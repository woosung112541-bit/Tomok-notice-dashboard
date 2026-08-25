"""
engine.py
---------
예전에는 '빠른/정밀/극한/주요4대' 라는 이름의 스크립트 4벌을 사람이 직접 골라야 했다.
여기서는 그 선택을 없애고, 사이트 하나하나에 대해 시스템이 자동으로 다음 순서로
시도한다 (제미나이 원칙 #1, #3을 그대로 코드화):

    1) custom  : site_registry가 'custom'으로 분류한 사이트는 전용 핸들러로 직행
                 (KHNP, 아이건설넷처럼 로그인/팝업/다단계 클릭이 필요한 곳)
    2) requests: 가볍고 빠른 1차 시도
    3) selenium: requests에서 행을 하나도 못 찾았을 때만(=JS 렌더링 필요 가능성) 승격
    4) manual  : selenium까지 실패하면 자동화를 포기하고 '수동 확인 목록'에 등록
                 (조용히 실패하는 대신, 사람이 봐야 할 목록에 명시적으로 올린다)

동시성: requests 사이트는 병렬 수를 높게, selenium(무거움)은 낮게 유지해서
Streamlit Cloud 같은 자원이 제한된 환경에서 메모리 폭발을 막는다.
"""

import concurrent.futures

import config
from scrapers import generic_requests, generic_selenium
from scrapers.custom import khnp, igunsul
from scrapers.base import discover_additional_boards
from utils.logging_setup import log_info, log_manual_required

CUSTOM_HANDLERS = {
    "khnp": khnp.scrape,
    "igunsul": igunsul.scrape,
}


def _handler_key_for_domain(domain: str) -> str | None:
    for known_domain, key in config.CUSTOM_HANDLER_DOMAINS.items():
        if known_domain in domain:
            return key
    return None


def _known_hard_reason_for_domain(domain: str) -> str | None:
    """config.KNOWN_HARD_DOMAINS는 부분 문자열(예: 'khnp.co.kr')로 등록되므로
    dict.get()의 완전 일치가 아니라 부분 일치로 찾아야 한다."""
    for known_domain, reason in config.KNOWN_HARD_DOMAINS.items():
        if known_domain in domain:
            return reason
    return None


def process_site(site: dict, target_date_limit, keywords: list[str]) -> dict:
    """사이트 하나를 처리하고 결과 dict를 반환한다.
    반환 형태: {org_name, base_url, notices, found, manual_required, manual_reason}
    """
    org_name, base_url, domain = site["org_name"], site["url"], site["domain"]

    if site["handler_type"] == "custom":
        handler_key = _handler_key_for_domain(domain)
        handler_fn = CUSTOM_HANDLERS.get(handler_key)
        notices = handler_fn(base_url, org_name, target_date_limit, keywords) if handler_fn else []
        if not notices:
            reason = _known_hard_reason_for_domain(domain) or "전용 핸들러 실행 결과 0건 (로그 확인 필요)"
            log_manual_required(org_name, base_url, reason)
            return {"org_name": org_name, "base_url": base_url, "notices": [],
                    "found": False, "manual_required": True, "manual_reason": reason}
        return {"org_name": org_name, "base_url": base_url, "notices": notices,
                "found": True, "manual_required": False, "manual_reason": ""}

    # ── generic: requests 먼저, 추가 게시판 후보도 함께 시도 ──────────────────
    candidate_urls = [base_url] + discover_additional_boards(base_url, domain)
    all_notices = []
    any_rows_found = False

    for u in candidate_urls:
        notices, rows_count = generic_requests.scrape_board(u, org_name, target_date_limit, keywords)
        all_notices.extend(notices)
        if rows_count > 0:
            any_rows_found = True

    if not any_rows_found:
        # requests로 행 자체를 못 찾음 -> JS 렌더링이 필요한 사이트일 가능성 -> selenium으로 승격
        for u in candidate_urls:
            notices, rows_count = generic_selenium.scrape_board(u, org_name, target_date_limit, keywords)
            all_notices.extend(notices)
            if rows_count > 0:
                any_rows_found = True  # selenium은 게시판을 정상적으로 찾음 (조건에 맞는 공고가 없을 뿐일 수 있음)

    if not all_notices and not any_rows_found:
        reason = "requests·selenium 모두 게시판 행을 찾지 못함 (게시판 구조 확인 필요)"
        log_manual_required(org_name, base_url, reason)
        return {"org_name": org_name, "base_url": base_url, "notices": [],
                "found": False, "manual_required": True, "manual_reason": reason}

    return {"org_name": org_name, "base_url": base_url, "notices": all_notices,
            "found": len(all_notices) > 0, "manual_required": False, "manual_reason": ""}


def run_all_sites(all_sites: list[dict], target_date_limit, keywords: list[str]) -> dict:
    """
    사이트 목록을 병렬로 처리한다. requests류와 selenium/custom류를 분리해서
    서로 다른 동시성 수준으로 실행한다 (무거운 selenium을 과도하게 병렬로 띄우지 않기 위함).
    """
    light_sites = [s for s in all_sites if s["handler_type"] == "generic"]
    heavy_sites = [s for s in all_sites if s["handler_type"] == "custom"]

    all_notices, collected_orgs, manual_check_items = [], set(), []

    def _handle_result(res: dict):
        log_info(f"[완료] {res['org_name']} ({len(res['notices'])}건)"
                 + (" - 수동확인 필요" if res["manual_required"] else ""))
        if res["found"]:
            collected_orgs.add(res["org_name"])
            all_notices.extend(res["notices"])
        if res["manual_required"]:
            manual_check_items.append({
                "발주처": res["org_name"], "URL": res["base_url"],
                "사유": res["manual_reason"], "최종확인시각": "",
            })

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.MAX_WORKERS_LIGHT) as executor:
        futures = {executor.submit(process_site, s, target_date_limit, keywords): s for s in light_sites}
        for future in concurrent.futures.as_completed(futures):
            _handle_result(future.result())

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.MAX_WORKERS_SELENIUM) as executor:
        futures = {executor.submit(process_site, s, target_date_limit, keywords): s for s in heavy_sites}
        for future in concurrent.futures.as_completed(futures):
            _handle_result(future.result())

    return {
        "all_notices": all_notices,
        "collected_orgs": collected_orgs,
        "manual_check_items": manual_check_items,
    }

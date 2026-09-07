"""
engine.py
-----------
사이트 하나를 처리하는 로직(process_site)과, 여러 사이트를 병렬로 돌리는
오케스트레이션(run_all_sites)을 담당한다.

단계적 자동 처리:
1) custom (khnp, igunsul, d2b): 전용 핸들러 직행
2) requests + discover_additional_boards: 네트워크 실패 시 selenium 재시도 스킵
3) selenium: 행 카운트 반환
4) 전부 실패 시: 사유별 분류(클라우드IP차단/조달청이관/구조문제) -> manual_check 탭
"""

import concurrent.futures
import time

import config
from scrapers import generic_requests, generic_selenium
from scrapers.custom import khnp, igunsul, d2b
from scrapers.base import discover_additional_boards
from utils.logging_setup import log_info, log_manual_required

CUSTOM_HANDLERS = {
    "khnp": khnp.scrape,
    "igunsul": igunsul.scrape,
    "d2b": d2b.scrape,
}


def _handler_key_for_domain(domain: str) -> str | None:
    for known_domain, key in config.CUSTOM_HANDLER_DOMAINS.items():
        if known_domain in domain:
            return key
    return None


def _known_hard_reason_for_domain(domain: str) -> str | None:
    """config.KNOWN_HARD_SITES는 부분 문자열(예: 'khnp.co.kr')로 등록되므로
    dict.get()의 완전 일치가 아니라 부분 일치로 찾아야 한다."""
    for known_domain, info in config.KNOWN_HARD_SITES.items():
        if known_domain in domain:
            return info["reason"]
    return None


def process_site(site: dict, target_date_limit, keywords: list[str], history_keys: set) -> dict:
    """사이트 하나를 처리하고 결과 dict를 반환한다.
    반환 형태: {org_name, base_url, notices, excluded_notices, found, manual_required,
    manual_reason, method_used, elapsed_seconds}

    method_used: "custom" / "requests" / "selenium" 중 최종적으로 결과를 만들어낸(또는
    실패한) 방식. "AI 전수조사 로그"에서 '어떤 방식이 이 사이트에 먹혔는지'를 한눈에
    보기 위한 것으로, 실제 수집 로직에는 영향을 주지 않는다.
    """
    start_time = time.time()
    org_name, base_url, domain = site["org_name"], site["url"], site["domain"]

    if site["handler_type"] == "custom":
        handler_key = _handler_key_for_domain(domain)
        handler_fn = CUSTOM_HANDLERS.get(handler_key)
        notices, excluded_notices = handler_fn(base_url, org_name, target_date_limit, keywords) if handler_fn else ([], [])
        elapsed = round(time.time() - start_time, 1)
        if not notices:
            reason = _known_hard_reason_for_domain(domain) or "전용 핸들러 실행 결과 0건 (로그 확인 필요)"
            log_manual_required(org_name, base_url, reason)
            return {"org_name": org_name, "base_url": base_url, "notices": [], "excluded_notices": excluded_notices,
                    "found": False, "manual_required": True, "manual_reason": reason,
                    "method_used": "custom", "elapsed_seconds": elapsed}
        return {"org_name": org_name, "base_url": base_url, "notices": notices, "excluded_notices": excluded_notices,
                "found": True, "manual_required": False, "manual_reason": "",
                "method_used": "custom", "elapsed_seconds": elapsed}

    # ── generic: requests 먼저, 추가 게시판 후보(iframe/메뉴링크)도 함께 시도 ────
    candidate_urls = [base_url] + discover_additional_boards(base_url, domain)
    all_notices = []
    all_excluded = []
    any_rows_found = False
    any_network_error = False
    method_used = "requests"

    for u in candidate_urls:
        notices, excluded, rows_count, network_error = generic_requests.scrape_board(
            u, org_name, target_date_limit, keywords, history_keys)
        all_notices.extend(notices)
        all_excluded.extend(excluded)
        if rows_count > 0:
            any_rows_found = True
        if network_error:
            any_network_error = True

    if not any_rows_found and not any_network_error:
        # requests로 행 자체를 못 찾음(단, 연결 자체는 됐던 경우만) -> JS 렌더링이 필요한
        # 사이트일 가능성 -> selenium으로 승격.
        # 연결 자체가 안 됐던 경우(any_network_error=True)는 selenium으로 다시 시도해봐야
        # 같은 네트워크 경로로 나가는 이상 똑같이 막힐 뿐이라 시간만 낭비한다 (사이트당
        # 수십 초씩 허비 -> 차단된 사이트가 많을 때 전체 실행 시간이 크게 늘어나는 원인이었음).
        method_used = "selenium"
        for u in candidate_urls:
            notices, excluded, rows_count, network_error = generic_selenium.scrape_board(
                u, org_name, target_date_limit, keywords, history_keys)
            all_notices.extend(notices)
            all_excluded.extend(excluded)
            if rows_count > 0:
                any_rows_found = True  # selenium은 게시판을 정상적으로 찾음 (조건에 맞는 공고가 없을 뿐일 수 있음)
            if network_error:
                any_network_error = True

    elapsed = round(time.time() - start_time, 1)

    if not all_notices and not any_rows_found:
        if any_network_error:
            reason = ("서버 접속 자체가 시간 초과됨 - 이 사이트가 현재 실행 위치(클라우드 IP)의 "
                       "접속을 막고 있을 가능성이 높음 (셀렉터 문제가 아님, 국내 IP 경유가 필요할 수 있음)")
        elif config.G2B_MIGRATION_HINT in org_name or org_name in config.KNOWN_G2B_REDIRECT_ORGS:
            reason = ("이 발주처는 자체 게시판에 공고가 없고 나라장터로 이관/연결된 것으로 확인됨 "
                       "(나라장터 API로 별도 수집되고 있으니 실제 문제가 아님)")
        else:
            reason = "requests·selenium 모두 게시판 행을 찾지 못함 (게시판 구조 확인 필요)"
        log_manual_required(org_name, base_url, reason)
        return {"org_name": org_name, "base_url": base_url, "notices": [], "excluded_notices": all_excluded,
                "found": False, "manual_required": True, "manual_reason": reason,
                "method_used": method_used, "elapsed_seconds": elapsed}

    return {"org_name": org_name, "base_url": base_url, "notices": all_notices, "excluded_notices": all_excluded,
            "found": len(all_notices) > 0, "manual_required": False, "manual_reason": "",
            "method_used": method_used, "elapsed_seconds": elapsed}


def run_all_sites(all_sites: list[dict], target_date_limit, keywords: list[str],
                   history_keys: set | None = None) -> dict:
    """light(generic) 사이트는 넉넉한 스레드로, heavy(custom, 브라우저 직접 조작)
    사이트는 적은 스레드로 병렬 처리한다."""
    history_keys = history_keys or set()
    light_sites = [s for s in all_sites if s["handler_type"] == "generic"]
    heavy_sites = [s for s in all_sites if s["handler_type"] == "custom"]
    total = len(light_sites) + len(heavy_sites)
    completed = 0

    all_notices, all_excluded_notices, collected_orgs, manual_check_items = [], [], set(), []
    site_results = []  # AI 전수조사 로그용 - 성공/실패 관계없이 사이트마다 한 줄씩 쌓는다

    def _handle_result(res: dict):
        nonlocal completed
        completed += 1
        log_info(f"[완료] {res['org_name']} ({len(res['notices'])}건)"
                 + (" - 실패 로그 등록" if res["manual_required"] else ""))
        print(f"PROGRESS:{completed}:{total}", flush=True)
        if res["found"]:
            collected_orgs.add(res["org_name"])
            all_notices.extend(res["notices"])
        all_excluded_notices.extend(res.get("excluded_notices", []))
        if res["manual_required"]:
            manual_check_items.append({
                "발주처": res["org_name"], "URL": res["base_url"],
                "사유": res["manual_reason"], "최종확인시각": "",
            })
        site_results.append({
            "발주처": res["org_name"],
            "URL": res["base_url"],
            "처리방식": res.get("method_used", "-"),
            "결과": "실패(수동확인)" if res["manual_required"] else ("성공" if res["found"] else "성공(0건)"),
            "수집건수": len(res["notices"]),
            "제외건수": len(res.get("excluded_notices", [])),
            "소요시간(초)": res.get("elapsed_seconds", ""),
            "사유": res["manual_reason"],
        })

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.MAX_WORKERS_LIGHT) as executor:
        futures = {executor.submit(process_site, s, target_date_limit, keywords, history_keys): s
                   for s in light_sites}
        for future in concurrent.futures.as_completed(futures):
            _handle_result(future.result())

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.MAX_WORKERS_SELENIUM) as executor:
        futures = {executor.submit(process_site, s, target_date_limit, keywords, history_keys): s
                   for s in heavy_sites}
        for future in concurrent.futures.as_completed(futures):
            _handle_result(future.result())

    return {
        "all_notices": all_notices,
        "excluded_notices": all_excluded_notices,
        "collected_orgs": collected_orgs,
        "manual_check_items": manual_check_items,
        "site_results": site_results,
    }

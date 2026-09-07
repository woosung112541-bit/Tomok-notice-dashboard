"""
main.py
---------
CLI 진입점. 사용 예:
    python main.py 15 "모집,안전,공고" ALL
    python main.py 15 "모집,안전,공고" "보령시(건설과),아산시" 0

인자: [days_ago] [keywords(콤마구분)] [target_orgs("ALL" 또는 콤마구분)] [use_proxy(0/1)]
"""

import os
import sys
import time
import uuid
import warnings
from datetime import datetime, timedelta, timezone

import urllib3

import config
import storage
import site_registry
import engine
from scrapers import api_g2b
from utils import proxy as proxy_util
from utils.logging_setup import log_info, log_failure, log_system_note, RUN_LOG

warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

KST = timezone(timedelta(hours=9))


def parse_args():
    args = sys.argv[1:]
    days_ago = int(args[0]) if len(args) > 0 and args[0] else config.DEFAULT_DAYS_AGO
    keywords_str = args[1] if len(args) > 1 and args[1] else ", ".join(config.DEFAULT_KEYWORDS)
    keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
    target_orgs = args[2] if len(args) > 2 and args[2] else "ALL"
    use_proxy = args[3] == "1" if len(args) > 3 else False
    return days_ago, keywords, target_orgs, use_proxy


def main():
    run_start_time = time.time()
    run_id = datetime.now(KST).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    # GitHub Actions는 항상 GITHUB_ACTIONS=true 환경변수를 심어준다 - 이걸로
    # "클라우드(Streamlit)"에서 돌았는지 "사무실 PC(GitHub Actions)"에서 돌았는지 구분한다.
    run_location = "사무실 PC(GitHub Actions)" if os.environ.get("GITHUB_ACTIONS") == "true" else "클라우드(Streamlit)"

    days_ago, keywords, target_orgs, use_proxy = parse_args()
    target_date_limit = datetime.now(KST).replace(tzinfo=None) - timedelta(days=days_ago)
    current_time = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

    storage.write_key_file_from_secret()

    if use_proxy:
        proxy_url = proxy_util.pick_working_proxy()
        if proxy_url:
            os.environ["HTTP_PROXY"] = proxy_url
            os.environ["HTTPS_PROXY"] = proxy_url
            os.environ["USE_PROXY_ACTIVE"] = "1"
    else:
        log_system_note("proxy_status", "프록시 미사용 (토글 꺼짐)")

    log_info(f"[시작] 대상 기간: 최근 {days_ago}일 / 키워드: {keywords} / "
             f"발주처: {'전수조사' if target_orgs == 'ALL' else target_orgs}")

    try:
        _, doc = storage.connect()
    except storage.SheetUnavailable as e:
        log_failure("시스템", "-", "connect", e)
        return

    if storage.manage_sheet_lock(doc, "check"):
        log_info("다른 실행이 이미 진행 중입니다. 종료합니다.")
        return
    storage.manage_sheet_lock(doc, "lock_and_log")

    try:
        ctx = storage.load_run_context(doc)

        base_dir = os.path.dirname(os.path.abspath(__file__))

        # target_orgs 안에 "나라장터 (API - ...)" 가짜 항목이 섞여 있을 수 있다 (사용자가
        # 드롭다운에서 나라장터만 빠르게 확인하려고 고른 경우). 이건 실제 게시판이
        # 아니므로 site_registry에는 넘기지 않고, 대신 나라장터 API를 호출할지 여부를
        # 결정하는 데만 쓴다.
        requested_orgs = [] if target_orgs == "ALL" else [o.strip() for o in target_orgs.split(",")]
        want_g2b = (target_orgs == "ALL") or (config.G2B_VIRTUAL_ORG_NAME in requested_orgs)
        real_orgs = [o for o in requested_orgs if o != config.G2B_VIRTUAL_ORG_NAME]
        site_target_orgs = target_orgs if target_orgs == "ALL" else (",".join(real_orgs) if real_orgs else None)

        all_sites = []
        if site_target_orgs:
            all_sites = site_registry.build_target_sites(base_dir, ctx["url_overrides"], site_target_orgs)

        if not all_sites and not want_g2b:
            log_info("대상 사이트가 없습니다 (명부 확인 필요).")
            return

        run_result = {"all_notices": [], "excluded_notices": [], "collected_orgs": set(), "manual_check_items": [],
                       "site_results": []}
        if all_sites:
            log_info(f"대상 사이트 {len(all_sites)}곳 처리 시작")
            run_result = engine.run_all_sites(all_sites, target_date_limit, keywords, ctx["history_keys"])

        all_notices = run_result["all_notices"]
        all_excluded = run_result["excluded_notices"]

        if want_g2b:
            g2b_notices, g2b_excluded = api_g2b.fetch(config.G2B_API_KEY, days_ago)
            all_notices.extend(g2b_notices)
            all_excluded.extend(g2b_excluded)
            log_info(f"[나라장터 API] {len(g2b_notices)}건 수집 / {len(g2b_excluded)}건 자동 제외")

        added = storage.append_notices(ctx["ws_notices"], all_notices, ctx["history_keys"], current_time)
        excluded_history_keys = storage.load_excluded_history_keys(doc)
        added_excluded = storage.append_excluded_notices(doc, all_excluded, excluded_history_keys, current_time)
        storage.append_collected_orgs(ctx["ws_collected"], run_result["collected_orgs"])
        storage.write_manual_check_list(doc, run_result["manual_check_items"])
        storage.write_run_log(doc, RUN_LOG)

        # "🗒️ 전수조사 로그 (AI 분석용)" - 성공/실패 관계없이 이번 실행 전체를 기록한다.
        # run_log(실패 로그)에는 성공한 사이트가 하나도 안 남아서, "84곳 중 정확히
        # 몇 곳이 어떤 방식으로 성공/실패했는지" 전체 그림을 볼 방법이 없었다.
        site_results = run_result.get("site_results", [])
        storage.write_site_results(doc, run_id, current_time, site_results)

        success_count = sum(1 for r in site_results if r["결과"].startswith("성공"))
        fail_count = sum(1 for r in site_results if r["결과"].startswith("실패"))
        total_elapsed = round(time.time() - run_start_time, 1)
        storage.write_run_summary(doc, {
            "실행ID": run_id,
            "시작시각": current_time,
            "종료시각": datetime.now(KST).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
            "총소요시간(초)": total_elapsed,
            "실행위치": run_location,
            "수집기간(일)": days_ago,
            "키워드": ", ".join(keywords),
            "대상발주처": target_orgs,
            "프록시사용": "예" if use_proxy else "아니오",
            "전체사이트수": len(site_results),
            "성공수": success_count,
            "실패_수동확인수": fail_count,
            "신규공고수": added,
            "자동제외수": added_excluded,
        })

        log_info(f"[종료] 신규 공고 {added}건 저장 완료 / 자동 제외 {added_excluded}건 / "
                 f"수동확인 필요 {len(run_result['manual_check_items'])}곳 / "
                 f"경고·오류 로그 {len(RUN_LOG)}건 / 총 소요시간 {total_elapsed}초")
    finally:
        storage.manage_sheet_lock(doc, "unlock")


if __name__ == "__main__":
    main()

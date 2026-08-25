"""
main.py
-------
공고 자동 수집 실행 진입점.

사용법:
    python main.py [DAYS_AGO] [키워드1,키워드2,...] [발주처1,발주처2,... | ALL]

예:
    python main.py 15 "모집,안전,공고" ALL
    python main.py 0 "안전점검" "한국시설안전협회,아이건설넷"

과거에는 main.py / main_major.py / main_max.py / main_pure.py 4개로 나뉘어 있던
'엔진'을 하나로 통합했다. 사이트별 처리 방식(requests/selenium/custom)은
site_registry.py + engine.py가 자동으로 결정하므로, 더 이상 사람이 엔진을 선택할
필요가 없다.
"""

import os
import sys
import warnings
from datetime import datetime, timedelta, timezone

import urllib3

import config
import storage
import site_registry
import engine
from scrapers import api_g2b
from utils.logging_setup import log_info, log_failure, RUN_LOG

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", module="bs4")

KST = timezone(timedelta(hours=9))


def parse_args():
    days_ago = config.DEFAULT_DAYS_AGO
    keywords = config.DEFAULT_KEYWORDS
    target_orgs = "ALL"

    if len(sys.argv) >= 2:
        try:
            days_ago = int(sys.argv[1])
        except ValueError:
            pass
    if len(sys.argv) >= 3:
        keywords = [w.strip() for w in sys.argv[2].split(",") if w.strip()]
    if len(sys.argv) >= 4:
        target_orgs = sys.argv[3]

    return days_ago, keywords, target_orgs


def main():
    days_ago, keywords, target_orgs = parse_args()

    now_kst = datetime.now(KST).replace(tzinfo=None)
    if days_ago == 0:
        target_date_limit = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        target_date_limit = now_kst - timedelta(days=days_ago)
    current_time = now_kst.strftime("%Y-%m-%d %H:%M:%S")

    log_info(f"[시작] 대상 기간: 최근 {days_ago}일 / 키워드: {keywords} / "
             f"발주처: {'전수조사' if target_orgs == 'ALL' else target_orgs}")

    storage.write_key_file_from_secret()
    try:
        gc, doc = storage.connect()
    except storage.SheetUnavailable as e:
        log_failure("시스템", "-", "google_sheet_connect", e)
        sys.exit(1)

    ctx = storage.load_run_context(doc)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    all_sites = site_registry.build_target_sites(base_dir, ctx["url_overrides"], target_orgs)

    if not all_sites:
        log_info("대상 사이트가 없습니다 (명부 확인 필요).")
        sys.exit(0)

    log_info(f"대상 사이트 {len(all_sites)}곳 처리 시작")
    run_result = engine.run_all_sites(all_sites, target_date_limit, keywords)

    all_notices = run_result["all_notices"]

    if target_orgs == "ALL":
        g2b_notices = api_g2b.fetch(config.G2B_API_KEY, days_ago, keywords)
        all_notices.extend(g2b_notices)
        log_info(f"[나라장터 API] {len(g2b_notices)}건 수집")

    added = storage.append_notices(ctx["ws_notices"], all_notices, ctx["history_keys"], current_time)
    storage.append_collected_orgs(ctx["ws_collected"], run_result["collected_orgs"])
    storage.write_manual_check_list(doc, run_result["manual_check_items"])
    storage.write_run_log(doc, RUN_LOG)

    log_info(f"[종료] 신규 공고 {added}건 저장 완료 / "
             f"수동확인 필요 {len(run_result['manual_check_items'])}곳 / "
             f"경고·오류 로그 {len(RUN_LOG)}건")


if __name__ == "__main__":
    main()

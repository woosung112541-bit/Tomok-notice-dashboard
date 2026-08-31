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
from utils import proxy as proxy_util
from utils.logging_setup import log_info, log_failure, log_system_note, RUN_LOG

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", module="bs4")

KST = timezone(timedelta(hours=9))


def parse_args():
    days_ago = config.DEFAULT_DAYS_AGO
    keywords = config.DEFAULT_KEYWORDS
    target_orgs = "ALL"
    use_proxy = False

    if len(sys.argv) >= 2:
        try:
            days_ago = int(sys.argv[1])
        except ValueError:
            pass
    if len(sys.argv) >= 3:
        keywords = [w.strip() for w in sys.argv[2].split(",") if w.strip()]
    if len(sys.argv) >= 4:
        target_orgs = sys.argv[3]
    if len(sys.argv) >= 5:
        use_proxy = sys.argv[4] in ("1", "true", "True")

    return days_ago, keywords, target_orgs, use_proxy


def main():
    days_ago, keywords, target_orgs, use_proxy = parse_args()

    if use_proxy:
        found_proxy = proxy_util.pick_working_proxy()
        if found_proxy:
            # requests는 HTTP_PROXY/HTTPS_PROXY 환경변수를 자동으로 읽어서 쓰므로
            # 코드 안의 모든 requests.get() 호출에 별도 수정 없이 그대로 적용된다.
            os.environ["HTTP_PROXY"] = f"http://{found_proxy}"
            os.environ["HTTPS_PROXY"] = f"http://{found_proxy}"
            # selenium(Chrome)은 환경변수를 자동으로 안 읽으므로 별도 변수에 담아두고
            # scrapers/generic_selenium.py의 get_driver()가 이 값을 읽어 명시적으로 적용한다.
            os.environ["SCRAPER_SELENIUM_PROXY"] = found_proxy
            log_system_note("proxy_status", f"프록시 사용함: {found_proxy}")
        else:
            log_system_note("proxy_status", "프록시 사용 시도했지만 살아있는 프록시를 찾지 못해 직접 연결로 진행")
    else:
        log_system_note("proxy_status", "프록시 미사용 (토글 꺼짐)")

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

    # 잠금 관리를 main.py 안으로 옮겨서, Streamlit 버튼이든 GitHub Actions(사무실 PC)든
    # 실행 경로에 상관없이 서로의 실행 여부를 알 수 있게 한다. (예전에는 app.py의
    # 구독형 실행 흐름에만 잠금이 있어서, 다른 경로로 실행하면 서로 못 알아챘다.)
    if storage.manage_sheet_lock(doc, "check"):
        log_info("다른 실행이 이미 진행 중인 것으로 확인됨 - 중복 실행을 막기 위해 종료합니다.")
        sys.exit(0)
    storage.manage_sheet_lock(doc, "lock_and_log", engine_name="통합 엔진")

    try:
        ctx = storage.load_run_context(doc)

        base_dir = os.path.dirname(os.path.abspath(__file__))
        all_sites = site_registry.build_target_sites(base_dir, ctx["url_overrides"], target_orgs)

        if not all_sites:
            log_info("대상 사이트가 없습니다 (명부 확인 필요).")
            return

        log_info(f"대상 사이트 {len(all_sites)}곳 처리 시작")
        run_result = engine.run_all_sites(all_sites, target_date_limit, keywords, ctx["history_keys"])

        all_notices = run_result["all_notices"]

        if target_orgs == "ALL":
            g2b_notices = api_g2b.fetch(config.G2B_API_KEY, days_ago)
            all_notices.extend(g2b_notices)
            log_info(f"[나라장터 API] {len(g2b_notices)}건 수집")

        added = storage.append_notices(ctx["ws_notices"], all_notices, ctx["history_keys"], current_time)
        storage.append_collected_orgs(ctx["ws_collected"], run_result["collected_orgs"])
        storage.write_manual_check_list(doc, run_result["manual_check_items"])
        storage.write_run_log(doc, RUN_LOG)

        log_info(f"[종료] 신규 공고 {added}건 저장 완료 / "
                 f"수동확인 필요 {len(run_result['manual_check_items'])}곳 / "
                 f"경고·오류 로그 {len(RUN_LOG)}건")
    finally:
        storage.manage_sheet_lock(doc, "unlock")


if __name__ == "__main__":
    main()

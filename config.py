"""
config.py
---------
프로젝트 전역 설정과 '시크릿(비밀값)' 로딩을 담당한다.

시크릿(자격증명)은 절대 이 파일이나 다른 코드 파일에 직접 적지 않는다.
아래 우선순위로 자동으로 찾아서 읽어온다.

1) 환경변수 (GitHub Actions Secrets 등에서 주입)
2) Streamlit secrets (.streamlit/secrets.toml, 또는 Streamlit Cloud의 Secrets 설정)

로컬에서 테스트할 때는 `.streamlit/secrets.toml` (아래 예시 파일 `secrets.toml.example` 참고)
또는 환경변수로 아래 값을 채워 넣으면 된다.

  GOOGLE_CREDENTIALS   : 구글 서비스 계정 키 JSON 전체 내용 (문자열)
  G2B_API_KEY          : 나라장터(조달청) OpenAPI 서비스키
  IGUNSUL_ID           : 아이건설넷 로그인 ID
  IGUNSUL_PW           : 아이건설넷 로그인 비밀번호
  DASHBOARD_PASSWORD   : Streamlit 대시보드 접속 비밀번호
"""

import os

try:
    import streamlit as st
except ImportError:  # main.py를 CLI/GitHub Actions에서 단독 실행할 때는 streamlit이 없을 수 있음
    st = None


def get_secret(key: str, default: str = "") -> str:
    """환경변수 -> Streamlit secrets 순서로 값을 찾는다. 코드에 직접 값을 적지 않기 위함."""
    val = os.environ.get(key)
    if val:
        return val
    if st is not None:
        try:
            return st.secrets.get(key, default)
        except Exception:
            pass
    return default


# ── 시크릿 (하드코딩 금지! 반드시 get_secret으로 로드) ─────────────────────────
G2B_API_KEY = get_secret("G2B_API_KEY")
IGUNSUL_ID = get_secret("IGUNSUL_ID")
IGUNSUL_PW = get_secret("IGUNSUL_PW")
DASHBOARD_PASSWORD = get_secret("DASHBOARD_PASSWORD", "0804")

# ── 구글 시트 ────────────────────────────────────────────────────────────────
GOOGLE_KEY_FILE = "google_key.json"  # get_secret("GOOGLE_CREDENTIALS")를 이 경로에 런타임에 기록해서 사용
GOOGLE_SHEET_NAME = "맞춤공고_DB"
SHEET_NOTICES = "notices"
SHEET_COLLECTED_ORGS = "collected_orgs"
SHEET_EMPTY_ORGS = "empty_orgs"
SHEET_URL_OVERRIDES = "url_overrides"
SHEET_SETTINGS = "settings"
SHEET_RUN_LOG = "run_log"          # 신규: 실행 로그(실패 사유 포함)를 구글시트에 남겨 대시보드에서 확인
SHEET_MANUAL_CHECK = "manual_check"  # 신규: 자동 수집이 불가능하다고 판단된 발주처 목록

# ── 입력 명부 엑셀 ───────────────────────────────────────────────────────────
INPUT_EXCEL_FILENAME = "등록명부 정리시트.xlsx"
ORG_NAME_COL_INDEX = 2   # '발주처' 열
URL_COL_INDEX = 9        # '링크' 열

# ── 수집 기본값 ──────────────────────────────────────────────────────────────
DEFAULT_DAYS_AGO = 15
DEFAULT_KEYWORDS = ["모집", "안전", "공고"]

BOARD_MENU_KEYWORDS = ["고시공고", "고시", "공고", "입찰", "발주", "새소식", "공지", "알림", "소식", "게시판"]

COMMON_ROW_SELECTORS = [
    "table.board_list tbody tr", "table.board-list tbody tr",
    "div.board_list tbody tr", ".list_tbl tbody tr",
    "tbody > tr", "ul.board_list > li", "div.list > ul > li",
]

# 공고 본문 특이사항 태깅용 키워드 (업무 분류용, 필요 시 이 목록만 수정하면 전체 반영됨)
PLUS_KWS = ["종합", "토목", "안전점검", "수행기관", "대전"]
MINUS_KWS = ["건축분야", "신축", "번지", "증축", "수의", "건립"]
REGION_KWS = ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기',
              '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']
REGION_HINT_KWS = ['지역제한', '소재지', '영업소', '한정', '관내', '소재한', '위치한']

# 명부 엑셀 외에 항상 포함하는 사이트 (조달청 통합명부, 한국시설안전협회, 아이건설넷 등)
EXTRA_SITES = [
    {"url": "http://www.assi.or.kr/sub/board/gongji.asp?boardname=gongji", "org_name": "한국시설안전협회"},
    {"url": "https://www.pps.go.kr/kor/bbs/list.do?key=00641", "org_name": "조달청 통합명부"},
    {"url": "https://www.igunsul.net/", "org_name": "아이건설넷"},
]

# 도메인별 전용 처리기(scrapers/custom/*)로 보낼 도메인 매핑.
# 여기에 등록된 도메인은 requests/일반 selenium을 거치지 않고 바로 전용 핸들러로 간다.
CUSTOM_HANDLER_DOMAINS = {
    "khnp.co.kr": "khnp",
    "igunsul.net": "igunsul",
}

# 일반 Selenium(3단계)까지는 시도하지만, 그래도 안 되면 '수동 확인'으로 분류할 때 참고용으로
# 미리 알려진, 자동화가 특히 어려운 도메인 (봇 탐지/보안 프로그램 등)
KNOWN_HARD_DOMAINS = {
    "khnp.co.kr": "AnySign/TouchEn 등 보안 프로그램으로 자동화가 매우 어려움 (K-Pro 전자상거래시스템)",
}

REQUEST_TIMEOUT = 20
SELENIUM_PAGE_LOAD_TIMEOUT = 45
MAX_WORKERS_LIGHT = 4   # requests 전용 사이트 동시 처리 수
MAX_WORKERS_SELENIUM = 2  # Selenium을 쓰는 사이트는 메모리 문제로 동시 처리 수를 낮게 유지

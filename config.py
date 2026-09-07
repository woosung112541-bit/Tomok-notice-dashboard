"""
config.py
-----------
전체 시스템의 설정값을 한 곳에 모아둔다.

필요한 시크릿 목록 (Streamlit secrets.toml 또는 GitHub Actions repo secrets):
  GOOGLE_CREDENTIALS   : 구글 서비스계정 키 JSON 전체 내용
  G2B_API_KEY          : 공공데이터포털에서 발급받은 나라장터 API 인증키
  IGUNSUL_ID           : 아이건설넷 로그인 ID
  IGUNSUL_PW           : 아이건설넷 로그인 비밀번호
  DASHBOARD_PASSWORD   : Streamlit 대시보드 접속 비밀번호
  GITHUB_TOKEN         : GitHub Actions 원격 실행용 Fine-grained PAT (Actions R/W)
  GITHUB_REPO          : "owner/repo" 형식
"""

import os
import urllib.parse


def get_secret(key: str) -> str:
    """환경변수를 먼저 보고, 없으면 Streamlit secrets에서 찾는다."""
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(key, "")
    except Exception:
        return ""


GOOGLE_CREDENTIALS = get_secret("GOOGLE_CREDENTIALS")
G2B_API_KEY = get_secret("G2B_API_KEY")
IGUNSUL_ID = get_secret("IGUNSUL_ID")
IGUNSUL_PW = get_secret("IGUNSUL_PW")
DASHBOARD_PASSWORD = get_secret("DASHBOARD_PASSWORD")
GITHUB_TOKEN = get_secret("GITHUB_TOKEN")
GITHUB_REPO = get_secret("GITHUB_REPO")
GITHUB_BRANCH = "main"

# ── 요청 헤더 (User-Agent + 동적 Referer) ──────────────────────────────────────
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


def get_request_headers(url: str) -> dict:
    """URL별로 '그 사이트 홈페이지에서 자연스럽게 넘어온 것처럼' Referer를 붙여서
    반환한다. 일부 사이트(예: 세종도시교통공사)는 주소를 직접 쳐서 들어가면
    '처리 중 오류가 발생하였습니다' 같은 안내 페이지로 돌려보내고, 자기 사이트
    안에서 메뉴를 눌러 넘어온 경우에만 실제 내용을 보여주는 리퍼러 체크를 한다.
    Referer를 그 사이트 자신의 루트 주소로 채워서 보내면, 이런 단순 체크는
    대부분 통과한다 (서버가 별도 세션 상태까지 검사하는 아주 엄격한 경우는 예외)."""
    try:
        parsed = urllib.parse.urlparse(url)
        referer = f"{parsed.scheme}://{parsed.netloc}/"
    except Exception:
        referer = url
    return {**REQUEST_HEADERS, "Referer": referer}


# ── 타임아웃 설정 ────────────────────────────────────────────────────────────
REQUEST_CONNECT_TIMEOUT_DIRECT = 5
REQUEST_CONNECT_TIMEOUT_PROXY = 15
REQUEST_READ_TIMEOUT = 20
SELENIUM_PAGE_LOAD_TIMEOUT = 45


def get_request_timeout_tuple():
    """프록시 사용 여부(환경변수 USE_PROXY_ACTIVE)에 따라 연결 타임아웃을 동적으로
    조정한다 - 프록시를 거치면 왕복 지연이 커서 5초는 너무 짧다."""
    connect_timeout = (REQUEST_CONNECT_TIMEOUT_PROXY if os.environ.get("USE_PROXY_ACTIVE") == "1"
                        else REQUEST_CONNECT_TIMEOUT_DIRECT)
    return (connect_timeout, REQUEST_READ_TIMEOUT)


# ── 동시 처리량 ──────────────────────────────────────────────────────────────
MAX_WORKERS_LIGHT = 8       # requests/selenium 대상 일반 사이트
MAX_WORKERS_SELENIUM = 2    # 전용 핸들러(custom) 대상 - 브라우저를 직접 띄우므로 적게

MAX_PAGINATION_SAFETY_CAP = 8  # 페이지네이션 무한루프 방지 안전 상한

# ── 입력 명부 엑셀 ───────────────────────────────────────────────────────────
INPUT_EXCEL_FILENAME = "등록명부 정리시트.xlsx"
ORG_NAME_COL_INDEX = 2   # '발주처' 열
URL_COL_INDEX = 9        # '링크' 열

# ── 수집 기본값 ──────────────────────────────────────────────────────────────
DEFAULT_DAYS_AGO = 15
DEFAULT_KEYWORDS = ["모집", "안전", "공고", "진단", "정밀", "점검", "성능", "수행"]

# 제목에 이 단어들이 있으면 키워드가 맞아도 무조건 제외한다. 실사용 중 확인된,
# 우리 업무와 거의 무관한(약 99%) 공고 유형들 - 예: 공시송달/보상계획은 토지보상
# 행정절차 공고, 무연고/분묘개장은 장사 관련 행정공고, 기간제/수강생/합격자/임용은
# 채용·교육 공고, 모니터링은 다른 분야 용역 공고인 경우가 대부분이었다.
EXCLUDE_KEYWORDS = [
    "공시송달", "무연고", "견적제출공고", "기간제", "분묘개장",
    "주민등록", "보상계획", "수강생", "합격자", "임용", "모니터링",
]

# 위 EXCLUDE_KEYWORDS에 걸리더라도, 제목에 이 핵심 안전점검/진단 관련 단어가 있으면
# 무조건 살려서 포함시킨다. 예: "주민등록센터 증축 안전점검 수행기관 모집"은
# '주민등록'이 있어 제외 대상처럼 보이지만, '안전점검'이 있으므로 반드시 포함해야 한다.
CORE_SAFETY_KEYWORDS = [
    "안전점검", "안전진단", "정밀진단", "정밀점검", "초기점검",
    "정기안전점검", "정밀안전진단", "성능평가", "정밀안전점검",
    "공사재개전점검", "자체안전점검",
]

BOARD_MENU_KEYWORDS = ["고시공고", "고시", "공고", "입찰", "발주", "새소식", "공지", "알림", "소식", "게시판"]

COMMON_ROW_SELECTORS = [
    "table.board_list tbody tr", "table.board-list tbody tr",
    "div.board_list tbody tr", ".list_tbl tbody tr",
    "tbody > tr", "ul.board_list > li", "div.list > ul > li",
]

# 공고 본문 특이사항 태깅용 키워드 (업무 분류용, 필요 시 이 목록만 수정하면 전체 반영됨)
PLUS_KWS = ["종합", "토목", "안전점검", "수행기관", "대전"]
MINUS_KWS = ["건축분야", "신축", "번지", "증축", "수의", "건립"]
REGION_HINT_KWS = ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
                    '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']

# 명부 엑셀 외에 항상 포함하는 사이트 (조달청 통합명부, 한국시설안전협회, 아이건설넷 등)
EXTRA_SITES = [
    {"url": "http://www.assi.or.kr/sub/board/gongji.asp?boardname=gongji", "org_name": "한국시설안전협회"},
    {"url": "https://www.pps.go.kr/kor/bbs/list.do?key=00641", "org_name": "조달청 통합명부"},
    {"url": "https://www.igunsul.net/", "org_name": "아이건설넷"},
]

# "발주처 선택" 드롭다운에 표시되는 가짜(virtual) 항목. 실제 게시판을 스캔하는 사이트가
# 아니라 나라장터 Open API(scrapers/api_g2b.py)를 호출하는 것이므로, 등록명부에는
# 존재하지 않는다. 사용자가 이 항목만 선택하면 사이트 스캔 없이 API만 호출해서
# 84곳을 다 기다리지 않고 나라장터 결과만 빠르게 확인할 수 있다 (main.py 참고).
G2B_VIRTUAL_ORG_NAME = "나라장터 (API - 사이트 스캔 없이 바로 조회)"

# 도메인별 전용 처리기(scrapers/custom/*)로 보낼 도메인 매핑.
CUSTOM_HANDLER_DOMAINS = {
    "khnp.co.kr": "khnp",
    "igunsul.net": "igunsul",
    "d2b.go.kr": "d2b",
}

# 일반 Selenium(3단계)까지는 시도하지만, 그래도 안 되면 '실패 로그 분석'에서 참고용으로
# 보여줄 알려진 어려운 사이트 사유 (보안 프로그램, 로그인 필요 등).
KNOWN_HARD_SITES = {
    "khnp.co.kr": {"label": "한국수력원자력 K-Pro", "url": "https://ebiz.khnp.co.kr/login.do",
                   "reason": "AnySign/TouchEn 계열 보안 프로그램 사용 - 자동화가 사실상 불가능한 것으로 판단됨. 수동 확인 권장."},
}

# 명부 엑셀에서 팀이 이미 "*24년부터 조달청*" 식으로 표시해둔 기관들.
# 이런 기관은 자체 게시판에 입찰공고가 없는 게 정상일 수 있음(나라장터 API로 별도 수집됨).
# 자동 수집 자체는 그대로 시도하되(가끔 다른 공지사항이 올라오기도 하므로), 0건이 나왔을 때
# "구조가 깨졌다"는 오해를 주지 않도록 사유만 다르게 표시한다.
G2B_MIGRATION_HINT = "조달청"

# 위와 같은 상황(자체 게시판 없이 나라장터로 이관됨)인데, 발주처 이름에 "조달청"이라는
# 글자가 없어서 위 힌트로는 못 잡아내는 곳들. 실제로 사이트를 직접 확인해서 발견한
# 경우에 여기 추가한다 (예: 세종도시교통공사는 자체 사이트의 '입찰공고' 메뉴 자체가
# 클릭하면 나라장터로 리다이렉트되는 구조로, 실제 화면으로 직접 확인함).
KNOWN_G2B_REDIRECT_ORGS = {
    "세종도시교통공사",
}

# ── 무료 공개 프록시 우회 (대시보드 토글로 켜고 끔) ────────────────────────────
# ProxyScrape 무료 API - 회원가입/키 없이 한국(KR) IP 목록을 텍스트로 제공.
FREE_PROXY_API_URL = ("https://api.proxyscrape.com/v2/?request=getproxies&protocol=http"
                       "&timeout=5000&country=KR&ssl=all&anonymity=all")

# ── 구글시트 탭 이름 ─────────────────────────────────────────────────────────
SHEET_NOTICES = "notices"
SHEET_COLLECTED_ORGS = "collected_orgs"
SHEET_EMPTY_ORGS = "empty_orgs"
SHEET_URL_OVERRIDES = "url_overrides"
SHEET_SETTINGS = "settings"
SHEET_RUN_LOG = "run_log"          # 신규: 실행 로그(실패 사유 포함)를 구글시트에 남겨 대시보드에서 확인
SHEET_MANUAL_CHECK = "manual_check"  # 신규: 자동 수집이 불가능하다고 판단된 발주처 목록
SHEET_TEAM_NOTES = "team_notes"    # 신규: "게시판/메모장" 메뉴용 팀 공유 메모
SHEET_EXCLUDED_NOTICES = "excluded_notices"  # 신규: 제외 키워드에 걸려 자동 분류된 공고 목록
SHEET_SITE_RESULTS = "site_results"  # 신규: "AI 전수조사 로그" - 성공/실패 관계없이 사이트별 결과
SHEET_RUN_SUMMARY = "run_summary"    # 신규: "AI 전수조사 로그" - 실행 1회당 요약 1줄

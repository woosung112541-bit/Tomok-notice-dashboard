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

# 대시보드의 '🏢 사무실 PC로 확실하게 수집' 버튼용 - GitHub Actions 워크플로우를
# 원격으로 실행시키기 위한 값. GITHUB_TOKEN은 이 저장소에 대해
# 'Actions: Read and write' 권한이 있는 Personal Access Token, GITHUB_REPO는
# "owner/repository" 형식(예: "nc-company/Tomok-notice-dashboard").
# 둘 다 없으면 그 버튼은 자동으로 비활성화된다(github_actions.is_configured() 참고).
GITHUB_TOKEN = get_secret("GITHUB_TOKEN")
GITHUB_REPO = get_secret("GITHUB_REPO")
GITHUB_BRANCH = get_secret("GITHUB_BRANCH", "main")

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
SHEET_TEAM_NOTES = "team_notes"    # 신규: "게시판/메모장" 메뉴용 팀 공유 메모
SHEET_EXCLUDED_NOTICES = "excluded_notices"  # 신규: 제외 키워드에 걸려 자동 분류된 공고 목록

# ── 입력 명부 엑셀 ───────────────────────────────────────────────────────────
INPUT_EXCEL_FILENAME = "등록명부 정리시트.xlsx"
ORG_NAME_COL_INDEX = 2   # '발주처' 열
URL_COL_INDEX = 9        # '링크' 열

# ── 수집 기본값 ──────────────────────────────────────────────────────────────
DEFAULT_DAYS_AGO = 15
DEFAULT_KEYWORDS = ["모집", "안전", "공고", "진단", "정밀"]

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
REGION_KWS = ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기',
              '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']
REGION_HINT_KWS = ['지역제한', '소재지', '영업소', '한정', '관내', '소재한', '위치한']

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
# 여기에 등록된 도메인은 requests/일반 selenium을 거치지 않고 바로 전용 핸들러로 간다.
CUSTOM_HANDLER_DOMAINS = {
    "khnp.co.kr": "khnp",
    "igunsul.net": "igunsul",
}

# 일반 Selenium(3단계)까지는 시도하지만, 그래도 안 되면 '실패 로그 분석'에서 참고용으로
# 보여줄, 미리 알려진 자동화가 특히 어려운 사이트(봇 탐지/보안 프로그램 등).
# url은 '바로가기' 버튼이 실제로 열어야 할 정확한 페이지(도메인 루트가 아니라 실제 조회 화면).
KNOWN_HARD_SITES = {
    "khnp.co.kr": {
        "label": "한국수력원자력 K-Pro",
        "url": "https://ebiz.khnp.co.kr/login.do",
        "reason": "AnySign/TouchEn 등 보안 프로그램으로 자동화가 매우 어려움 (K-Pro 전자상거래시스템)",
    },
}

# 명부 엑셀에서 팀이 이미 "*24년부터 조달청*" 식으로 표시해둔 기관들.
# 이런 기관은 자체 게시판에 입찰공고가 없는 게 정상일 수 있음(나라장터 API로 별도 수집됨).
# 자동 수집 자체는 그대로 시도하되(가끔 다른 공지사항이 올라오기도 하므로), 0건이 나왔을 때
# "구조가 깨졌다"는 오해를 주지 않도록 사유만 다르게 표시한다.
G2B_MIGRATION_HINT = "조달청"

# ── 무료 공개 프록시 우회 (대시보드 토글로 켜고 끔) ────────────────────────────
# ProxyScrape 무료 API - 회원가입/키 없이 한국(KR) IP 목록을 텍스트로 제공.
# proxy_format=ipport 이면 'ip:port' 형태 한 줄씩 내려온다.
FREE_PROXY_API_URL = (
    "https://api.proxyscrape.com/v4/free-proxy-list/get"
    "?request=display_proxies&proxy_format=ipport&format=text"
    "&country=kr&protocol=http"
)
PROXY_TEST_URL = "https://www.naver.com"  # 프록시가 실제로 살아있는지 확인할 때 쓰는 사이트
PROXY_TEST_TIMEOUT = 6      # 프록시 하나 테스트할 때 기다리는 시간(초)
PROXY_CANDIDATES_LIMIT = 20  # 앞에서부터 최대 몇 개까지 시도해볼지 (너무 많으면 시작이 느려짐)

REQUEST_TIMEOUT = 20
# (연결타임아웃, 읽기타임아웃) 튜플로 분리. 접속 자체가 막힌 사이트는 서버가 아예 응답하지
# 않으므로 5초면 충분히 판단 가능하다 (20초씩 기다릴 필요 없음 - 차단된 사이트가 많을 때
# 전체 실행 시간을 크게 줄여준다). 반면 접속은 되는데 응답이 느린 사이트를 위해
# 읽기 타임아웃은 기존처럼 넉넉하게 20초 유지.
#
# 단, 프록시를 거칠 때는 클라이언트->프록시->대상 서버로 홉이 하나 늘어나고,
# https:// 사이트는 프록시와 'CONNECT 터널'을 먼저 맺어야 하는데 이 단계도
# '연결 타임아웃' 값을 쓴다. 무료 프록시는 그 자체로 느릴 수 있어서 5초는
# 빠듯하다 - 실제로 "그냥 느려서" 실패한 걸 "차단됐다"고 잘못 판단하는 사례가
# 나왔다. 그래서 프록시 사용 중에는 연결 타임아웃을 더 넉넉하게 준다.
REQUEST_CONNECT_TIMEOUT_DIRECT = 5
REQUEST_CONNECT_TIMEOUT_PROXY = 15


def get_request_timeout_tuple() -> tuple[int, int]:
    """지금 프록시를 쓰고 있는지 여부에 따라 연결 타임아웃을 다르게 준다.
    (모듈 로딩 시점이 아니라 요청 시점에 매번 계산해야 한다 - main.py가 프록시를
    찾아서 환경변수를 설정하는 시점이 config.py가 import된 다음이기 때문이다.)"""
    if os.environ.get("HTTP_PROXY"):
        return (REQUEST_CONNECT_TIMEOUT_PROXY, REQUEST_TIMEOUT)
    return (REQUEST_CONNECT_TIMEOUT_DIRECT, REQUEST_TIMEOUT)


SELENIUM_PAGE_LOAD_TIMEOUT = 45
# 하루에 공고를 많이 올리는 게시판(예: 유성구청 도시계획과, 하루 10건 이상)은
# 1페이지만 보면 최근 공고가 이미 2페이지로 밀려나 있을 수 있다. 그래서 페이지를
# 고정된 개수만큼이 아니라 '이미 알고 있는 공고(중복)나 수집 기간보다 오래된
# 공고를 만날 때까지' 계속 따라간다 (page_has_stop_signal 참고). 이 값은 혹시
# 모를 오작동(끝없이 페이지가 이어지는 경우)을 막는 안전 상한선일 뿐이다.
MAX_PAGINATION_SAFETY_CAP = 8
MAX_WORKERS_LIGHT = 4   # requests 전용 사이트 동시 처리 수
MAX_WORKERS_SELENIUM = 2  # Selenium을 쓰는 사이트는 메모리 문제로 동시 처리 수를 낮게 유지

# 일부 관공서 사이트는 단순 "Mozilla/5.0" 같은 짧은 UA를 봇으로 간주해 차단한다.
# 실제 브라우저와 가까운 완전한 UA 문자열을 공용으로 사용한다.
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

"""
scrapers/base.py
-------------------
모든 게시판형 스크래퍼(generic_requests, generic_selenium, custom/*)가 공유하는
공통 유틸리티: 행 선택, 제목/날짜/링크 추출, 페이지네이션 다음 페이지 찾기,
적응형 페이지네이션 중지 신호 판단, 상세페이지 딥스캔, 키워드 필터(핵심키워드
강제포함 / 제외키워드 / 순수 포함 매칭).
"""

import re
import urllib.parse

import requests
from bs4 import BeautifulSoup

import config

_NOTICE_NUMBER_PATTERN = re.compile(r'^[가-힣0-9\s]{0,20}(공고|고시)\s*제?\s*[\d\-]+\s*호$')

# "2026-08-21", "2026-08-21 ~ 2026-09-18", "2026.08.21" 처럼 날짜(또는 날짜 범위)
# 뿐인 텍스트를 가려내기 위한 패턴. 대전 동구청처럼 '게재기간'(예: "2026-08-21 ~
# 2026-09-18") 컬럼이 있는 게시판에서, 이 날짜 범위 텍스트가 우연히 진짜 제목보다
# 길어지면 _pick_title()이 날짜를 제목으로 잘못 골라버릴 수 있다. 번호 패턴과
# 마찬가지로 후보에서 아예 제외한다.
_DATE_ONLY_PATTERN = re.compile(r'^[\d.\-/년월일\s]+(~|-)?\s*[\d.\-/년월일\s]*$')


def select_rows(soup: BeautifulSoup) -> list:
    """등록된 후보 셀렉터를 순서대로 시도해서 첫 번째로 결과가 있는 것을 쓴다.

    그래도 못 찾으면 '펼쳐진 li형' 특수 구조(예: 낙동강유역환경청 등 mcee.go.kr
    계열)를 시도한다 - 이런 사이트는 번호/제목/등록자/날짜/조회수가 각각 독립된
    형제 <li>로 나란히 펼쳐져 있고, 이를 하나로 묶는 상위 태그(<tr>/<li> 등)가
    없다. <li class="title">(제목 칸에는 이 클래스가 붙어있다는 걸 실제 화면으로
    확인함)를 기준점 삼아, 바로 앞 형제 1개(번호)와 다음 li.title이 나오기 전까지의
    뒤쪽 형제들(등록자/날짜/조회수 등, 사이트마다 개수가 달라도 자동으로 대응됨)을
    모아 하나의 합성 '행'(새 <div> 컨테이너)으로 재구성한다. 원본 트리는 건드리지
    않도록 각 <li>를 복사해서 붙인다."""
    for sel in config.COMMON_ROW_SELECTORS:
        rows = soup.select(sel)
        if rows:
            return rows

    title_lis = soup.select("li.title")
    if not title_lis:
        return []

    import copy
    synthetic_rows = []
    for title_li in title_lis:
        group = []
        prev_sib = title_li.find_previous_sibling("li")
        if prev_sib is not None and prev_sib not in title_lis:
            group.append(prev_sib)
        group.append(title_li)

        sib = title_li.find_next_sibling("li")
        while sib is not None and sib not in title_lis:
            group.append(sib)
            sib = sib.find_next_sibling("li")

        wrapper = BeautifulSoup("<div></div>", "html.parser").div
        for el in group:
            wrapper.append(copy.copy(el))
        synthetic_rows.append(wrapper)

    return synthetic_rows


def _pick_title(row, anchor=None) -> str:
    """행(row) 안의 여러 텍스트 후보 중 '진짜 제목'을 고른다.

    - 공고번호 패턴("OO 공고 제2026-1호")과 순수 날짜(범위) 텍스트는 후보에서
      제외한다 (실제 제목보다 우연히 길어질 수 있어서, 그냥 놔두면 이런 것들이
      "제목"으로 잘못 뽑히는 경우가 실제로 있었다).
    - 남은 후보 중 가장 긴 것을 제목으로 채택한다 (보통 실제 제목이 가장 길다).
    - <a> 태그가 없는 행(예: <tr onclick="...">로 여는 방식)도 지원한다 - anchor가
      None이어도 셀 텍스트만으로 동작한다.
    """
    candidates = []
    if anchor is not None:
        anchor_text = " ".join(anchor.stripped_strings)
        if anchor_text:
            candidates.append(anchor_text)
    for cell in row.find_all(["td", "li", "div", "span"]):
        text = " ".join(cell.stripped_strings)
        if text and text not in candidates:
            candidates.append(text)

    if not candidates:
        return ""

    filtered = [c for c in candidates
                if not _NOTICE_NUMBER_PATTERN.match(c) and not _DATE_ONLY_PATTERN.match(c)]
    pool = filtered or candidates
    return max(pool, key=len)


def resolve_link(base_url: str, href: str) -> str:
    """상대경로 href를 base_url 기준 절대경로로 변환. javascript: 링크 등은 base_url로 대체."""
    if not href or href.strip().lower().startswith("javascript:"):
        return base_url
    return urllib.parse.urljoin(base_url, href)


def extract_row_fields(row, base_url: str, target_date_limit) -> dict | None:
    """
    BeautifulSoup row(tr/li 등)에서 제목/링크/날짜를 추출한다.
    조건(날짜가 target_date_limit 이후)을 만족하지 못하면 None을 반환.

    <a> 태그가 없는 행(예: 대전 동구청처럼 <tr onclick="...">로 자바스크립트
    상세보기를 여는 방식, <a href> 자체가 없는 구조)도 지원한다 - 이런 경우
    제목은 그대로 셀 텍스트에서 뽑고, 상세 링크만 게시판 목록 주소 자체로
    대체한다 (개별 공고로 바로 가는 주소를 알 수 없기 때문).
    """
    anchor = row.find("a")

    title = _pick_title(row, anchor)
    if not title:
        return None

    if anchor is not None:
        href = anchor.get("href", "")
        link = resolve_link(base_url, href) or base_url
    else:
        link = base_url

    row_text = " ".join(row.stripped_strings)
    post_date = find_earliest_date_in_text(row_text)
    if not post_date or post_date < target_date_limit:
        return None

    return {"title": title, "link": link, "date_str": post_date.strftime("%Y.%m.%d")}


def find_earliest_date_in_text(text: str):
    """utils.date_parser의 날짜 스캐너를 그대로 사용 (순환참조 방지를 위해 지연 import)."""
    from utils.date_parser import find_earliest_date
    return find_earliest_date(text)


def find_next_page_url(soup: BeautifulSoup, current_url: str, page_num: int) -> str | None:
    """다음 페이지 링크를 찾는다. pageIndex/page 파라미터 패턴과, 숫자 페이지 링크
    ("2", "3"...) 둘 다 시도한다."""
    next_num = page_num + 1

    # 1) 숫자 텍스트를 가진 <a> 태그 중 next_num과 일치하는 것 찾기
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        if text == str(next_num) and a.get("href"):
            return resolve_link(current_url, a["href"])

    # 2) "다음"/"next"/">" 텍스트를 가진 링크
    for a in soup.find_all("a"):
        text = a.get_text(strip=True).lower()
        if text in ("다음", "next", ">", "»") and a.get("href"):
            return resolve_link(current_url, a["href"])

    return None


def page_has_stop_signal(rows: list, org_name: str, target_date_limit, history_keys: set) -> bool:
    """이 페이지에서 '이미 아는 공고' 또는 '수집기간보다 오래된 공고'를 만났으면
    True를 반환해서, 더 이상 페이지를 넘어갈 필요가 없음을 알린다."""
    for row in rows:
        try:
            fields = extract_row_fields(row, "", target_date_limit)
        except Exception:
            continue
        if not fields:
            # 날짜 조건에 못 미쳐서 None이 나온 경우도 '더 오래된 데이터에 도달함'
            # 신호로 취급할 수 있으나, 여기서는 단순히 넘어간다(page 자체의
            # 종료는 아래 notice_key 체크로 판단).
            continue
        notice_key = f"{org_name}|||{fields['title']}"
        if notice_key in history_keys:
            return True
    return False


def deep_scan_notice(url: str) -> str:
    """상세 페이지 + 첨부파일까지 열어 PLUS/MINUS/지역제한 키워드를 태깅해서 문자열로 반환."""
    headers = config.get_request_headers(url)
    full_text = ""
    try:
        res = requests.get(url, headers=headers, verify=False, timeout=config.get_request_timeout_tuple())
        soup = BeautifulSoup(res.text, "html.parser")
        full_text = soup.get_text(" ", strip=True)
    except Exception:
        return "-"

    tags = []
    plus_hits = [kw for kw in config.PLUS_KWS if kw in full_text]
    minus_hits = [kw for kw in config.MINUS_KWS if kw in full_text]
    if plus_hits:
        tags.append("🔥PLUS(" + ",".join(plus_hits) + ")")
    if minus_hits:
        tags.append("🧊MINUS(" + ",".join(minus_hits) + ")")
    region_hits = [kw for kw in config.REGION_HINT_KWS if kw in full_text]
    if region_hits:
        tags.append("📍지역제한(" + ",".join(region_hits) + ")")

    return " / ".join(tags) if tags else "-"


def discover_additional_boards(base_url: str, domain: str) -> list[str]:
    """base_url 페이지 안에서, 게시판일 가능성이 높은 추가 메뉴/iframe 링크를
    찾아서 후보 URL 목록으로 반환한다 (예: '고시공고', '입찰공고' 텍스트를 가진
    메뉴 링크, 또는 게시판을 담고 있는 iframe의 src)."""
    candidates = []
    try:
        res = requests.get(base_url, headers=config.get_request_headers(base_url),
                            verify=False, timeout=config.get_request_timeout_tuple())
        soup = BeautifulSoup(res.text, "html.parser")
    except Exception:
        return candidates

    for iframe in soup.find_all("iframe"):
        src = iframe.get("src")
        if src:
            resolved = resolve_link(base_url, src)
            if resolved not in candidates and resolved != base_url:
                candidates.append(resolved)

    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        href = a.get("href", "")
        if not href or not text:
            continue
        if any(kw in text for kw in config.BOARD_MENU_KEYWORDS):
            resolved = resolve_link(base_url, href)
            if resolved not in candidates and resolved != base_url:
                candidates.append(resolved)

    return candidates[:3]  # 후보가 너무 많아지지 않도록 상위 몇 개만


def is_force_included(title: str) -> bool:
    """이 핵심 안전점검/진단 키워드가 있으면 EXCLUDE_KEYWORDS에 걸려도 무조건 살려서
    포함시킨다. 예: '주민등록센터 증축 안전점검 수행기관 모집'은 '주민등록'이 있어
    제외 대상처럼 보이지만 '안전점검'이 있으므로 반드시 포함해야 한다."""
    return any(kw in title for kw in config.CORE_SAFETY_KEYWORDS)


def is_excluded_title(title: str) -> bool:
    """제목에 config.EXCLUDE_KEYWORDS 중 하나라도 있으면 True (거의 우리 업무가 아닌 것으로
    확인된 공고 유형). 단, is_force_included()가 True면 이 판정은 무시된다."""
    if is_force_included(title):
        return False
    return any(kw in title for kw in config.EXCLUDE_KEYWORDS)


def matches_positive_keywords(title: str, keywords: list[str]) -> bool:
    """제외 여부는 따지지 않고, 순수하게 '찾는 키워드'에 맞는지만 본다."""
    return (not keywords) or any(kw in title for kw in keywords)


def matches_keywords(title: str, keywords: list[str]) -> bool:
    """'최종 포함 여부'(제외되지 않고 + 키워드도 맞음)만 알고 싶을 때 쓰는 하위 호환 함수.
    제외된 공고를 별도로 모아두고 싶은 호출부는 matches_positive_keywords()와
    is_excluded_title()을 따로 써서 두 경우를 구분해야 한다 (scrapers/generic_*.py 참고)."""
    if is_excluded_title(title):
        return False
    return matches_positive_keywords(title, keywords)

"""
scrapers/base.py
-----------------
모든 스크래퍼(requests 버전, selenium 버전, custom 버전)가 공통으로 쓰는 로직.

- extract_row_fields(): 게시판 한 행(row)에서 제목/링크/날짜를 뽑아낸다.
- deep_scan_notice(): 공고 상세 페이지 + 첨부파일(PDF/HWP)까지 열어서
  PLUS_KWS/MINUS_KWS/지역제한 키워드를 태깅한다 ('특이사항' 컬럼).

주의: 이 파일의 함수들은 '어디서(requests든 selenium이든) 가져온 HTML/텍스트인지'를
신경 쓰지 않는다. 이미 만들어진 BeautifulSoup Tag나 텍스트만 받는다.
"""

import io
import re
import urllib.parse

import requests
from bs4 import BeautifulSoup

import config
from utils.date_parser import find_all_dates_in_row

try:
    import olefile
except ImportError:
    olefile = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


def resolve_link(base_url: str, href: str, onclick: str = "") -> str | None:
    """
    <a href="..."> 또는 onclick="fn_view(...)" 형태에서 실제로 이동 가능한 링크를 만든다.
    href가 '#'이거나 javascript:인데 onclick도 없으면 None을 반환 (호출부에서 base_url로 대체).
    """
    href = (href or "").strip()
    if href and "javascript:" not in href.lower() and href != "#":
        return urllib.parse.urljoin(base_url, href)
    return None


def extract_row_fields(row, base_url: str, target_date_limit) -> dict | None:
    """
    BeautifulSoup row(tr/li 등)에서 제목/링크/날짜를 추출한다.
    조건(날짜가 target_date_limit 이후)을 만족하지 못하면 None을 반환.
    """
    title_tag = row.find("a")
    if not title_tag:
        return None

    title = " ".join(title_tag.stripped_strings) or title_tag.get_text(strip=True)
    if not title:
        return None

    href = title_tag.get("href", "")
    link = resolve_link(base_url, href) or base_url

    dates = find_all_dates_in_row(row.stripped_strings)
    post_date = min(dates) if dates else None
    if not post_date or post_date < target_date_limit:
        return None

    return {
        "title": title,
        "link": link,
        "date_str": post_date.strftime("%Y.%m.%d"),
    }


def matches_keywords(title: str, keywords: list[str]) -> bool:
    return (not keywords) or any(kw in title for kw in keywords)


def _extract_text_from_attachment(file_url: str, headers: dict) -> str:
    try:
        res = requests.get(file_url, headers=headers, verify=False, timeout=config.get_request_timeout_tuple(), stream=True)
        if int(res.headers.get("content-length", 0)) > 5_000_000:
            return ""
        content = res.content
    except Exception:
        return ""

    text = ""
    lower = file_url.lower()
    if lower.endswith(".pdf") and PdfReader is not None:
        try:
            reader = PdfReader(io.BytesIO(content))
            for page in reader.pages[:3]:
                text += " " + (page.extract_text() or "")
        except Exception:
            pass
    elif lower.endswith(".hwp") and olefile is not None:
        try:
            f = olefile.OleFileIO(io.BytesIO(content))
            if f.exists("PrvText"):
                text += " " + f.openstream("PrvText").read().decode("utf-16le", errors="ignore")
        except Exception:
            pass
    return text


def deep_scan_notice(url: str) -> str:
    """상세 페이지 + 첨부파일까지 열어 PLUS/MINUS/지역제한 키워드를 태깅해서 문자열로 반환."""
    headers = config.REQUEST_HEADERS
    full_text = ""
    try:
        res = requests.get(url, headers=headers, verify=False, timeout=config.get_request_timeout_tuple())
        res.encoding = "utf-8"
        soup = BeautifulSoup(res.text, "html.parser")
        full_text += soup.get_text()

        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            if href.endswith(".pdf") or href.endswith(".hwp"):
                file_url = urllib.parse.urljoin(url, a["href"])
                full_text += " " + _extract_text_from_attachment(file_url, headers)
    except Exception:
        return "-"

    found_specials = set()
    for kw in config.PLUS_KWS:
        if kw in full_text:
            found_specials.add(f"🔴{kw}")
    for kw in config.MINUS_KWS:
        if kw in full_text:
            found_specials.add(f"🔵{kw}")

    if any(hint in full_text for hint in config.REGION_HINT_KWS):
        found_regions = {r for r in config.REGION_KWS if r in full_text}
        found_specials.add(f"지역제한({','.join(found_regions)})" if found_regions else "지역제한(상세확인)")

    return "🔥 " + ", ".join(found_specials) if found_specials else "-"


def discover_additional_boards(base_url: str, domain: str) -> list[str]:
    """
    메인/상위 페이지에서 추가 게시판 후보를 찾는다. 두 가지를 찾는다.

    1) <iframe src="..."> — 대전 동구청처럼 '입찰공고' 메뉴 페이지 안에 실제
       게시판이 다른 도메인(eminwon.xxx.go.kr 등)의 iframe으로 통째로 끼워진
       경우가 매우 흔하다. 겉 페이지 HTML만 보면 표가 하나도 안 보이므로,
       iframe의 src를 최우선 후보로 별도 수집한다. (도메인 제한을 걸지 않는다 —
       실제 게시판이 다른 서브도메인에 있는 게 이 패턴의 핵심이기 때문)
    2) '고시·공고·입찰' 등 게시판으로 보이는 <a href> 메뉴 링크 (기존 로직)
    """
    discovered_iframes = set()
    discovered_menu_links = set()
    try:
        res = requests.get(base_url, headers=config.REQUEST_HEADERS, verify=False, timeout=config.get_request_timeout_tuple())
        soup = BeautifulSoup(res.text, "html.parser")

        for iframe in soup.find_all("iframe", src=True):
            src = iframe["src"].strip()
            if src and "javascript:" not in src.lower():
                discovered_iframes.add(urllib.parse.urljoin(base_url, src))

        for a_tag in soup.find_all("a", href=True):
            text = a_tag.get_text(strip=True).replace(" ", "")
            href = a_tag["href"]
            if any(kw in text for kw in config.BOARD_MENU_KEYWORDS):
                if "javascript:" in href.lower() or href == "#":
                    continue
                full_url = urllib.parse.urljoin(base_url, href)
                if domain in full_url:
                    discovered_menu_links.add(full_url)
    except Exception:
        pass

    ranked_menu = sorted(discovered_menu_links,
                          key=lambda u: any(k in u.lower() for k in ("gosi", "noti", "bid")), reverse=True)
    # iframe은 겉 페이지가 사실상 빈 껍데기라는 강한 신호이므로 최우선으로 앞에 배치
    return list(discovered_iframes) + ranked_menu[:5]


def select_rows(soup: BeautifulSoup):
    """공통 셀렉터 목록을 순서대로 시도해 첫 번째로 매치되는 행 목록을 반환."""
    for selector in config.COMMON_ROW_SELECTORS:
        rows = soup.select(selector)
        if rows:
            return rows
    return []


def find_next_page_url(soup: BeautifulSoup, base_url: str, current_page_num: int) -> str | None:
    """1페이지(또는 현재 페이지) 안에서 '다음 번호(current_page_num+1)' 링크를 찾아 반환한다.
    없으면 None (더 이상 갈 페이지가 없다는 뜻)."""
    target_text = str(current_page_num + 1)
    for a_tag in soup.find_all("a", href=True):
        if a_tag.get_text(strip=True) != target_text:
            continue
        href = a_tag["href"].strip()
        if not href or href == "#" or "javascript:" in href.lower():
            continue
        return urllib.parse.urljoin(base_url, href)
    return None


def page_has_stop_signal(rows, org_name: str, target_date_limit, history_keys: set) -> bool:
    """
    현재 페이지 안에 '여기서부터는 더 안 가도 되는 지점'이 있는지 확인한다.
    게시판은 보통 최신순 정렬이므로, 아래 둘 중 하나라도 만나면 그보다 아래(더
    오래된 쪽)는 이미 다 지나간 내용이라고 보고 페이지네이션을 멈춘다.

      1) 등록일이 이번 수집 기간(target_date_limit)보다 오래된 행을 만남
      2) 이미 지난 실행에서 저장된 공고(notice_key가 history_keys에 있음)를 만남

    (제목/링크가 없는 배너·공지성 행은 그냥 건너뛴다.)
    """
    for row in rows:
        title_tag = row.find("a")
        if not title_tag:
            continue
        title = " ".join(title_tag.stripped_strings) or title_tag.get_text(strip=True)
        if not title:
            continue

        dates = find_all_dates_in_row(row.stripped_strings)
        post_date = min(dates) if dates else None
        if post_date and post_date < target_date_limit:
            return True

        if f"{org_name}|||{title}" in history_keys:
            return True
    return False

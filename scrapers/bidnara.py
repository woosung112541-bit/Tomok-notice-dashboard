"""
scrapers/bidnara.py
----------------------
입찰나라(bidnara.com) 전용 - 기존 84곳 게시판 파싱과는 완전히 독립적으로 동작한다.
별도 메뉴("🌐 입찰나라 통합검색")에서만 쓰이고, 결과도 별도 구글시트 탭
(config.SHEET_BIDNARA_AGENCY / SHEET_BIDNARA_BID)에 저장된다. 기존 notices/
manual_check 등 84곳 파이프라인과는 절대 섞이지 않는다.

두 가지를 따로 수집한다:

1) 기관별 공지사항 (bidnara.com/notices/agency-list)
   여러 기관의 자체 공지를 한곳에 모아둔 페이지. 실제 화면 HTML로 확인한 결과,
   한 줄이 <tr class="notice-row" data-href="/notices/agency/detail/...">
   형태 - 일반 <a href> 태그가 아니라 data-href 속성에 상세주소가 들어있다.
   페이지네이션은 ?page=N 방식인데, 실제 테스트로 확인해보니 page=1이 최신
   (0이 아님 - page=0을 넘기면 서버가 이를 범위 밖 값으로 보고 마지막 페이지로
   보내버리는 특이한 동작을 보였다). ?search= 파라미터는 실제로는 서버에서 안
   먹히는 것으로 확인되어(화면 전용 자바스크립트 필터로 추정), 페이지를 하나씩
   넘기며 우리 쪽에서 직접 키워드로 거른다.

2) 입찰 목록 (bidnara.com 메인 화면 '입찰' 탭) - 사실상 나라장터 데이터를 그대로
   재노출하는 미러라서, 이미 공식 G2B API로 갖고 있는 것과 대부분 겹친다. 그래서
   호출하는 쪽(main.py)이 넘겨주는 '이미 갖고 있는 나라장터 공고 제목 집합'에
   없는 것만 결과에 남긴다(완전 신규이거나 우리 G2B 수집 범위 밖에 있던 것).
"""

import time
import urllib.parse
from datetime import datetime

import requests
from bs4 import BeautifulSoup

import config
from scrapers.base import is_excluded_title, matches_positive_keywords
from utils.date_parser import find_earliest_date
from utils.logging_setup import log_failure, log_info

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
}


def fetch_agency_notices(keywords: list[str], target_date_limit: datetime) -> tuple[list[dict], list[dict]]:
    """'기관별 공지사항' 페이지를 최신 페이지(1)부터 넘기며 수집한다.
    반환: (수집된 공고 리스트, 제외된 공고 리스트)"""
    results = []
    excluded_results = []

    for page_num in range(1, config.BIDNARA_MAX_PAGES + 1):
        url = f"{config.BIDNARA_AGENCY_LIST_URL}?page={page_num}&search="
        try:
            res = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
            soup = BeautifulSoup(res.text, "html.parser")
        except Exception as e:
            log_failure("입찰나라(기관별공지)", url, "fetch", e)
            break

        rows = soup.select("tr.notice-row")
        if not rows:
            break

        page_has_old = False
        for row in rows:
            title_span = row.select_one("span.title-cell")
            agency_span = row.select_one("span.agency-cell")
            if not title_span or not agency_span:
                continue
            title = title_span.get_text(strip=True)
            agency = agency_span.get_text(strip=True)

            tds = row.find_all("td")
            date_text = tds[-1].get_text(strip=True) if tds else ""
            post_date = find_earliest_date(date_text)

            if post_date and post_date < target_date_limit:
                page_has_old = True
                continue  # 이 행은 오래됐지만, 같은 페이지에 더 최신 것이 섞여있을 수 있어 계속 확인

            if not matches_positive_keywords(title, keywords):
                continue

            data_href = row.get("data-href", "")
            link = urllib.parse.urljoin(config.BIDNARA_BASE_URL, data_href) if data_href else url

            item = {
                "출처": f"{agency} (입찰나라-기관공지)",
                "등록일": post_date.strftime("%Y.%m.%d") if post_date else date_text,
                "공고제목": title,
                "상세링크": link,
                "특이사항": "-",
            }
            if is_excluded_title(title):
                excluded_results.append(item)
            else:
                results.append(item)

        if page_has_old:
            break  # 이 페이지에서 이미 오래된 공고를 만났으니 더 넘어갈 필요 없음
        time.sleep(0.3)  # 서버 예의상 살짝 대기

    log_info(f"[입찰나라-기관별공지] 수집:{len(results)}건 / 제외:{len(excluded_results)}건")
    return results, excluded_results


def fetch_bid_notices(keywords: list[str], target_date_limit: datetime,
                       existing_titles: set) -> tuple[list[dict], list[dict]]:
    """메인 화면의 '입찰' 목록(나라장터 미러)을 가져와서, 이미 저장된 나라장터
    공고 제목(existing_titles)에 없는 것만 반환한다. 반환: (기존에 없던 신규만, 제외된 것)"""
    results = []
    excluded_results = []

    try:
        res = requests.get(config.BIDNARA_BASE_URL, headers=REQUEST_HEADERS, timeout=20)
        soup = BeautifulSoup(res.text, "html.parser")
    except Exception as e:
        log_failure("입찰나라(입찰목록)", config.BIDNARA_BASE_URL, "fetch", e)
        return results, excluded_results

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/bids/v/bid/" not in href:
            continue
        title = a.get_text(strip=True)
        if not title or title in seen:
            continue
        seen.add(title)

        if title in existing_titles:
            continue  # 이미 우리 나라장터 API로 갖고 있는 것 - 중복이니 건너뜀

        row = a.find_parent("tr") or a.find_parent("div")
        row_text = row.get_text(" ", strip=True) if row else title
        post_date = find_earliest_date(row_text)
        if post_date and post_date < target_date_limit:
            continue

        if not matches_positive_keywords(title, keywords):
            continue

        link = urllib.parse.urljoin(config.BIDNARA_BASE_URL, href)
        item = {
            "출처": "입찰나라(나라장터 미러 - 신규만)",
            "등록일": post_date.strftime("%Y.%m.%d") if post_date else "-",
            "공고제목": title,
            "상세링크": link,
            "특이사항": "-",
        }
        if is_excluded_title(title):
            excluded_results.append(item)
        else:
            results.append(item)

    log_info(f"[입찰나라-입찰목록] 신규(기존 미보유):{len(results)}건 / 제외:{len(excluded_results)}건")
    return results, excluded_results

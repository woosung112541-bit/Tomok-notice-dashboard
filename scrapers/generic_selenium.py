"""
scrapers/generic_selenium.py
-------------------------------
3순위: requests로 게시판 행을 못 찾은 경우(JS 렌더링이 필요한 사이트로 추정)
Selenium으로 승격해서 다시 시도한다.
"""

import os

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

import config
from scrapers.base import (extract_row_fields, matches_positive_keywords, is_excluded_title, deep_scan_notice,
                            select_rows, find_next_page_url, page_has_stop_signal)
from utils.logging_setup import log_failure, log_info


def get_driver():
    """헤드리스 Chrome WebDriver를 만든다. 무료 프록시 토글이 켜져 있으면
    (환경변수 HTTP_PROXY/HTTPS_PROXY) 그 프록시를 통해 나가도록 설정한다."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"user-agent={config.REQUEST_HEADERS['User-Agent']}")

    proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    if proxy:
        options.add_argument(f"--proxy-server={proxy}")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(config.SELENIUM_PAGE_LOAD_TIMEOUT)
    return driver


def _navigate_with_referer(driver, url: str) -> None:
    """일부 사이트(예: 세종도시교통공사)는 주소창에 직접 쳐서 들어가면 '처리 중
    오류' 안내 페이지로 돌려보내고, 자기 사이트 안에서 메뉴를 눌러 넘어온
    경우에만 실제 내용을 보여주는 리퍼러 체크를 한다. 일반 driver.get()은
    리퍼러가 비어있어서 이런 체크에 걸린다 - Chrome DevTools Protocol로 그
    사이트 자신의 루트 주소를 리퍼러로 채워서 이동하면 대부분 통과한다."""
    try:
        referer = config.get_request_headers(url)["Referer"]
        driver.execute_cdp_cmd("Page.navigate", {"url": url, "referrer": referer})
    except Exception:
        driver.get(url)


def scrape_board(url: str, org_name: str, target_date_limit, keywords: list[str],
                  history_keys: set | None = None) -> tuple[list[dict], list[dict], int, bool]:
    """
    반환: (수집된 공고 리스트, 제외된 공고 리스트, 발견된 행 개수, 네트워크_접속_실패_여부)
    generic_requests.scrape_board()와 동일한 규약(페이지네이션 중지 조건, 제외 목록 분리)을 따른다.
    """
    history_keys = history_keys or set()
    results = []
    excluded_results = []
    driver = None
    all_rows = []
    current_url = url
    visited = {url}

    try:
        driver = get_driver()
    except Exception as e:
        log_failure(org_name, url, "selenium_load", e)
        return results, excluded_results, 0, False

    page_num = 0
    for page_num in range(1, config.MAX_PAGINATION_SAFETY_CAP + 1):
        try:
            _navigate_with_referer(driver, current_url)
            driver.implicitly_wait(2)
            soup = BeautifulSoup(driver.page_source, "html.parser")
            rows = select_rows(soup)
        except TimeoutException as e:
            if page_num == 1:
                log_failure(org_name, url, "selenium_load", f"[페이지 로딩 타임아웃 - 네트워크/차단 가능성] {e}")
                driver.quit()
                return results, excluded_results, 0, True
            break
        except Exception as e:
            if page_num == 1:
                log_failure(org_name, url, "selenium_load", e)
                driver.quit()
                return results, excluded_results, 0, False
            break

        all_rows.extend(rows)

        if not rows or page_has_stop_signal(rows, org_name, target_date_limit, history_keys):
            break  # 이미 아는 지점(또는 수집기간 밖)에 도달 -> 더 갈 필요 없음

        next_url = find_next_page_url(soup, current_url, page_num)
        if not next_url or next_url in visited:
            break
        visited.add(next_url)
        current_url = next_url

    if page_num > 1:
        log_info(f"[{org_name}] 페이지네이션으로 {page_num}페이지까지 확인 후 중단")

    for row in all_rows:
        try:
            fields = extract_row_fields(row, url, target_date_limit)
        except Exception as e:
            log_failure(org_name, url, "parse_row", e)
            continue
        if not fields:
            continue
        title = fields["title"]
        if not matches_positive_keywords(title, keywords):
            continue
        special = deep_scan_notice(fields["link"])
        item = {
            "출처": org_name, "등록일": fields["date_str"],
            "공고제목": title, "상세링크": fields["link"],
            "특이사항": special,
        }
        if is_excluded_title(title):
            excluded_results.append(item)
        else:
            results.append(item)

    driver.quit()
    return results, excluded_results, len(all_rows), False

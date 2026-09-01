"""
scrapers/generic_selenium.py
------------------------------
3순위: requests로는 안 잡히는(=자바스크립트 렌더링이 필요한) 일반 게시판.
로그인이나 다단계 클릭처럼 사이트 고유의 절차가 필요한 곳은 여기서 처리하지 않고
scrapers/custom/*.py로 보낸다 (site_registry.py가 handler_type='custom'으로 분류).

get_driver()는 custom 핸들러에서도 재사용한다 (한 곳에서만 Chrome 옵션을 관리하기 위함).
"""

import os

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

import config
from scrapers.base import (extract_row_fields, matches_positive_keywords, is_excluded_title, deep_scan_notice,
                            select_rows, find_next_page_url, page_has_stop_signal)
from utils.logging_setup import log_failure, log_info


def get_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # main.py가 프록시 우회 토글이 켜졌을 때 환경변수로 넘겨준 값. Selenium/Chrome은
    # HTTP_PROXY 환경변수를 자동으로 읽지 않으므로 명시적으로 --proxy-server 옵션을 준다.
    selenium_proxy = os.environ.get("SCRAPER_SELENIUM_PROXY")
    if selenium_proxy:
        options.add_argument(f"--proxy-server=http://{selenium_proxy}")

    try:
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=options)
    except Exception:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

    driver.set_page_load_timeout(config.SELENIUM_PAGE_LOAD_TIMEOUT)
    try:
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {
            "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        })
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    except Exception:
        pass
    return driver


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
            driver.get(current_url)
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

"""
scrapers/generic_selenium.py
------------------------------
3순위: requests로는 안 잡히는(=자바스크립트 렌더링이 필요한) 일반 게시판.
로그인이나 다단계 클릭처럼 사이트 고유의 절차가 필요한 곳은 여기서 처리하지 않고
scrapers/custom/*.py로 보낸다 (site_registry.py가 handler_type='custom'으로 분류).

get_driver()는 custom 핸들러에서도 재사용한다 (한 곳에서만 Chrome 옵션을 관리하기 위함).
"""

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

import config
from scrapers.base import extract_row_fields, matches_keywords, deep_scan_notice, select_rows
from utils.logging_setup import log_failure


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


def scrape_board(url: str, org_name: str, target_date_limit, keywords: list[str]) -> tuple[list[dict], int]:
    """
    반환: (수집된 공고 리스트, 발견된 행 개수)
    generic_requests.scrape_board()와 동일하게 행 개수를 함께 반환한다.
    (예전 버전은 이 값을 반환하지 않아서, engine.py가 'selenium으로 게시판은
    정상적으로 찾았지만 이번엔 조건에 맞는 공고가 없었을 뿐인 경우'와
    '애초에 게시판 구조 자체를 못 찾은 경우'를 구분하지 못하고 전자까지
    "수동 확인 필요"로 잘못 분류하는 문제가 있었다.)
    """
    results = []
    driver = None
    try:
        driver = get_driver()
        driver.get(url)
        driver.implicitly_wait(2)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        rows = select_rows(soup)
    except Exception as e:
        log_failure(org_name, url, "selenium_load", e)
        if driver:
            driver.quit()
        return results, 0

    for row in rows:
        try:
            fields = extract_row_fields(row, url, target_date_limit)
        except Exception as e:
            log_failure(org_name, url, "parse_row", e)
            continue
        if not fields:
            continue
        if not matches_keywords(fields["title"], keywords):
            continue
        special = deep_scan_notice(fields["link"])
        results.append({
            "출처": org_name, "등록일": fields["date_str"],
            "공고제목": fields["title"], "상세링크": fields["link"],
            "특이사항": special,
        })

    driver.quit()
    return results, len(rows)

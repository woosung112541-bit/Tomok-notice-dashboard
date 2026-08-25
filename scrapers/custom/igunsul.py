"""
scrapers/custom/igunsul.py
-----------------------------
아이건설넷(igunsul.net) 전용 핸들러 - 로그인 후 게시판 조회.
로그인 계정은 절대 코드에 적지 않고 config.IGUNSUL_ID / config.IGUNSUL_PW
(Streamlit secrets / GitHub Actions secrets)에서 읽어온다.
"""

import time

from bs4 import BeautifulSoup

import config
from scrapers.base import extract_row_fields, matches_keywords, deep_scan_notice, select_rows
from scrapers.generic_selenium import get_driver
from utils.logging_setup import log_failure, log_info

LOGIN_URL = "https://www.igunsul.net/login"


def scrape(url: str, org_name: str, target_date_limit, keywords: list[str]) -> list[dict]:
    results = []

    if not config.IGUNSUL_ID or not config.IGUNSUL_PW:
        log_failure(org_name, url, "custom_flow", "IGUNSUL_ID/IGUNSUL_PW 시크릿이 설정되지 않음")
        return results

    driver = None
    try:
        driver = get_driver()
        driver.get(LOGIN_URL)
        time.sleep(2)
        try:
            driver.execute_script(
                "document.querySelector('input[type=\"text\"], input[name*=\"id\"]').value=arguments[0];",
                config.IGUNSUL_ID,
            )
            driver.execute_script(
                "document.querySelector('input[type=\"password\"], input[name*=\"pw\"]').value=arguments[0];",
                config.IGUNSUL_PW,
            )
            driver.execute_script("document.querySelector('form').submit();")
            time.sleep(2)
            log_info("[아이건설넷] 로그인 시도 완료")
        except Exception as e:
            log_failure(org_name, LOGIN_URL, "login", e)

        driver.get(url)
        time.sleep(3)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(1)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        rows = select_rows(soup)
        if not rows:
            log_failure(org_name, url, "parse_row", "게시판 행 자체를 찾지 못함 (로그인 실패 또는 셀렉터 불일치 가능성)")

        for row in rows:
            fields = extract_row_fields(row, url, target_date_limit)
            if not fields or not matches_keywords(fields["title"], keywords):
                continue
            special = deep_scan_notice(fields["link"])
            results.append({
                "출처": org_name, "등록일": fields["date_str"],
                "공고제목": fields["title"], "상세링크": fields["link"],
                "특이사항": special,
            })

    except Exception as e:
        log_failure(org_name, url, "custom_flow", e)
    finally:
        if driver:
            driver.quit()

    return results

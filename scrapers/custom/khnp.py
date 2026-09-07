"""
scrapers/custom/khnp.py
-------------------------
한국수력원자력 K-Pro 전자상거래시스템(ebiz.khnp.co.kr) 전용 핸들러.

말씀 주신 흐름을 그대로 코드화했다:
    1) 최초 진입 시 뜨는 팝업/공지 레이어 닫기
    2) 상단 메뉴 '입찰공고' -> '입찰공고조회' 클릭
    3) 목록이 그려질 때까지 대기
    4) 목록에서 조건에 맞는 공고를 눌러 상세로 이동

⚠️ 이 사이트는 AnySign/TouchEn 계열 보안 프로그램을 쓰는 것으로 확인되어,
현재는 자동화가 사실상 불가능한 것으로 판단하고 "수동 확인" 대상으로 받아들이기로
했다 (config.KNOWN_HARD_SITES 참고). 이 파일은 실패하더라도 항상 log_failure로
사유를 남기도록 되어 있어서, 어느 단계에서 막혔는지는 run_log에서 계속 확인할 수 있다.
"""

import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from scrapers.base import matches_positive_keywords, is_excluded_title, deep_scan_notice
from scrapers.generic_selenium import get_driver
from utils.date_parser import find_earliest_date
from utils.logging_setup import log_failure, log_info

ENTRY_URL = "https://ebiz.khnp.co.kr/login.do"

# 팝업/레이어 닫기 버튼으로 흔히 쓰이는 셀렉터 후보들 (여러 개 시도)
POPUP_CLOSE_SELECTORS = [
    "button.close", "a.close", ".layerClose", ".btn_close",
    ".popup_close", ".layer_close", "[class*='close']",
]

MENU_LINK_TEXT = "입찰공고"
SUBMENU_LINK_TEXT = "입찰공고조회"


def _try_close_popups(driver) -> None:
    for sel in POPUP_CLOSE_SELECTORS:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in elements:
                if el.is_displayed():
                    el.click()
                    time.sleep(0.3)
        except Exception:
            continue


def _click_by_text(driver, wait, text: str) -> bool:
    """지정한 텍스트를 가진 클릭 가능한 요소를 찾아 클릭한다. 실패하면 False."""
    try:
        el = wait.until(EC.element_to_be_clickable((By.XPATH, f"//*[contains(text(), '{text}')]")))
        try:
            el.click()
        except Exception:
            driver.execute_script("arguments[0].click();", el)
        return True
    except TimeoutException:
        return False


def scrape(url: str, org_name: str, target_date_limit, keywords: list[str]) -> tuple[list[dict], list[dict]]:
    results = []
    excluded_results = []
    driver = None
    try:
        driver = get_driver()
        driver.get(url or ENTRY_URL)
        time.sleep(2)
        wait = WebDriverWait(driver, 15)

        _try_close_popups(driver)

        if not _click_by_text(driver, wait, MENU_LINK_TEXT):
            return results, excluded_results
        time.sleep(0.5)
        if not _click_by_text(driver, wait, SUBMENU_LINK_TEXT):
            return results, excluded_results

        # 목록 grid가 그려질 때까지 대기
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr")))
        except TimeoutException as e:
            log_failure(org_name, driver.current_url, "wait_grid", e)
            return results, excluded_results

        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
        log_info(f"[KHNP] 목록 {len(rows)}행 발견")

        for i in range(len(rows)):
            try:
                current_rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
                if i >= len(current_rows):
                    break
                row = current_rows[i]
                row_text = row.text
                post_date = find_earliest_date(row_text)
                if not post_date or post_date < target_date_limit:
                    continue

                # 공고명은 보통 마지막 열에 텍스트로만 존재 (하이퍼링크가 아닐 수 있음) -> 행 전체를 클릭
                title = row_text.strip().splitlines()[-1] if row_text.strip() else ""
                if not matches_positive_keywords(title, keywords):
                    continue

                row.click()
                time.sleep(2)
                link = driver.current_url
                special = deep_scan_notice(link) if link != url else "-"
                item = {
                    "출처": org_name,
                    "등록일": post_date.strftime("%Y.%m.%d"),
                    "공고제목": title or "(제목 확인 필요)",
                    "상세링크": link,
                    "특이사항": special,
                }
                if is_excluded_title(title):
                    excluded_results.append(item)
                else:
                    results.append(item)
                driver.back()
                time.sleep(1.5)
            except Exception as e:
                log_failure(org_name, url, "custom_flow_row", e)
                continue

    except Exception as e:
        log_failure(org_name, url, "custom_flow", e)
    finally:
        if driver:
            driver.quit()

    return results, excluded_results

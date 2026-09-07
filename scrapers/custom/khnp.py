"""
scrapers/custom/khnp.py
-------------------------
한국수력원자력 K-Pro 전자상거래시스템(ebiz.khnp.co.kr) 전용 핸들러.

말씀 주신 흐름을 그대로 코드화했다:
    1) 최초 진입 시 뜨는 팝업/공지 레이어 닫기
    2) 상단 메뉴 '입찰공고' -> '입찰공고조회' 클릭
    3) 목록이 그려질 때까지 대기
    4) 목록에서 조건에 맞는 공고를 눌러 상세로 이동

⚠️ 중요: 이 환경(Claude 작업 샌드박스)은 보안 정책상 KHNP 같은 일반 외부 사이트에
네트워크로 접속할 수 없어서, 실제 DOM 구조(정확한 버튼 class/id)를 직접 확인하지 못한
채로 작성했다. 아래 셀렉터는 화면 캡처와 일반적인 관공서 사이트 패턴을 근거로 한
'최선의 추정'이며, 실제로 돌려보면 한두 군데 셀렉터를 조정해야 할 가능성이 높다.

대신 각 단계마다 log_failure/log_info를 남기도록 만들어서, 실패하면 '어느 단계에서
막혔는지'가 run_log 구글시트에 정확히 남는다. 기존 코드처럼 通째로 실패해서 원인을
알 수 없는 상황을 막는 것이 이 파일의 핵심 목표다. 실제 실행 로그를 보고 셀렉터를
한 번 더 조정해주면 완성도가 올라간다.
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
    "button[aria-label='닫기']", "a[title='닫기']",
]

MENU_LINK_TEXT = "입찰공고"
SUBMENU_LINK_TEXT = "입찰공고조회"


def _try_close_popups(driver) -> None:
    """뜰 수 있는 팝업/레이어를 최대한 닫아본다. 하나도 없어도 정상 흐름이므로 예외를 삼키지 않고 log_info만 남긴다."""
    closed_any = False
    for selector in POPUP_CLOSE_SELECTORS:
        try:
            elems = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elems:
                if el.is_displayed():
                    el.click()
                    closed_any = True
                    time.sleep(0.3)
        except Exception:
            continue

    # alert()/confirm() 형태의 브라우저 네이티브 팝업도 확인
    try:
        alert = driver.switch_to.alert
        alert.accept()
        closed_any = True
    except Exception:
        pass

    if closed_any:
        log_info("[KHNP] 팝업/레이어 닫기 완료")


def _click_by_text(driver, wait: WebDriverWait, text: str) -> bool:
    try:
        xpath = f"//*[self::a or self::button or self::span][contains(normalize-space(text()), '{text}')]"
        el = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        ActionChains(driver).move_to_element(el).pause(0.3).click(el).perform()
        return True
    except (TimeoutException, NoSuchElementException) as e:
        log_failure("한국수력원자력(K-Pro)", driver.current_url, "click_menu", f"'{text}' 클릭 실패: {e}")
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

"""
scrapers/custom/igunsul.py
-----------------------------
아이건설넷(igunsul.net) 전용 핸들러 - 로그인 후 게시판 조회.
로그인 계정은 절대 코드에 적지 않고 config.IGUNSUL_ID / config.IGUNSUL_PW
(Streamlit secrets / GitHub Actions secrets)에서 읽어온다.

실제 화면 확인 결과: 첫 화면에 "아이디 로그인" / "공동인증서 로그인" 두 탭이 있고,
"아이디 로그인" 탭이 기본으로 열려있다. 예전 코드는 "페이지에서 처음 보이는
텍스트 입력칸"을 무작정 골랐는데, 화면 맨 위에 "공고명을 검색하세요"라는
검색창도 똑같이 text 타입 입력칸이라서, 로그인 아이디 칸이 아니라 그 검색창에
아이디를 입력하고 있었을 가능성이 높다 (그래서 로그인이 계속 조용히 실패했음).

이제 placeholder 텍스트("아이디 입력", "비밀번호 입력")로 정확한 칸을 콕 집어서
채우고, "로그인" 버튼을 텍스트로 정확히 찾아서 클릭한다 (엉뚱한 첫 번째 <form>을
제출하지 않는다).
"""

import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup

import config
from scrapers.base import extract_row_fields, matches_positive_keywords, is_excluded_title, deep_scan_notice, select_rows
from scrapers.generic_selenium import get_driver
from utils.logging_setup import log_failure, log_info

LOGIN_URL = "https://www.igunsul.net/"

# 실제 화면에서 확인한 입력칸의 placeholder 텍스트. 여러 후보를 순서대로 시도한다
# (사이트가 문구를 조금 바꿔도 웬만하면 걸리도록).
ID_FIELD_SELECTORS = ["input[placeholder*='아이디 입력']", "input[placeholder*='아이디']"]
PW_FIELD_SELECTORS = ["input[placeholder*='비밀번호 입력']", "input[type='password']"]


def _find_first(driver, selectors):
    for sel in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el:
                return el
        except NoSuchElementException:
            continue
    return None


def scrape(url: str, org_name: str, target_date_limit, keywords: list[str]) -> tuple[list[dict], list[dict]]:
    results = []
    excluded_results = []

    if not config.IGUNSUL_ID or not config.IGUNSUL_PW:
        log_failure(org_name, url, "custom_flow", "IGUNSUL_ID/IGUNSUL_PW 시크릿이 설정되지 않음")
        return results, excluded_results

    driver = None
    try:
        driver = get_driver()
        driver.get(LOGIN_URL)
        wait = WebDriverWait(driver, 10)

        id_field = _find_first(driver, ID_FIELD_SELECTORS)
        pw_field = _find_first(driver, PW_FIELD_SELECTORS)

        if not id_field or not pw_field:
            log_failure(org_name, LOGIN_URL, "login",
                        f"로그인 입력칸을 못 찾음 (id_field={bool(id_field)}, pw_field={bool(pw_field)})")
        else:
            id_field.clear()
            id_field.send_keys(config.IGUNSUL_ID)
            pw_field.clear()
            pw_field.send_keys(config.IGUNSUL_PW)

            url_before_login = driver.current_url

            # 1순위: 비밀번호 칸에서 Enter를 누른다 - 대부분의 로그인 폼은 이렇게
            # 하면 실제 "로그인" 버튼을 누른 것과 똑같이 동작한다. 어떤 버튼이
            # 진짜 제출 버튼인지 헷갈릴 일이 없어서 이 방식이 가장 안전하다.
            pw_field.send_keys(Keys.RETURN)
            time.sleep(2)

            # 그래도 로그인 후 화면(주소)이 안 바뀌었으면, 페이지 안의 "로그인"
            # 버튼/링크를 찾아 클릭해본다 (Enter만으로 안 되는 폼도 있어서 보험 차원).
            if driver.current_url == url_before_login:
                login_btn = None
                for tag in ["button", "a", "input"]:
                    try:
                        candidates = driver.find_elements(By.XPATH, f"//{tag}[contains(text(), '로그인')]")
                        if candidates:
                            login_btn = candidates[0]
                            break
                    except Exception:
                        continue
                if login_btn:
                    try:
                        login_btn.click()
                    except Exception:
                        # 화면에 뜬 팝업/배너의 반투명 오버레이(blackPanel 등)가 버튼을
                        # 가리고 있어서 일반 클릭이 막히는 경우가 실제로 있었다
                        # (ElementClickInterceptedException). 자바스크립트로 직접
                        # 클릭 이벤트를 발생시키면 화면상 겹침 여부와 무관하게 눌린다.
                        driver.execute_script("arguments[0].click();", login_btn)
                    time.sleep(2)

            if driver.current_url == url_before_login:
                # 화면에 뭔가 에러 문구(비밀번호 틀림, 자동입력방지문자 등)가 떴는지
                # 함께 잡아본다 - "0건"으로만 남는 것보다 훨씬 정확한 원인 파악이 된다.
                page_text = ""
                try:
                    page_text = driver.find_element(By.TAG_NAME, "body").text
                except Exception:
                    pass
                hint_words = ["일치하지", "틀렸", "잘못", "캡차", "자동입력방지",
                              "보안문자", "로봇", "차단", "확인해", "가입"]
                found_hints = [w for w in hint_words if w in page_text]
                snippet = page_text[:300].replace("\n", " ")
                log_failure(org_name, LOGIN_URL, "login",
                            f"로그인 시도 후에도 주소가 안 바뀜(여전히 {driver.current_url}) - "
                            f"아이디/비밀번호가 틀렸거나, 로그인 버튼을 못 찾았을 가능성 "
                            f"[화면에서 발견된 관련 단어: {found_hints or '없음'}] "
                            f"[화면 상단 텍스트: {snippet}]")
            log_info(f"[아이건설넷] 로그인 시도 완료 (현재 주소: {driver.current_url})")

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

    except Exception as e:
        log_failure(org_name, url, "custom_flow", e)
    finally:
        if driver:
            driver.quit()

    return results, excluded_results

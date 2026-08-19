"""
main_max.py — 공고 탐색 딥 스캔 엔진 (안정성/정확도 강화판 + 타겟기관 필터링)
"""
import os
import sys
import re
import json
import time
import logging
import warnings
import urllib.parse
import urllib3
import concurrent.futures
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup
import pandas as pd
import gspread

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

try:
    import streamlit as st
except ImportError:
    st = None

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", module='bs4')

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gonggo_scanner")
RUN_LOG = []

def log_error(context, err):
    msg = f"[{context}] {type(err).__name__}: {err}"
    logger.warning(msg)
    RUN_LOG.append(msg)

def _get_secret(key, default=""):
    val = os.environ.get(key)
    if val:
        return val
    if st is not None:
        try:
            return st.secrets.get(key, default)
        except Exception:
            pass
    return default

IGUNSUL_ID = _get_secret("IGUNSUL_ID")
IGUNSUL_PW = _get_secret("IGUNSUL_PW")
G2B_API_KEY = _get_secret("G2B_API_KEY")

KST = timezone(timedelta(hours=9))

def get_now_kst():
    return datetime.now(KST).replace(tzinfo=None)

DAYS_AGO_DEFAULT = 15
# 🚀 키워드 3개 축소
TARGET_KEYWORDS_DEFAULT = ["모집", "안전", "공고"]
DAYS_AGO = DAYS_AGO_DEFAULT
TARGET_KEYWORDS = TARGET_KEYWORDS_DEFAULT
target_date_limit = get_now_kst() - timedelta(days=DAYS_AGO_DEFAULT)
current_time = get_now_kst().strftime("%Y-%m-%d %H:%M:%S")

BOARD_MENU_KEYWORDS = ["고시공고", "고시", "공고", "입찰", "발주", "새소식", "공지", "알림", "소식", "게시판"]
ORG_NAME_COL_INDEX = 2

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_EXCEL = os.path.join(BASE_DIR, '등록명부 정리시트.xlsx')

PLUS_KWS = ["종합", "토목", "안전점검", "수행기관", "대전"]
MINUS_KWS = ["건축분야", "신축", "번지", "증축", "수의", "건립"]
REGION_KWS = ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']
REGION_HINT_KWS = ['지역제한', '소재지', '영업소', '한정', '관내', '소재한', '위치한']

DEADLINE_LABELS = ["마감", "접수마감", "제출마감", "입찰마감", "개찰"]
POST_LABELS = ["등록일", "게시일", "작성일", "공고일"]

EXTRA_SITES = [
    {'url': 'http://www.assi.or.kr/sub/board/gongji.asp?boardname=gongji', 'org_name': '한국시설안전협회'},
    {'url': 'https://www.pps.go.kr/kor/bbs/list.do?key=00641', 'org_name': '조달청 통합명부'},
    {'url': 'https://www.igunsul.net/', 'org_name': '아이건설넷'}
]

URL_OVERRIDES = {
    "대전교통공사": "https://www.djtc.kr/kor/board.do?menuIdx=361",
    "서산시": "https://www.seosan.go.kr/www/contents.do?key=1258",
    "대전광역시 서구": "https://www.seogu.go.kr/prog/saeolGosi/GOSI/kor/sub04_02_01/list.do",
    "논산시": "https://www.nonsan.go.kr/kor/html/sub03/03010201.html",
    "용인특례시": "https://www.yongin.go.kr/home/yiNw/yiNwStable/yiNwStable02/yiNwStable02_01.jsp",
    "용인시": "https://www.yongin.go.kr/home/yiNw/yiNwStable/yiNwStable02/yiNwStable02_01.jsp"
}

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
}

def get_gspread_client():
    if st is not None:
        try:
            if "gcp_service_account" in st.secrets:
                creds_dict = dict(st.secrets["gcp_service_account"])
                return gspread.service_account_from_dict(creds_dict)
        except Exception as e:
            log_error("gspread-secrets", e)

    env_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if env_json:
        try:
            return gspread.service_account_from_dict(json.loads(env_json))
        except Exception as e:
            log_error("gspread-envjson", e)

    key_path = os.path.join(BASE_DIR, "google_key.json")
    if os.path.exists(key_path):
        return gspread.service_account(filename=key_path)

    raise RuntimeError(
        "구글 서비스 계정 인증 정보를 찾을 수 없습니다."
    )

def safe_get(url, timeout=(10, 20), retries=2, headers=None):
    last_err = None
    for attempt in range(retries + 1):
        try:
            res = requests.get(url, headers=headers or DEFAULT_HEADERS, verify=False, timeout=timeout)
            if not res.encoding or res.encoding.lower() == "iso-8859-1":
                res.encoding = res.apparent_encoding or "utf-8"
            return res
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    log_error(f"safe_get:{url}", last_err)
    return None

def get_domain(url):
    try:
        return urllib.parse.urlparse(str(url)).netloc
    except Exception:
        return ""

def discover_additional_boards(base_url, domain):
    discovered_urls = set()
    res = safe_get(base_url, timeout=(10, 20))
    if res is None:
        return []
    try:
        soup = BeautifulSoup(res.text, 'html.parser')
        for a_tag in soup.find_all('a', href=True):
            text = a_tag.get_text(strip=True).replace(" ", "")
            href = a_tag['href']
            if any(keyword in text for keyword in BOARD_MENU_KEYWORDS):
                if "javascript:" in href.lower() or href == "#":
                    continue
                full_url = urllib.parse.urljoin(base_url, href)
                if domain in full_url:
                    discovered_urls.add(full_url)
    except Exception as e:
        log_error(f"discover_additional_boards:{base_url}", e)
    sorted_urls = sorted(
        list(discovered_urls),
        key=lambda x: ('gosi' in x.lower() or 'noti' in x.lower() or 'bid' in x.lower()),
        reverse=True
    )
    return sorted_urls[:3]

def deep_scan_notice(url):
    found_specials = set()
    found_regions = set()
    res = safe_get(url, timeout=15, retries=1)
    if res is None:
        return "-"
    try:
        soup = BeautifulSoup(res.text, 'html.parser')
        full_text = soup.get_text()

        for kw in PLUS_KWS:
            if kw in full_text:
                found_specials.add(f"🔴{kw}")
        for kw in MINUS_KWS:
            if kw in full_text:
                found_specials.add(f"🔵{kw}")

        if any(hint in full_text for hint in REGION_HINT_KWS):
            for r in REGION_KWS:
                if r in full_text:
                    found_regions.add(r)
            if found_regions:
                found_specials.add(f"지역제한({','.join(list(found_regions))})")
            else:
                found_specials.add("지역제한(상세확인)")
    except Exception as e:
        log_error(f"deep_scan_notice:{url}", e)

    return "🔥 " + ", ".join(list(found_specials)) if found_specials else "-"

def bulldozer_scan_html(html_source, base_url, org_name):
    _now = get_now_kst()
    soup = BeautifulSoup(html_source, 'html.parser')
    results = []
    processed_rows = set()

    for a_tag in soup.find_all('a', href=True):
        try:
            title = " ".join(a_tag.stripped_strings)
            if not title:
                title = a_tag.get_text(strip=True)
            if len(title) < 5 or title.isdigit() or title in ["이전", "다음", "목록", "처음", "마지막", "더보기"]:
                continue

            row = a_tag.find_parent(['tr', 'li'])
            if not row:
                row = a_tag.find_parent('div', class_=re.compile(r'row|item|list|board', re.I))
            if not row:
                row = a_tag.parent

            row_id = id(row)
            if row_id in processed_rows:
                continue
            processed_rows.add(row_id)

            row_text = row.get_text(separator=' ', strip=True)
            candidates = [] 

            matches = list(re.finditer(r'(20\d{2}|\d{2})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})', row_text))
            for match in matches:
                y, m, d = match.groups()
                if len(y) == 2:
                    y = "20" + y
                try:
                    pd_date = datetime(int(y), int(m), int(d))
                except ValueError:
                    continue
                prefix = row_text[max(0, match.start() - 8):match.start()]
                candidates.append((
                    pd_date,
                    any(k in prefix for k in DEADLINE_LABELS),
                    any(k in prefix for k in POST_LABELS)
                ))

            if not candidates:
                matches_md = list(re.finditer(r'(?<!\d)(\d{1,2})[-./월\s]+(\d{1,2})(?![.\d])', row_text))
                for match in matches_md:
                    m, d = match.groups()
                    try:
                        pd_date = datetime(_now.year, int(m), int(d))
                        if pd_date > _now + timedelta(days=30):
                            pd_date = datetime(_now.year - 1, int(m), int(d))
                    except ValueError:
                        continue
                    prefix = row_text[max(0, match.start() - 8):match.start()]
                    candidates.append((
                        pd_date,
                        any(k in prefix for k in DEADLINE_LABELS),
                        any(k in prefix for k in POST_LABELS)
                    ))

            valid = [c for c in candidates if c[0] <= _now + timedelta(days=1)]
            post_date = None
            
            labeled = [c[0] for c in valid if c[2] and not c[1]]
            if labeled:
                post_date = min(labeled)
            else:
                non_deadline = [c[0] for c in valid if not c[1]]
                if non_deadline:
                    post_date = min(non_deadline)
                elif valid:
                    post_date = min(c[0] for c in valid)

            date_str = post_date.strftime("%Y.%m.%d") if post_date else ""

            if post_date and post_date >= target_date_limit:
                if not TARGET_KEYWORDS or any(keyword in title for keyword in TARGET_KEYWORDS):
                    href = a_tag.get('href', '').strip()
                    onclick = a_tag.get('onclick', '')

                    if "assi.or.kr" in base_url and "javascript:view" in href.lower():
                        m2 = re.search(r"view\(['\"]?(\d+)['\"]?\)", href, re.IGNORECASE)
                        link = f"http://www.assi.or.kr/sub/board/gongji_view.asp?idx={m2.group(1)}" if m2 else base_url
                    elif "pps.go.kr" in base_url and onclick:
                        m2 = re.search(r"['\"]([0-9a-zA-Z_]+)['\"]", onclick)
                        link = f"https://www.pps.go.kr/kor/bbs/view.do?key=00641&bbsSn={m2.group(1)}" if m2 else base_url
                    elif "javascript:" in href.lower() or href == "#":
                        m2 = re.search(r"\((['\"]?)(\d+)\1\)", href)
                        if m2 and "idx=" in base_url:
                            link = re.sub(r'idx=\d+', f'idx={m2.group(2)}', base_url)
                        else:
                            link = base_url
                    else:
                        link = urllib.parse.urljoin(base_url, href)

                    special_notes = deep_scan_notice(link) if link != base_url else "-"
                    results.append({
                        '출처': org_name, '등록일': date_str, '공고제목': title,
                        '상세링크': link, '특이사항': special_notes
                    })
        except Exception as e:
            log_error(f"bulldozer_scan_html-row:{org_name}", e)
            continue

    return results

def smart_scrape_board(url, domain, org_name):
    res = safe_get(url, timeout=(15, 30))
    if res is None:
        return [], 0
    try:
        results = bulldozer_scan_html(res.text, url, org_name)
        return results, len(results)
    except Exception as e:
        log_error(f"smart_scrape_board:{org_name}:{url}", e)
        return [], 0

def _build_driver(service, options):
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": DEFAULT_HEADERS['User-Agent']})
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def get_chrome_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    candidate_paths = [
        os.environ.get("CHROMEDRIVER_PATH", ""),
        "/usr/bin/chromedriver",
        "/usr/lib/chromium-browser/chromedriver",
    ]
    last_err = None
    for path in candidate_paths:
        if not path or not os.path.exists(path):
            continue
        try:
            return _build_driver(Service(path), chrome_options)
        except Exception as e:
            last_err = e

    try:
        return _build_driver(Service(ChromeDriverManager().install()), chrome_options)
    except Exception as e:
        last_err = e

    log_error("get_chrome_driver", last_err)
    raise RuntimeError("Chrome/Chromedriver를 찾을 수 없습니다.") from last_err

def smart_scrape_board_with_selenium(url, domain, org_name):
    results = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.set_page_load_timeout(45)

        if "igunsul.net" in url:
            if IGUNSUL_ID and IGUNSUL_PW:
                try:
                    driver.get("https://www.igunsul.net/login")
                    time.sleep(2)
                    id_js = json.dumps(IGUNSUL_ID)
                    pw_js = json.dumps(IGUNSUL_PW)
                    driver.execute_script(f"""
                        var idEl = document.querySelector('input[type="text"], input[name*="id"]');
                        var pwEl = document.querySelector('input[type="password"], input[name*="pw"]');
                        if (idEl) {{
                            idEl.value = {id_js};
                            idEl.dispatchEvent(new Event('input', {{bubbles: true}}));
                            idEl.dispatchEvent(new Event('change', {{bubbles: true}}));
                        }}
                        if (pwEl) {{
                            pwEl.value = {pw_js};
                            pwEl.dispatchEvent(new Event('input', {{bubbles: true}}));
                            pwEl.dispatchEvent(new Event('change', {{bubbles: true}}));
                        }}
                    """)
                    driver.execute_script("var f = document.querySelector('form'); if (f) f.submit();")
                    time.sleep(2)
                except Exception as e:
                    log_error("igunsul-login", e)
            else:
                log_error("igunsul-login", RuntimeError("IGUNSUL_ID / IGUNSUL_PW 미설정"))

        driver.get(url)
        time.sleep(4)

        in_iframe_idx = -1

        for page_num in range(1, 4):
            time.sleep(1)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")

            page_source_before = driver.page_source
            page_results = []

            if in_iframe_idx == -1:
                page_results = bulldozer_scan_html(page_source_before, url, org_name)
                if not page_results:
                    frames = driver.find_elements(By.TAG_NAME, "iframe") + driver.find_elements(By.TAG_NAME, "frame")
                    for i in range(len(frames)):
                        try:
                            driver.switch_to.frame(i)
                            iframe_results = bulldozer_scan_html(driver.page_source, url, org_name)
                            if iframe_results:
                                page_results.extend(iframe_results)
                                in_iframe_idx = i
                                break
                            driver.switch_to.default_content()
                        except Exception as e:
                            log_error(f"selenium-iframe:{org_name}", e)
                            driver.switch_to.default_content()
            else:
                page_results = bulldozer_scan_html(page_source_before, url, org_name)

            for item in page_results:
                if not any(r['공고제목'] == item['공고제목'] and r['출처'] == item['출처'] for r in results):
                    results.append(item)

            if page_num < 3:
                try:
                    next_page_str = str(page_num + 1)
                    next_btns = driver.find_elements(
                        By.XPATH,
                        f"//a[text()='{next_page_str}'] | //a[contains(text(), '[{next_page_str}]')] "
                        f"| //a[@title='{next_page_str}페이지']"
                    )
                    if next_btns:
                        driver.execute_script("arguments[0].click();", next_btns[0])
                        for _ in range(10):
                            time.sleep(0.5)
                            if driver.page_source != page_source_before:
                                break
                        time.sleep(1)
                    else:
                        break
                except Exception as e:
                    log_error(f"selenium-pagination:{org_name}", e)
                    break

        driver.switch_to.default_content()

    except Exception as e:
        log_error(f"smart_scrape_board_with_selenium:{org_name}", e)
    finally:
        if driver:
            try: driver.quit()
            except Exception: pass
    return results

def fetch_g2b_api(api_key, days_ago, keywords):
    if not api_key:
        log_error("fetch_g2b_api", RuntimeError("G2B_API_KEY가 설정되지 않았습니다."))
        return []
    g2b_now_kst = datetime.now(timezone(timedelta(hours=9)))
    end_dt = g2b_now_kst.strftime("%Y%m%d2359")
    start_dt = (g2b_now_kst - timedelta(days=days_ago)).strftime("%Y%m%d0000")
    results = []
    endpoints = ["getFcltyBidPblancListInfoServc", "getServcBidPblancListInfoServc", "getBidPblancListInfoServc"]

    for endpoint in endpoints:
        url = f"http://apis.data.go.kr/1230000/BidPublicInfoService04/{endpoint}"
        params = {
            "serviceKey": api_key, "numOfRows": "999", "pageNo": "1", "inqryDiv": "1",
            "inqryBgnDt": start_dt, "inqryEndDt": end_dt, "type": "json"
        }
        try:
            res = requests.get(url, params=params, timeout=30)
            if res.status_code != 200:
                log_error(f"fetch_g2b_api:{endpoint}", RuntimeError(f"HTTP {res.status_code}"))
                continue
            data = res.json()
            header = data.get('response', {}).get('header', {})
            result_code = str(header.get('resultCode', '00'))
            if result_code not in ("00", "0"):
                log_error(f"fetch_g2b_api:{endpoint}", RuntimeError(f"API 오류: {header.get('resultMsg', result_code)}"))
                continue
            items = data.get('response', {}).get('body', {}).get('items', [])
            for item in items:
                title = item.get('bidNtceNm', '')
                if not keywords or any(kw in title for kw in keywords):
                    region = item.get('prtcptPosblRgnNm', '')
                    quelfc = item.get('bidQuelfcCdNm', '')
                    link = item.get('bidNtceDtlUrl', '')

                    special = []
                    if region:
                        special.append(f"지역제한({region})")
                    if quelfc:
                        special.append("자격제한(상세확인)")
                    final_special_str = "🔥 " + ", ".join(special) if special else "-"

                    if not any(r['공고제목'] == title and r['출처'].startswith(item.get('dmdInsttNm', '조달청')) for r in results):
                        results.append({
                            '출처': f"{item.get('dmdInsttNm', '조달청')} (나라장터)",
                            '등록일': item.get('bidNtceDt', '')[:10].replace('-', '.'),
                            '공고제목': title,
                            '상세링크': link,
                            '특이사항': final_special_str
                        })
        except Exception as e:
            log_error(f"fetch_g2b_api:{endpoint}", e)
    return results

def load_target_sites():
    try:
        df_input = pd.read_excel(INPUT_EXCEL, sheet_name=0)
    except Exception as e:
        log_error("load_target_sites", e)
        return list(EXTRA_SITES)

    target_sites = []
    for index, row in df_input.iterrows():
        try:
            org_name = str(row.iloc[ORG_NAME_COL_INDEX]).strip()
            if not org_name or org_name == 'nan':
                org_name = "미상"
            url_j = str(row.iloc[9]).strip() if len(row) > 9 else ""
            url_k = str(row.iloc[10]).strip() if len(row) > 10 else ""
            if url_j.startswith('http'):
                target_sites.append({'url': url_j, 'org_name': org_name})
            if url_k.startswith('http'):
                target_sites.append({'url': url_k, 'org_name': org_name})
        except Exception as e:
            log_error(f"load_target_sites:row{index}", e)

    for site in target_sites:
        for k, v in URL_OVERRIDES.items():
            if k == site['org_name'] or k in site['org_name']:
                site['url'] = v

    target_sites.extend(EXTRA_SITES)
    unique_sites = {site['url']: site for site in target_sites}.values()
    return list(unique_sites)

def process_site(site):
    base_url, org_name = site['url'], site['org_name']
    domain = get_domain(base_url)

    res = safe_get(base_url, timeout=20, retries=1)
    if res is None:
        health_status = "🔌 연결 실패"
    elif res.status_code == 404:
        health_status = "❌ 404 에러"
    elif res.status_code != 200:
        health_status = f"⚠️ 서버 에러 ({res.status_code})"
    else:
        health_status = "공고 없음"

    urls_to_scrape = [base_url] + discover_additional_boards(base_url, domain)
    site_notices = []
    js_heavy_domains = ["igunsul.net", "pps.go.kr"]
    needs_selenium = any(d in domain for d in js_heavy_domains)

    for u in urls_to_scrape:
        try:
            if needs_selenium:
                data = smart_scrape_board_with_selenium(u, domain, org_name)
            else:
                data, rows_count = smart_scrape_board(u, domain, org_name)
                if rows_count == 0:
                    data = smart_scrape_board_with_selenium(u, domain, org_name)
            site_notices.extend(data)
        except Exception as e:
            log_error(f"process_site:{org_name}:{u}", e)

    return {
        'org_name': org_name, 'base_url': base_url, 'notices': site_notices,
        'found': len(site_notices) > 0, 'status': health_status
    }

# 🚀 런 함수에 target_orgs 파라미터 추가하여 발주처 필터링 연동
def run(days_ago=None, keywords=None, target_orgs="ALL", max_workers=2):
    global RUN_LOG, TARGET_KEYWORDS, target_date_limit, current_time
    RUN_LOG = []

    days_ago = DAYS_AGO_DEFAULT if days_ago is None else days_ago
    if keywords is None:
        kw_list = list(TARGET_KEYWORDS_DEFAULT)
    elif isinstance(keywords, str):
        kw_list = [w.strip() for w in keywords.split(',') if w.strip()]
    else:
        kw_list = list(keywords)
    TARGET_KEYWORDS = kw_list

    now_local = get_now_kst()
    if days_ago == 0:
        target_date_limit = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        target_date_limit = now_local - timedelta(days=days_ago)
    current_time = now_local.strftime("%Y-%m-%d %H:%M:%S")

    result = {"success": False, "new_notices": 0, "empty_sites": 0, "errors": [], "fatal": None}

    try:
        gc = get_gspread_client()
        doc = gc.open("맞춤공고_DB")
        ws_notices = doc.worksheet("notices")
        ws_collected = doc.worksheet("collected_orgs")
        ws_empty = doc.worksheet("empty_orgs")
        if not ws_notices.get_all_values():
            ws_notices.append_row(["출처", "등록일", "공고제목", "상세링크", "notice_key", "created_at", "특이사항", "검토유무"])
        if not ws_collected.get_all_values():
            ws_collected.append_row(["org_name"])
        existing_notices = ws_notices.get_all_records()
        history_keys = {str(row.get('notice_key', '')) for row in existing_notices}
        existing_collected = ws_collected.get_all_records()
        collected_orgs = {str(row.get('org_name', '')) for row in existing_collected if str(row.get('org_name', ''))}
    except Exception as e:
        log_error("init-google-sheets", e)
        result["errors"] = list(RUN_LOG)
        result["fatal"] = str(e)
        return result

    all_sites = load_target_sites()
    
    # 🚀 타겟 기관 필터링 적용 (전수조사가 아닌 경우)
    if target_orgs != "ALL":
        allowed_orgs = [o.strip() for o in target_orgs.split(',') if o.strip()]
        all_sites = [site for site in all_sites if site['org_name'] in allowed_orgs]
        if not all_sites:
            logger.warning("선택된 기관에 해당하는 사이트 URL이 명부에 없습니다.")
            result["success"] = True
            result["errors"] = ["선택된 기관에 해당하는 사이트 URL이 명부에 없습니다."]
            return result

    all_notices, empty_sites = [], []
    logger.info(f"[시작] 딥 스캔 엔진 가동 — 대상 {len(all_sites)}곳, 최근 {days_ago}일, 키워드 {kw_list}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_site = {executor.submit(process_site, site): site for site in all_sites}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_site), 1):
            site = future_to_site[future]
            try:
                res = future.result()
                logger.info(f"[{i}/{len(all_sites)}] 완료: {res['org_name']} ({len(res['notices'])}건)")
                if res['found']:
                    collected_orgs.add(res['org_name'])
                    all_notices.extend(res['notices'])
                else:
                    empty_sites.append({'출처기관': res['org_name'], '게시판_URL': res['base_url'], '분류': res['status']})
            except Exception as e:
                log_error(f"process_site-thread:{site.get('org_name')}", e)

    try:
        g2b_notices = fetch_g2b_api(G2B_API_KEY, days_ago, kw_list)
        if g2b_notices:
            all_notices.extend(g2b_notices)
    except Exception as e:
        log_error("fetch_g2b_api-outer", e)

    new_rows = []
    for item in all_notices:
        notice_key = f"{item['출처']}|||{item['공고제목']}|||{item.get('등록일', '')}"
        if notice_key not in history_keys:
            new_rows.append([
                item['출처'], item['등록일'], item['공고제목'], item['상세링크'],
                notice_key, current_time, item.get('특이사항', '-'), "미검토"
            ])
            history_keys.add(notice_key)

    try:
        if new_rows:
            ws_notices.append_rows(new_rows)
        new_orgs = [[org] for org in collected_orgs if org not in {str(r.get('org_name', '')) for r in existing_collected}]
        if new_orgs:
            ws_collected.append_rows(new_orgs)
        ws_empty.clear()
        ws_empty.append_row(['출처기관', '게시판_URL', '분류'])
        empty_rows = [[e['출처기관'], e['게시판_URL'], e['분류']] for e in empty_sites if e['출처기관'] not in collected_orgs]
        if empty_rows:
            ws_empty.append_rows(empty_rows)
    except Exception as e:
        log_error("save-to-sheets", e)

    logger.info("[종료] 딥 스캔 완료")
    result.update({
        "success": True,
        "new_notices": len(new_rows),
        "empty_sites": len(empty_sites),
        "errors": list(RUN_LOG),
    })
    return result

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        _days = int(sys.argv[1])
        _kw = sys.argv[2]
    else:
        _days = DAYS_AGO_DEFAULT
        _kw = ",".join(TARGET_KEYWORDS_DEFAULT)

    # 🚀 파라미터 3: 특정 발주처 목록 (ALL 이면 전수조사)
    if len(sys.argv) >= 4:
        _orgs = sys.argv[3]
    else:
        _orgs = "ALL"

    outcome = run(_days, _kw, _orgs)

    if not outcome.get("success"):
        print(f"[실패] 구글 시트 초기화 오류: {outcome.get('fatal')}")
        sys.exit(1)

    print(f"[성공] 신규 공고 {outcome['new_notices']}건, 미수집 사이트 {outcome['empty_sites']}곳, 경고/오류 {len(outcome['errors'])}건")
    if outcome['errors']:
        print("\n--- 상세 경고 로그 (최대 20개) ---")
        for line in outcome['errors'][:20]:
            print(line)

import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import urllib3
import time
import sys
import re
import concurrent.futures
import gspread  # 🌟 구글 시트 라이브러리

# 🌟 무적의 크롬 브라우저 조종석 (Selenium)
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
G2B_API_KEY = "9f7b495399ad64ec35b86f54a0a933fdf368b264bed9bcbf4e9b11556b6c9ff9"
# ==========================================

if len(sys.argv) >= 3:
    DAYS_AGO = int(sys.argv[1])
    TARGET_KEYWORDS = [word.strip() for word in sys.argv[2].split(',')]
else:
    DAYS_AGO = 15
    TARGET_KEYWORDS = ["안전", "모집", "지정", "공고", "용역"]

BOARD_MENU_KEYWORDS = ["공지", "알림", "고시", "소식", "입찰", "발주", "게시판"] 
ORG_NAME_COL_INDEX = 2 

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_EXCEL = os.path.join(BASE_DIR, '등록명부 정리시트.xlsx')

target_date_limit = datetime.now() - timedelta(days=DAYS_AGO)
current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ==========================================
# 🌟 [구글 시트 연동 및 초기 셋업]
# ==========================================
try:
    gc = gspread.service_account(filename="google_key.json")
    doc = gc.open("맞춤공고_DB")
    ws_notices = doc.worksheet("notices")
    ws_collected = doc.worksheet("collected_orgs")
    ws_empty = doc.worksheet("empty_orgs")
    
    if not ws_notices.get_all_values():
        ws_notices.append_row(["출처", "등록일", "공고제목", "상세링크", "notice_key", "created_at"])
    if not ws_collected.get_all_values():
        ws_collected.append_row(["org_name"])
        
    existing_notices = ws_notices.get_all_records()
    history_keys = {str(row.get('notice_key', '')) for row in existing_notices}
    
    existing_collected = ws_collected.get_all_records()
    collected_orgs = {str(row.get('org_name', '')) for row in existing_collected if str(row.get('org_name', ''))}
    
except Exception as e:
    print(f"❌ [치명적 오류] 구글 시트 연결 실패: {e}")
    sys.exit(1)

COMMON_ROW_SELECTORS = [
    "table.board_list tbody tr", "table.board-list tbody tr",
    "div.board_list tbody tr", ".list_tbl tbody tr", "tbody > tr",
    "ul.board_list > li", "div.list > ul > li"
]

def get_domain(url):
    try: return urllib.parse.urlparse(str(url)).netloc
    except: return ""

def discover_additional_boards(base_url, domain):
    headers = {'User-Agent': 'Mozilla/5.0'}
    discovered_urls = set()
    try:
        response = requests.get(base_url, headers=headers, verify=False, timeout=(5, 10))
        response.encoding = 'utf-8'
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                text = a_tag.get_text(strip=True)
                href = a_tag['href']
                if any(keyword in text for keyword in BOARD_MENU_KEYWORDS):
                    if "javascript:" in href.lower() or href == "#": continue
                    full_url = urllib.parse.urljoin(base_url, href)
                    if domain in full_url: discovered_urls.add(full_url)
    except Exception: pass
    return list(discovered_urls)[:3] 

# ---------------------------------------------------------
# 🛠️ 1차: 초고속 스캐너 (requests)
# ---------------------------------------------------------
def smart_scrape_board(url, domain, org_name):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    results = []
    rows_found_count = 0 
    
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=(5, 10))
        response.encoding = 'utf-8'
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            rows = []
            for selector in COMMON_ROW_SELECTORS:
                found_rows = soup.select(selector)
                if len(found_rows) > 0:
                    rows = found_rows
                    break
                    
            rows_found_count = len(rows) 
            
            for row in rows:
                title_tag = row.find('a')
                if title_tag:
                    title = title_tag.get_text(strip=True)
                    href = title_tag.get('href', '').strip()
                    link = url if "javascript:" in href.lower() or href == "#" or not href else urllib.parse.urljoin(url, href)
                        
                    date_str, post_date = "", None
                    for text in row.stripped_strings:
                        match = re.search(r'(20\d{2}|\d{2})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})', text)
                        if match:
                            y, m, d = match.groups()
                            if len(y) == 2: y = "20" + y 
                            try:
                                post_date = datetime(int(y), int(m), int(d))
                                date_str = post_date.strftime("%Y.%m.%d")
                                break
                            except ValueError: pass
                            
                    if post_date and post_date >= target_date_limit:
                        if any(keyword in title for keyword in TARGET_KEYWORDS):
                            results.append({'출처': org_name, '등록일': date_str, '공고제목': title, '상세링크': link})
    except Exception: pass
    return results, rows_found_count

# ---------------------------------------------------------
# 🤖 2차: 무적의 크롬 브라우저 (Selenium)
# ---------------------------------------------------------
def get_chrome_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080")
    
    try:
        service = Service('/usr/bin/chromedriver')
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def smart_scrape_board_with_selenium(url, domain, org_name):
    results = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.set_page_load_timeout(20)
        driver.get(url)
        time.sleep(3) # 자바스크립트 렌더링 대기
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = []
        for selector in COMMON_ROW_SELECTORS:
            found_rows = soup.select(selector)
            if len(found_rows) > 0:
                rows = found_rows
                break
                
        for row in rows:
            title_tag = row.find('a')
            if title_tag:
                title = title_tag.get_text(strip=True)
                href = title_tag.get('href', '').strip()
                link = url if "javascript:" in href.lower() or href == "#" or not href else urllib.parse.urljoin(url, href)
                    
                date_str, post_date = "", None
                for text in row.stripped_strings:
                    match = re.search(r'(20\d{2}|\d{2})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})', text)
                    if match:
                        y, m, d = match.groups()
                        if len(y) == 2: y = "20" + y 
                        try:
                            post_date = datetime(int(y), int(m), int(d))
                            date_str = post_date.strftime("%Y.%m.%d")
                            break
                        except ValueError: pass
                        
                if post_date and post_date >= target_date_limit:
                    if any(keyword in title for keyword in TARGET_KEYWORDS):
                        results.append({'출처': org_name, '등록일': date_str, '공고제목': title, '상세링크': link})
    except Exception:
        pass
    finally:
        if driver:
            driver.quit() 
    return results

def fetch_g2b_api(api_key, days_ago, keywords):
    if not api_key: return []
    print("\n🏛️ [나라장터] 조달청 오픈 API 접근 중...")
    end_dt = datetime.now().strftime("%Y%m%d2359")
    start_dt = (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d0000")
    results = []
    url = "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServc"
    params = {"serviceKey": api_key, "numOfRows": "999", "pageNo": "1", "inqryDiv": "1", "inqryBgnDt": start_dt, "inqryEndDt": end_dt, "type": "json"}
    try:
        res = requests.get(url, params=params, timeout=15)
        if res.status_code == 200:
            items = res.json().get('response', {}).get('body', {}).get('items', [])
            for item in items:
                title = item.get('bidNtceNm', '')
                if any(kw in title for kw in keywords):
                    results.append({
                        '출처': f"{item.get('dmdInsttNm', '조달청(미상)')} (나라장터)",
                        '등록일': item.get('bidNtceDt', '')[:10].replace('-', '.'),
                        '공고제목': title,
                        '상세링크': item.get('bidNtceDtlUrl', '')
                    })
    except Exception as e: print(f"❌ [나라장터 API 오류] {e}")
    return results

# ==========================================
EXTRA_SITES = [{'url': 'http://www.assi.or.kr/index.asp', 'org_name': '대한산업안전협회(수동추가)'}]

print(f"[시스템] 수집 기간: 최근 {DAYS_AGO}일 이내 | 수집 키워드: {TARGET_KEYWORDS}")
try:
    df_input = pd.read_excel(INPUT_EXCEL, sheet_name=0)
    target_sites = []
    for index, row in df_input.iterrows():
        org_name = str(row.iloc[ORG_NAME_COL_INDEX]).strip()
        if org_name == 'nan' or not org_name: org_name = "미상"
        url_j, url_k = str(row.iloc[9]).strip(), str(row.iloc[10]).strip() 
        if url_j.startswith('http'): target_sites.append({'url': url_j, 'org_name': org_name})
        if url_k.startswith('http'): target_sites.append({'url': url_k, 'org_name': org_name})
    target_sites.extend(EXTRA_SITES)
    unique_sites = {site['url']: site for site in target_sites}.values()
    all_sites = list(unique_sites)
except Exception:
    all_sites = EXTRA_SITES

def process_site(site):
    base_url, org_name = site['url'], site['org_name']
    domain = get_domain(base_url)
    urls_to_scrape = [base_url] + discover_additional_boards(base_url, domain)
    site_notices = []
    
    # 처음부터 크롬으로 뚫어야 하는 사이트
    js_heavy_domains = ["igunsul.net"]
    needs_selenium = any(d in domain for d in js_heavy_domains)

    for u in urls_to_scrape:
        if needs_selenium:
            data = smart_scrape_board_with_selenium(u, domain, org_name)
            site_notices.extend(data)
        else:
            # 하이브리드 로직
            data, rows_count = smart_scrape_board(u, domain, org_name)
            if rows_count == 0:
                data = smart_scrape_board_with_selenium(u, domain, org_name)
            site_notices.extend(data)
            
    return {'org_name': org_name, 'base_url': base_url, 'notices': site_notices, 'found': len(site_notices) > 0}

all_notices, empty_sites = [], []

# 크롬 브라우저 안정성을 위해 로봇은 3마리 유지
print(f"[시작] 🚀 구글 시트 연동 하이브리드 튜닝 엔진 가동 (로봇 3대 병렬 투입)")
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    future_to_site = {executor.submit(process_site, site): site for site in all_sites}
    for i, future in enumerate(concurrent.futures.as_completed(future_to_site), 1):
        try:
            res = future.result()
            print(f"[{i}/{len(all_sites)}] ✅ [완료] {res['org_name']} ({len(res['notices'])}건)")
            if res['found']:
                collected_orgs.add(res['org_name'])
                all_notices.extend(res['notices'])
            else:
                empty_sites.append({'출처기관': res['org_name'], '게시판_URL': res['base_url'], '분류': '공고 없음'})
        except Exception:
            pass

g2b_notices = fetch_g2b_api(G2B_API_KEY, DAYS_AGO, TARGET_KEYWORDS)
if g2b_notices:
    print(f"🎉 [성공] 조달청 나라장터에서 {len(g2b_notices)}건 수집 완료!")
    all_notices.extend(g2b_notices)

# ==========================================
# 🌟 [구글 시트에 최종 데이터 기록]
# ==========================================
print("\n📝 [저장 중] 튜닝 로봇이 수집한 데이터를 구글 시트에 기록합니다...")

new_rows = []
for item in all_notices:
    notice_key = f"{item['출처']}|||{item['공고제목']}"
    if notice_key not in history_keys:
        new_rows.append([item['출처'], item['등록일'], item['공고제목'], item['상세링크'], notice_key, current_time])
        history_keys.add(notice_key)

if new_rows:
    ws_notices.append_rows(new_rows)
    print(f"-> 🟢 구글 시트(notices)에 신규 공고 {len(new_rows)}건 추가 완료!")
else:
    print("-> ⚪ 새로운 공고가 없습니다.")

new_orgs = [[org] for org in collected_orgs if org not in {str(row.get('org_name', '')) for row in existing_collected}]
if new_orgs:
    ws_collected.append_rows(new_orgs)

ws_empty.clear()
ws_empty.append_row(['출처기관', '게시판_URL', '분류'])
empty_rows = []
for empty in empty_sites:
    if empty['출처기관'] not in collected_orgs:
        empty_rows.append([empty['출처기관'], empty['게시판_URL'], empty['분류']])
if empty_rows:
    ws_empty.append_rows(empty_rows)

print(f"\n[종료] 튜닝 모드 수집 및 구글 시트 저장 완료! 📱")

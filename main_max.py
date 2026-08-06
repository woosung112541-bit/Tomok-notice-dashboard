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
import gspread
import io
import olefile
from pypdf import PdfReader
import logging

logging.getLogger("pypdf").setLevel(logging.ERROR)

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

G2B_API_KEY = "9f7b495399ad64ec35b86f54a0a933fdf368b264bed9bcbf4e9b11556b6c9ff9"

if len(sys.argv) >= 3:
    DAYS_AGO = int(sys.argv[1])
    TARGET_KEYWORDS = [word.strip() for word in sys.argv[2].split(',')]
else:
    DAYS_AGO = 15
    TARGET_KEYWORDS = ["안전", "모집", "지정", "공고", "용역"]

if DAYS_AGO == 0:
    target_date_limit = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
else:
    target_date_limit = datetime.now() - timedelta(days=DAYS_AGO)

current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

BOARD_MENU_KEYWORDS = ["고시공고", "고시", "공고", "입찰", "발주", "새소식", "공지", "알림", "소식", "게시판"]
ORG_NAME_COL_INDEX = 2 

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_EXCEL = os.path.join(BASE_DIR, '등록명부 정리시트.xlsx')

PLUS_KWS = ["종합", "토목", "안전점검", "수행기관", "대전"]
MINUS_KWS = ["건축분야", "신축", "번지", "증축", "수의", "건립"]
REGION_KWS = ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']
REGION_HINT_KWS = ['지역제한', '소재지', '영업소', '한정', '관내', '소재한', '위치한']

try:
    gc = gspread.service_account(filename="google_key.json")
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
    print(f"❌ 구글 시트 연결 실패: {e}")
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
        response = requests.get(base_url, headers=headers, verify=False, timeout=(15, 30))
        soup = BeautifulSoup(response.text, 'html.parser')
        for a_tag in soup.find_all('a', href=True):
            text = a_tag.get_text(strip=True).replace(" ", "")
            href = a_tag['href']
            if any(keyword in text for keyword in BOARD_MENU_KEYWORDS):
                if "javascript:" in href.lower() or href == "#": continue
                full_url = urllib.parse.urljoin(base_url, href)
                if domain in full_url: discovered_urls.add(full_url)
    except: pass
    
    sorted_urls = sorted(list(discovered_urls), key=lambda x: ('gosi' in x.lower() or 'noti' in x.lower() or 'bid' in x.lower()), reverse=True)
    return sorted_urls[:5] 

def deep_scan_notice(url):
    found_specials = set()
    found_regions = set()
    full_text = ""
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, verify=False, timeout=30)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        full_text += soup.get_text()
        
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if href.endswith('.pdf') or href.endswith('.hwp'):
                file_url = urllib.parse.urljoin(url, a['href'])
                try:
                    f_res = requests.get(file_url, headers=headers, verify=False, timeout=30, stream=True)
                    if int(f_res.headers.get('content-length', 0)) < 5000000:
                        content = f_res.content
                        if href.endswith('.pdf'):
                            reader = PdfReader(io.BytesIO(content))
                            for page in reader.pages[:3]: 
                                full_text += " " + page.extract_text()
                        elif href.endswith('.hwp'):
                            f = olefile.OleFileIO(io.BytesIO(content))
                            if f.exists('PrvText'):
                                prv = f.openstream('PrvText').read().decode('utf-16le', errors='ignore')
                                full_text += " " + prv
                except: pass
                
        for kw in PLUS_KWS:
            if kw in full_text: found_specials.add(f"🔴{kw}")
            
        for kw in MINUS_KWS:
            if kw in full_text: found_specials.add(f"🔵{kw}")
            
        is_region_restricted = any(hint in full_text for hint in REGION_HINT_KWS)
        if is_region_restricted:
            for r in REGION_KWS:
                if r in full_text:
                    found_regions.add(r)
            if found_regions:
                found_specials.add(f"지역제한({','.join(list(found_regions))})")
            else:
                found_specials.add("지역제한(상세확인)")
    except: pass
    
    return "🔥 " + ", ".join(list(found_specials)) if found_specials else "-"

def smart_scrape_board(url, domain, org_name):
    headers = {'User-Agent': 'Mozilla/5.0'}
    results = []
    rows_found_count = 0
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=(15, 30))
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = []
        for selector in COMMON_ROW_SELECTORS:
            found_rows = soup.select(selector)
            if len(found_rows) > 0:
                rows = found_rows; break
        
        rows_found_count = len(rows)
        for row in rows:
            title_tag = row.find('a')
            if title_tag:
                title = " ".join(title_tag.stripped_strings)
                if not title: title = title_tag.get_text(strip=True)
                
                href = title_tag.get('href', '').strip()
                link = url if "javascript:" in href.lower() or href == "#" else urllib.parse.urljoin(url, href)
                    
                found_dates = []
                for text in row.stripped_strings:
                    matches = re.finditer(r'(20\d{2}|\d{2})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})', text)
                    for match in matches:
                        y, m, d = match.groups()
                        if len(y) == 2: y = "20" + y 
                        try:
                            pd_date = datetime(int(y), int(m), int(d))
                            found_dates.append(pd_date)
                        except: pass
                        
                post_date = None
                date_str = ""
                if found_dates:
                    post_date = min(found_dates)
                    date_str = post_date.strftime("%Y.%m.%d")
                        
                if post_date and post_date >= target_date_limit:
                    if any(keyword in title for keyword in TARGET_KEYWORDS):
                        special_notes = deep_scan_notice(link)
                        results.append({'출처': org_name, '등록일': date_str, '공고제목': title, '상세링크': link, '특이사항': special_notes})
    except: pass
    return results, rows_found_count

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
    except:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def smart_scrape_board_with_selenium(url, domain, org_name):
    results = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.set_page_load_timeout(60)
        driver.get(url)
        time.sleep(5) 
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = []
        for selector in COMMON_ROW_SELECTORS:
            found_rows = soup.select(selector)
            if len(found_rows) > 0:
                rows = found_rows; break
                
        for row in rows:
            title_tag = row.find('a')
            if title_tag:
                title = " ".join(title_tag.stripped_strings)
                if not title: title = title_tag.get_text(strip=True)
                
                href = title_tag.get('href', '').strip()
                link = url if "javascript:" in href.lower() or href == "#" else urllib.parse.urljoin(url, href)
                    
                found_dates = []
                for text in row.stripped_strings:
                    matches = re.finditer(r'(20\d{2}|\d{2})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})', text)
                    for match in matches:
                        y, m, d = match.groups()
                        if len(y) == 2: y = "20" + y 
                        try:
                            pd_date = datetime(int(y), int(m), int(d))
                            found_dates.append(pd_date)
                        except: pass
                        
                post_date = None
                date_str = ""
                if found_dates:
                    post_date = min(found_dates)
                    date_str = post_date.strftime("%Y.%m.%d")
                        
                if post_date and post_date >= target_date_limit:
                    if any(keyword in title for keyword in TARGET_KEYWORDS):
                        special_notes = deep_scan_notice(link)
                        results.append({'출처': org_name, '등록일': date_str, '공고제목': title, '상세링크': link, '특이사항': special_notes})
    except: pass
    finally:
        if driver: driver.quit() 
    return results

def fetch_g2b_api(api_key, days_ago, keywords):
    if not api_key: return []
    end_dt = datetime.now().strftime("%Y%m%d2359")
    start_dt = (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d0000")
    results = []
    url = "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServc"
    params = {"serviceKey": api_key, "numOfRows": "999", "pageNo": "1", "inqryDiv": "1", "inqryBgnDt": start_dt, "inqryEndDt": end_dt, "type": "json"}
    try:
        res = requests.get(url, params=params, timeout=30)
        if res.status_code == 200:
            items = res.json().get('response', {}).get('body', {}).get('items', [])
            for item in items:
                title = item.get('bidNtceNm', '')
                if any(kw in title for kw in keywords):
                    region = item.get('prtcptPosblRgnNm', '')
                    quelfc = item.get('bidQuelfcCdNm', '')
                    special = []
                    if region: special.append(f"지역제한({region})")
                    if quelfc: special.append("자격제한(상세확인)")
                    
                    results.append({
                        '출처': f"{item.get('dmdInsttNm', '조달청')} (나라장터)",
                        '등록일': item.get('bidNtceDt', '')[:10].replace('-', '.'),
                        '공고제목': title,
                        '상세링크': item.get('bidNtceDtlUrl', ''),
                        '특이사항': "🔥 " + ", ".join(special) if special else "-"
                    })
    except: pass
    return results

EXTRA_SITES = [{'url': 'http://www.assi.or.kr/index.asp', 'org_name': '대한산업안전협회(수동)'}]

try:
    df_input = pd.read_excel(INPUT_EXCEL, sheet_name=0)
    target_sites = []
    for index, row in df_input.iterrows():
        org_name = str(row.iloc[ORG_NAME_COL_INDEX]).strip()
        if not org_name or org_name == 'nan': org_name = "미상"
        url_j, url_k = str(row.iloc[9]).strip(), str(row.iloc[10]).strip() 
        if url_j.startswith('http'): target_sites.append({'url': url_j, 'org_name': org_name})
        if url_k.startswith('http'): target_sites.append({'url': url_k, 'org_name': org_name})
    target_sites.extend(EXTRA_SITES)
    unique_sites = {site['url']: site for site in target_sites}.values()
    all_sites = list(unique_sites)
except:
    all_sites = EXTRA_SITES

def process_site(site):
    base_url, org_name = site['url'], site['org_name']
    domain = get_domain(base_url)
    health_status = "공고 없음"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(base_url, headers=headers, verify=False, timeout=30)
        if res.status_code == 404: 
            health_status = "❌ 404 에러 (게시판 삭제 또는 개편 의심)"
        elif res.status_code != 200: 
            health_status = f"⚠️ 서버 에러 (상태코드: {res.status_code})"
    except requests.exceptions.Timeout:
        health_status = "⏳ 응답 지연 (서버 마비 의심)"
    except requests.exceptions.ConnectionError:
        health_status = "🔌 연결 실패 (주소 완전 변경 의심)"
    except Exception:
        health_status = "⚠️ 기타 접속 오류"

    urls_to_scrape = [base_url] + discover_additional_boards(base_url, domain)
    site_notices = []
    js_heavy_domains = ["igunsul.net"]
    needs_selenium = any(d in domain for d in js_heavy_domains)

    for u in urls_to_scrape:
        if needs_selenium:
            data = smart_scrape_board_with_selenium(u, domain, org_name)
            site_notices.extend(data)
        else:
            data, rows_count = smart_scrape_board(u, domain, org_name)
            if rows_count == 0:
                data = smart_scrape_board_with_selenium(u, domain, org_name)
            site_notices.extend(data)
            
    return {
        'org_name': org_name, 
        'base_url': base_url, 
        'notices': site_notices, 
        'found': len(site_notices) > 0,
        'status': health_status
    }

all_notices, empty_sites = [], []

print("[시작] 극한 탐색(최대 60초 대기/셀레니움) 가동")
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
                empty_sites.append({'출처기관': res['org_name'], '게시판_URL': res['base_url'], '분류': res['status']})
        except: pass

g2b_notices = fetch_g2b_api(G2B_API_KEY, DAYS_AGO, TARGET_KEYWORDS)
if g2b_notices: all_notices.extend(g2b_notices)

print("\n📝 [저장 중] 구글 시트에 기록합니다...")

new_rows = []
for item in all_notices:
    notice_key = f"{item['출처']}|||{item['공고제목']}"
    if notice_key not in history_keys:
        new_rows.append([
            item['출처'], item['등록일'], item['공고제목'], item['상세링크'], 
            notice_key, current_time, item.get('특이사항', '-'), "미검토"
        ])
        history_keys.add(notice_key)

if new_rows:
    ws_notices.append_rows(new_rows)
    print(f"-> 🟢 구글 시트에 신규 공고 {len(new_rows)}건 추가 완료!")

new_orgs = [[org] for org in collected_orgs if org not in {str(row.get('org_name', '')) for row in existing_collected}]
if new_orgs: ws_collected.append_rows(new_orgs)

ws_empty.clear()
ws_empty.append_row(['출처기관', '게시판_URL', '분류'])
empty_rows = [[e['출처기관'], e['게시판_URL'], e['분류']] for e in empty_sites if e['출처기관'] not in collected_orgs]
if empty_rows: ws_empty.append_rows(empty_rows)

print("\n[종료] 극한 탐색 수집 완료!")

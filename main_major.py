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
import warnings
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

logging.getLogger("pypdf").setLevel(logging.ERROR)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", module='bs4')

G2B_API_KEY = "9f7b495399ad64ec35b86f54a0a933fdf368b264bed9bcbf4e9b11556b6c9ff9"

if len(sys.argv) >= 3:
    DAYS_AGO = int(sys.argv[1])
    TARGET_KEYWORDS = [word.strip() for word in sys.argv[2].split(',')]
else:
    DAYS_AGO = 15
    TARGET_KEYWORDS = ["안전", "모집", "지정", "공고", "용역"]

if DAYS_AGO == 0: target_date_limit = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
else: target_date_limit = datetime.now() - timedelta(days=DAYS_AGO)
current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

BOARD_MENU_KEYWORDS = ["고시공고", "고시", "공고", "입찰", "발주", "새소식", "공지", "알림", "소식", "게시판"]

PLUS_KWS = ["종합", "토목", "안전점검", "수행기관", "대전"]
MINUS_KWS = ["건축분야", "신축", "번지", "증축", "수의", "건립"]
REGION_KWS = ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']
REGION_HINT_KWS = ['지역제한', '소재지', '영업소', '한정', '관내', '소재한', '위치한']

# 🌟 엑셀 로딩 패스! 오직 핵심 3개 웹사이트만 타겟팅 (나라장터는 별도 API)
MAJOR_SITES = [
    {'url': 'http://www.assi.or.kr/sub/board/gongji.asp?boardname=gongji', 'org_name': '한국시설안전협회'},
    {'url': 'https://www.pps.go.kr/kor/bbs/list.do?key=00641', 'org_name': '조달청 통합명부'},
    {'url': 'https://www.igunsul.net/', 'org_name': '아이건설넷'}
]

try:
    gc = gspread.service_account(filename="google_key.json")
    doc = gc.open("맞춤공고_DB")
    ws_notices = doc.worksheet("notices")
    if not ws_notices.get_all_values(): ws_notices.append_row(["출처", "등록일", "공고제목", "상세링크", "notice_key", "created_at", "특이사항", "검토유무"])
    existing_notices = ws_notices.get_all_records()
    history_keys = {str(row.get('notice_key', '')) for row in existing_notices}
except: sys.exit(1)

COMMON_ROW_SELECTORS = ["table.board_list tbody tr", "table.board-list tbody tr", "div.board_list tbody tr", ".list_tbl tbody tr", "tbody > tr", "ul.board_list > li", "div.list > ul > li"]

def deep_scan_notice(url):
    found_specials = set()
    found_regions = set()
    full_text = ""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, verify=False, timeout=7)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        full_text += soup.get_text()
        for kw in PLUS_KWS:
            if kw in full_text: found_specials.add(f"🔴{kw}")
        for kw in MINUS_KWS:
            if kw in full_text: found_specials.add(f"🔵{kw}")
        is_region_restricted = any(hint in full_text for hint in REGION_HINT_KWS)
        if is_region_restricted:
            for r in REGION_KWS:
                if r in full_text: found_regions.add(r)
            if found_regions: found_specials.add(f"지역제한({','.join(list(found_regions))})")
            else: found_specials.add("지역제한(상세확인)")
    except: pass
    return "🔥 " + ", ".join(list(found_specials)) if found_specials else "-"

def smart_scrape_board(url, domain, org_name):
    headers = {'User-Agent': 'Mozilla/5.0'}
    results = []
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=(10, 15))
        soup = BeautifulSoup(response.text, 'html.parser')
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
                
                # 🌟 한국시설안전협회 1단계 해법 (JS 우회 정규식)
                if "assi.or.kr" in url and "javascript:view" in href.lower():
                    match = re.search(r"view\(['\"]?(\d+)['\"]?\)", href, re.IGNORECASE)
                    if match: link = f"http://www.assi.or.kr/sub/board/gongji_view.asp?idx={match.group(1)}"
                    else: link = url
                elif "javascript:" in href.lower() or href == "#": link = url
                else: link = urllib.parse.urljoin(url, href)
                    
                found_dates = []
                for text in row.stripped_strings:
                    matches = re.finditer(r'(20\d{2}|\d{2})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})', text)
                    for match in matches:
                        y, m, d = match.groups()
                        if len(y) == 2: y = "20" + y 
                        try: pd_date = datetime(int(y), int(m), int(d)); found_dates.append(pd_date)
                        except: pass
                post_date = min(found_dates) if found_dates else None
                date_str = post_date.strftime("%Y.%m.%d") if post_date else ""
                
                if post_date and post_date >= target_date_limit:
                    if not TARGET_KEYWORDS or any(keyword in title for keyword in TARGET_KEYWORDS):
                        special_notes = deep_scan_notice(link)
                        results.append({'출처': org_name, '등록일': date_str, '공고제목': title, '상세링크': link, '특이사항': special_notes})
    except: pass
    return results

# 🌟 최상위 스텔스 모드 드라이버 세팅 (아이건설넷 방어막 뚫기용)
def get_stealth_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled") # 봇 탐지 방해
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    try:
        service = Service('/usr/bin/chromedriver')
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
    driver.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'})
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def smart_scrape_board_with_stealth_selenium(url, domain, org_name):
    results = []
    driver = None
    try:
        driver = get_stealth_driver()
        driver.set_page_load_timeout(30)
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
                link = urllib.parse.urljoin(url, href) if not ("javascript:" in href.lower() or href == "#") else url
                found_dates = []
                for text in row.stripped_strings:
                    matches = re.finditer(r'(20\d{2}|\d{2})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})', text)
                    for match in matches:
                        y, m, d = match.groups()
                        if len(y) == 2: y = "20" + y 
                        try: pd_date = datetime(int(y), int(m), int(d)); found_dates.append(pd_date)
                        except: pass
                post_date = min(found_dates) if found_dates else None
                date_str = post_date.strftime("%Y.%m.%d") if post_date else ""
                
                if post_date and post_date >= target_date_limit:
                    if not TARGET_KEYWORDS or any(keyword in title for keyword in TARGET_KEYWORDS):
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
                if not keywords or any(kw in title for kw in keywords):
                    region = item.get('prtcptPosblRgnNm', '')
                    quelfc = item.get('bidQuelfcCdNm', '')
                    special = []
                    if region: special.append(f"지역제한({region})")
                    if quelfc: special.append("자격제한(상세확인)")
                    results.append({'출처': f"{item.get('dmdInsttNm', '조달청')} (나라장터)", '등록일': item.get('bidNtceDt', '')[:10].replace('-', '.'), '공고제목': title, '상세링크': item.get('bidNtceDtlUrl', ''), '특이사항': "🔥 " + ", ".join(special) if special else "-"})
    except: pass
    return results

def process_major_site(site):
    base_url, org_name = site['url'], site['org_name']
    domain = urllib.parse.urlparse(str(base_url)).netloc
    site_notices = []
    
    if org_name == '한국시설안전협회':
        # 1단계 맞춤 타격
        data = smart_scrape_board(base_url, domain, org_name)
        if not data: data = smart_scrape_board_with_stealth_selenium(base_url, domain, org_name)
        site_notices.extend(data)
    else:
        # 조달청 통합명부 및 아이건설넷 스텔스 타격
        data = smart_scrape_board_with_stealth_selenium(base_url, domain, org_name)
        site_notices.extend(data)
        
    return {'org_name': org_name, 'notices': site_notices}

all_notices = []
print("[시작] 🌟 4대 중앙 사이트 전용 스텔스 엔진 가동")

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    future_to_site = {executor.submit(process_major_site, site): site for site in MAJOR_SITES}
    for i, future in enumerate(concurrent.futures.as_completed(future_to_site), 1):
        try:
            res = future.result()
            print(f"[{i}/{len(MAJOR_SITES)}] ✅ [완료] {res['org_name']} ({len(res['notices'])}건)")
            all_notices.extend(res['notices'])
        except: pass

print(f"[API] ✅ [완료] 나라장터 (G2B) 연동 중...")
g2b_notices = fetch_g2b_api(G2B_API_KEY, DAYS_AGO, TARGET_KEYWORDS)
if g2b_notices: 
    print(f" -> {len(g2b_notices)}건 수집 완료")
    all_notices.extend(g2b_notices)

print("\n📝 [저장 중] 구글 시트에 기록합니다...")
new_rows = []
for item in all_notices:
    notice_key = f"{item['출처']}|||{item['공고제목']}"
    if notice_key not in history_keys:
        new_rows.append([item['출처'], item['등록일'], item['공고제목'], item['상세링크'], notice_key, current_time, item.get('특이사항', '-'), "미검토"])
        history_keys.add(notice_key)

if new_rows: ws_notices.append_rows(new_rows)
print("\n[종료] 주요 4대 중앙 사이트 전용 수집 완료!")

import json
import os

# 검증 완료된 사이트 목록 불러오기 함수
def load_verified_sites():
    file_path = 'verified_sites.json'
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()



import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import os
import urllib.parse
import urllib3
import time
import sys

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 📱 [텔레그램 알림 설정]
# ==========================================
TELEGRAM_TOKEN = "8732310390:AAGT20ClcRU2pb6F4z2zPJ1ug0_5MMlSv_E"
TELEGRAM_CHAT_ID = "7442626003"

def send_telegram_message(msg):
    if TELEGRAM_TOKEN == "여기에_토큰을_입력하세요" or not TELEGRAM_TOKEN or TELEGRAM_CHAT_ID == "여기에_숫자ID를_입력하세요":
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"[알림 오류] 텔레그램 전송 실패: {e}")

# ==========================================
# [환경 설정]
# ==========================================
if len(sys.argv) >= 3:
    DAYS_AGO = int(sys.argv[1])
    TARGET_KEYWORDS = [word.strip() for word in sys.argv[2].split(',')]
else:
    DAYS_AGO = 10
    TARGET_KEYWORDS = ["안전", "모집", "지정", "공고", "용역"]

BOARD_MENU_KEYWORDS = ["공지", "알림", "고시", "소식", "입찰", "발주", "게시판"] 
ORG_NAME_COL_INDEX = 2 

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_EXCEL = os.path.join(BASE_DIR, '등록명부 정리시트.xlsx')
OUTPUT_EXCEL = os.path.join(BASE_DIR, '통합_맞춤공고.xlsx')
CHECK_EXCEL = os.path.join(BASE_DIR, '수동확인_필요목록.xlsx')
HISTORY_FILE = os.path.join(BASE_DIR, '알림내역_기록장부.txt') 

target_date_limit = datetime.now() - timedelta(days=DAYS_AGO)
current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
# ==========================================

history_urls = set()
if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        history_urls = set(line.strip() for line in f)

COMMON_ROW_SELECTORS = [
    "table.board_list tbody tr", 
    "table.board-list tbody tr",
    "div.board_list tbody tr",
    ".list_tbl tbody tr",
    "tbody > tr",
    "ul.board_list > li",
    "div.list > ul > li"
]

def get_domain(url):
    try:
        return urllib.parse.urlparse(str(url)).netloc
    except:
        return ""

def discover_additional_boards(base_url, domain):
    headers = {'User-Agent': 'Mozilla/5.0'}
    discovered_urls = set()
    try:
        response = requests.get(base_url, headers=headers, verify=False, timeout=10)
        response.encoding = 'utf-8'
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                text = a_tag.get_text(strip=True)
                href = a_tag['href']
                
                if any(keyword in text for keyword in BOARD_MENU_KEYWORDS):
                    if "javascript:" in href.lower() or href == "#":
                        continue
                    full_url = urllib.parse.urljoin(base_url, href)
                    if domain in full_url: 
                        discovered_urls.add(full_url)
    except Exception:
        pass
    return list(discovered_urls)[:3] 

def smart_scrape_board(url, domain, org_name):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    results = []
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=15)
        response.encoding = 'utf-8'
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
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
                    
                    if "javascript:" in href.lower() or href == "#" or "void(" in href.lower() or not href:
                        link = url 
                    else:
                        link = urllib.parse.urljoin(url, href)
                        
                    date_str = ""
                    for text in row.stripped_strings:
                        text = text.replace("-", ".")
                        if "." in text and len(text) == 10 and text.startswith("202"):
                            date_str = text
                            break
                            
                    if date_str:
                        try:
                            post_date = datetime.strptime(date_str, "%Y.%m.%d")
                            if post_date >= target_date_limit:
                                if any(keyword in title for keyword in TARGET_KEYWORDS):
                                    results.append({
                                        '출처': org_name,
                                        '등록일': date_str,
                                        '공고제목': title,
                                        '상세링크': link
                                    })
                        except ValueError:
                            pass
    except Exception:
        pass
    return results

# ==========================================
print(f"[시스템] 데이터 수집 기준: 최근 {DAYS_AGO}일 이내 | 검출 키워드: {TARGET_KEYWORDS}")
print("[진행] 대상 기관 명부 및 URL 데이터를 로드합니다...")
try:
    df_input = pd.read_excel(INPUT_EXCEL, sheet_name=0)
    target_sites = []
    for index, row in df_input.iterrows():
        org_name = str(row.iloc[ORG_NAME_COL_INDEX]).strip()
        if org_name == 'nan' or not org_name:
            org_name = "미상"
            
        url_j = str(row.iloc[9]).strip()  
        url_k = str(row.iloc[10]).strip() 
        
        if url_j.startswith('http'):
            target_sites.append({'url': url_j, 'org_name': org_name})
        if url_k.startswith('http'):
            target_sites.append({'url': url_k, 'org_name': org_name})
            
    unique_sites = {site['url']: site for site in target_sites}.values()
    all_sites = list(unique_sites)
    print(f"[진행] 총 {len(all_sites)}개의 유효 접속 주소가 확보되었습니다.\n")
except Exception as e:
    print(f"[오류] 데이터 로드 실패: {e}")
    all_sites = []

# ==========================================
all_notices = []
empty_sites = [] 
new_alert_count = 0

print("[시작] 하위 링크 심층 분석 및 데이터 수집 알고리즘을 가동합니다.")
for i, site in enumerate(all_sites, 1):
    base_url = site['url']
    org_name = site['org_name']
    domain = get_domain(base_url)
    
    print(f"\n[{i}/{len(all_sites)}] [탐색] {org_name} 접속 및 분석 중...")
    urls_to_scrape = [base_url]
    
    print("   - [분석] 연관 하위 게시판(알림/고시/입찰 등) 추가 식별 진행...")
    discovered = discover_additional_boards(base_url, domain)
    if discovered:
        print(f"   - [결과] 유효 하위 게시판 {len(discovered)}개소 추가 식별 완료.")
        urls_to_scrape.extend(discovered)
    
    site_found_notices = False
    
    for idx, url_to_scrape in enumerate(urls_to_scrape):
        scraped_data = smart_scrape_board(url_to_scrape, domain, org_name)
        if scraped_data:
            site_found_notices = True
            
            for item in scraped_data:
                all_notices.append(item) 
                link = item['상세링크']
                
                if link not in history_urls:
                    history_urls.add(link)
                    new_alert_count += 1
                    
                    with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
                        f.write(link + '\n')
                    
                    msg_text = (
                        f"🚨 <b>[신규 공고 알림]</b>\n\n"
                        f"🏢 <b>발주기관:</b> {item['출처']}\n"
                        f"📌 <b>공고제목:</b> {item['공고제목']}\n"
                        f"📅 <b>등록일자:</b> {item['등록일']}\n\n"
                        f"🔗 <a href='{link}'>상세내용 확인하기</a>"
                    )
                    send_telegram_message(msg_text)
                    time.sleep(0.5) 
                    
            print(f"   - [수집] (대상 {idx+1}) 조건 부합 데이터 {len(scraped_data)}건 수집 완료.")
        time.sleep(1) 
        
    if not site_found_notices:
        empty_sites.append({
            '출처기관': org_name,
            '게시판_URL': base_url,
            '분류': '신규 데이터 없음 또는 접근 불가'
        })
        print(f"   - [안내] 수집된 데이터 없음. (수동 점검 대상으로 분류)")

# ==========================================
if len(all_notices) > 0:
    df_output = pd.DataFrame(all_notices)
    df_output = df_output.drop_duplicates(subset=['공고제목'])
    df_output.to_excel(OUTPUT_EXCEL, index=False)
    print(f"\n[종료] 수집 완료. 총 {len(df_output)}건 중 신규 알림 {new_alert_count}건 전송됨.")
else:
    df_output = pd.DataFrame([{'출처': '-', '등록일': '-', '공고제목': f"[{current_time}] 조건에 부합하는 신규 데이터가 없습니다.", '상세링크': '-'}])
    df_output.to_excel(OUTPUT_EXCEL, index=False)
    print(f"\n[종료] 수집 완료. 조건에 부합하는 신규 데이터가 없습니다.")

if empty_sites:
    df_empty = pd.DataFrame(empty_sites)
    df_empty.to_excel(CHECK_EXCEL, index=False)

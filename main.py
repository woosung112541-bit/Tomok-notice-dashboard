import json
import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
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
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"[알림 오류] 텔레그램 전송 실패: {e}")

# ==========================================
# [환경 설정 및 파일 경로]
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
COLLECTED_ORGS_FILE = os.path.join(BASE_DIR, 'collected_orgs.json') # 공고 수집 성공 기관 장부

target_date_limit = datetime.now() - timedelta(days=DAYS_AGO)
current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 1. 중복 알림 방지 장부 로드 (기관명 + 공고제목 조합으로 엄격 체킹)
history_keys = set()
if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        history_keys = set(line.strip() for line in f if line.strip())

# 2. 여태껏 공고 수집에 성공했던 기관 장부 로드
collected_orgs = set()
if os.path.exists(COLLECTED_ORGS_FILE):
    try:
        with open(COLLECTED_ORGS_FILE, 'r', encoding='utf-8') as f:
            collected_orgs = set(json.load(f))
    except Exception:
        pass

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

print("[시작] 공고 수집 및 알고리즘을 가동합니다.")
for i, site in enumerate(all_sites, 1):
    base_url = site['url']
    org_name = site['org_name']
    domain = get_domain(base_url)
    
    print(f"\n[{i}/{len(all_sites)}] [탐색] {org_name} 접속 중...")
    urls_to_scrape = [base_url]
    
    discovered = discover_additional_boards(base_url, domain)
    if discovered:
        urls_to_scrape.extend(discovered)
    
    site_found_notices = False
    
    for idx, url_to_scrape in enumerate(urls_to_scrape):
        scraped_data = smart_scrape_board(url_to_scrape, domain, org_name)
        if scraped_data:
            site_found_notices = True
            
            # ★ 성공한 기관 자동 기록
            collected_orgs.add(org_name)
            
            for item in scraped_data:
                all_notices.append(item)
                
                # ★ 중복 알림 방지용 고유키 (기관명 + 제목)
                notice_key = f"{item['출처']}|||{item['공고제목']}"
                
                if notice_key not in history_keys:
                    history_keys.add(notice_key)
                    new_alert_count += 1
                    
                    with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
                        f.write(notice_key + '\n')
                    
                    msg_text = (
                        f"🚨 <b>[신규 공고 알림]</b>\n\n"
                        f"🏢 <b>발주기관:</b> {item['출처']}\n"
                        f"📌 <b>공고제목:</b> {item['공고제목']}\n"
                        f"📅 <b>등록일자:</b> {item['등록일']}\n\n"
                        f"🔗 <a href='{item['상세링크']}'>상세내용 확인하기</a>"
                    )
                    send_telegram_message(msg_text)
                    time.sleep(0.3)
                    
            print(f"   - [수집] 조건 부합 데이터 {len(scraped_data)}건 수집 완료.")
        time.sleep(0.5) 
        
    if not site_found_notices:
        empty_sites.append({
            '출처기관': org_name,
            '게시판_URL': base_url,
            '분류': '신규 데이터 없음 또는 접근 불가'
        })

# ==========================================
# 1. 수집 성공 기관 장부 저장
with open(COLLECTED_ORGS_FILE, 'w', encoding='utf-8') as f:
    json.dump(list(collected_orgs), f, ensure_ascii=False, indent=4)

# 2. 결과 엑셀 생성
if len(all_notices) > 0:
    df_output = pd.DataFrame(all_notices)
    df_output = df_output.drop_duplicates(subset=['출처', '공고제목'])
    df_output.to_excel(OUTPUT_EXCEL, index=False)
    print(f"\n[종료] 수집 완료. 총 {len(df_output)}건 중 신규 알림 {new_alert_count}건 전송됨.")
else:
    df_output = pd.DataFrame([{'출처': '-', '등록일': '-', '공고제목': f"[{current_time}] 조건에 부합하는 신규 데이터가 없습니다.", '상세링크': '-'}])
    df_output.to_excel(OUTPUT_EXCEL, index=False)
    print(f"\n[종료] 수집 완료. 조건에 부합하는 신규 데이터가 없습니다.")

# 3. 추가검토 필요 기관 필터링 (여태껏 단 한 번도 공고를 수집해본 적 없는 기관만 추출)
if empty_sites:
    filtered_empty_sites = [
        site for site in empty_sites 
        if site['출처기관'] not in collected_orgs
    ]
    
    if filtered_empty_sites:
        df_empty = pd.DataFrame(filtered_empty_sites)
        df_empty.to_excel(CHECK_EXCEL, index=False)
        print(f"[안내] 역사상 수집 기록이 단 1건도 없는 진짜 미확인 기관 {len(filtered_empty_sites)}개만 수동확인 목록에 저장되었습니다.")
    else:
        if os.path.exists(CHECK_EXCEL):
            os.remove(CHECK_EXCEL)
        print("[안내] 미수집 기관들이 모두 과거 수집 성공 이력이 있는 곳이므로 수동확인 목록이 생성되지 않았습니다.")

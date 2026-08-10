import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta, timezone
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

logging.getLogger("pypdf").setLevel(logging.ERROR)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", module='bs4')

G2B_API_KEY = "9f7b495399ad64ec35b86f54a0a933fdf368b264bed9bcbf4e9b11556b6c9ff9"

# 🌟 한국 표준시(KST) 기반으로 시간 강제 연산
KST = timezone(timedelta(hours=9))
now_kst = datetime.now(KST).replace(tzinfo=None)

if len(sys.argv) >= 3:
    DAYS_AGO = int(sys.argv[1])
    TARGET_KEYWORDS = [word.strip() for word in sys.argv[2].split(',')]
else:
    DAYS_AGO = 15
    TARGET_KEYWORDS = ["안전", "모집", "지정", "공고", "용역"]

if DAYS_AGO == 0: target_date_limit = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
else: target_date_limit = now_kst - timedelta(days=DAYS_AGO)
current_time = now_kst.strftime("%Y-%m-%d %H:%M:%S")

BOARD_MENU_KEYWORDS = ["고시공고", "고시", "공고", "입찰", "발주", "새소식", "공지", "알림", "소식", "게시판"]
ORG_NAME_COL_INDEX = 2 

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_EXCEL = os.path.join(BASE_DIR, '등록명부 정리시트.xlsx')

PLUS_KWS = ["종합", "토목", "안전점검", "수행기관", "대전"]
MINUS_KWS = ["건축분야", "신축", "번지", "증축", "수의", "건립"]
REGION_KWS = ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']
REGION_HINT_KWS = ['지역제한', '소재지', '영업소', '한정', '관내', '소재한', '위치한']

EXTRA_SITES = [
    {'url': 'http://www.assi.or.kr/sub/board/gongji.asp?boardname=gongji', 'org_name': '한국시설안전협회'},
    {'url': 'https://www.pps.go.kr/kor/bbs/list.do?key=00641', 'org_name': '조달청 통합명부'},
    {'url': 'https://www.igunsul.net/', 'org_name': '아이건설넷'}
]

try:
    gc = gspread.service_account(filename="google_key.json")
    doc = gc.open("맞춤공고_DB")
    ws_notices = doc.worksheet("notices")
    ws_collected = doc.worksheet("collected_orgs")
    ws_empty = doc.worksheet("empty_orgs")
    
    if not ws_notices.get_all_values(): ws_notices.append_row(["출처", "등록일", "공고제목", "상세링크", "notice_key", "created_at", "특이사항", "검토유무"])
    if not ws_collected.get_all_values(): ws_collected.append_row(["org_name"])
        
    existing_notices = ws_notices.get_all_records()
    history_keys = {str(row.get('notice_key', '')) for row in existing_notices}
    existing_collected = ws_collected.get_all_records()
    collected_orgs = {str(row.get('org_name', '')) for row in existing_collected if str(row.get('org_name', ''))}
except Exception as e:
    sys.exit(1)

COMMON_ROW_SELECTORS = ["table.board_list tbody tr", "table.board-list tbody tr", "div.board_list tbody tr", ".list_tbl tbody tr", "tbody > tr", "ul.board_list > li", "div.list > ul > li"]

def get_domain(url):
    try: return urllib.parse.urlparse(str(url)).netloc
    except: return ""

def discover_additional_boards(base_url, domain):
    headers = {'User-Agent': 'Mozilla/5.0'}
    discovered_urls = set()
    try:
        response = requests.get(base_url, headers=headers, verify=False, timeout=(10, 15))
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
        res = requests.get(url, headers=headers, verify=False, timeout=7)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        full_text += soup.get_text()
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if href.endswith('.pdf') or href.endswith('.hwp'):
                file_url = urllib.parse.urljoin(url, a['href'])
                try:
                    f_res = requests.get(file_url, headers=headers, verify=False, timeout=5, stream=True)
                    if int(f_res.headers.get('content-length', 0)) < 5000000:
                        content = f_res.content
                        if href.endswith('.pdf'):
                            reader = PdfReader(io.BytesIO(content))
                            for page in reader.pages[:3]: full_text += " " + page.extract_text()
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
                if r in full_text: found_regions.add(r)
            if found_regions: found_specials.add(f"지역제한({','.join(list(found_regions))})")
            else: found_specials.add("지역제한(상세확인)")
    except: pass
    return "🔥 " + ", ".join(list(found_specials)) if found_specials else "-"

def smart_scrape_board(url, domain, org_name):
    headers = {'User-Agent': 'Mozilla/5.0'}
    results = []
    rows_found_count = 0
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=(10, 15))
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
                if "assi.or.kr" in url and "javascript:view" in href.lower():
                    match = re.search(r"view\(['\"]?(\d+)['\"]?\)", href, re.IGNORECASE)
                    if match: link = f"http://www.assi.or.kr/sub/board/gongji_view.asp?idx={match.group(1)}"
                    else: link = url
                elif "pps.go.kr" in url and title_tag.has_attr('onclick'):
                    onclick_text = title_tag['onclick']
                    match = re.search(r"['\"]([0-9a-zA-Z_]+)['\"]", onclick_text)
                    if match: link = f"https://www.pps.go.kr/kor/bbs/view.do?key=00641&bbsSn={match.group(1)}"
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
                post_date = None
                date_str = ""
                if found_dates:
                    post_date = min(found_dates)
                    date_str = post_date.strftime("%Y.%m.%d")
                if post_date and post_date >= target_date_limit:
                    if not TARGET_KEYWORDS or any(keyword in title for keyword in TARGET_KEYWORDS):
                        special_notes = deep_scan_notice(link)
                        results.append({'출처': org_name, '등록일': date_str, '공고제목': title, '상세링크': link, '특이사항': special_notes})
    except: pass
    return results, rows_found_count

def fetch_g2b_api(api_key, days_ago, keywords):
    if not api_key: return []
    # 🌟 G2B API 시간도 KST 기반으로 조회
    g2b_now_kst = datetime.now(timezone(timedelta(hours=9)))
    end_dt = g2b_now_kst.strftime("%Y%m%d2359")
    start_dt = (g2b_now_kst - timedelta(days=days_ago)).strftime("%Y%m%d0000")
    results = []
    endpoints = ["getFcltyBidPblancListInfoServc", "getServcBidPblancListInfoServc", "getBidPblancListInfoServc"]
    
    for endpoint in endpoints:
        url = f"http://apis.data.go.kr/1230000/BidPublicInfoService04/{endpoint}"
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
                        link = item.get('bidNtceDtlUrl', '')
                        
                        special = []
                        if region: special.append(f"지역제한({region})")
                        if quelfc: special.append("자격제한(상세확인)")
                        
                        deep_special = deep_scan_notice(link) if link else "-"
                        
                        final_special = []
                        if special: final_special.append("🔥 " + ", ".join(special))
                        if deep_special != "-": final_special.append(deep_special)
                        final_special_str = " / ".join(final_special) if final_special else "-"
                        
                        if not any(r['공고제목'] == title and r['출처'].startswith(item.get('dmdInsttNm', '조달청')) for r in results):
                            results.append({
                                '출처': f"{item.get('dmdInsttNm', '조달청')} (나라장터)", 
                                '등록일': item.get('bidNtceDt', '')[:10].replace('-', '.'), 
                                '공고제목': title, 
                                '상세링크': link, 
                                '특이사항': final_special_str
                            })
        except: pass
    return results

try:
    df_input = pd.read_excel(INPUT_EXCEL, sheet_name=0)
    target_sites = []
    for index, row in df_input.iterrows():
        org_name = str(row.iloc[ORG_NAME_COL_INDEX]).strip()
        if not org_name or org_name == 'nan': org_name = "미상"
        url_j, url_k = str(row.iloc[9]).strip(), str(row.iloc[10]).strip() 
        if url_j.startswith('http'): target_sites.append({'url': url_j, 'org_name': org_name})
        if url_k.startswith('http'): target_sites.append({'url': url_k, 'org_name': org_name})
    
    URL_OVERRIDES = {
        "대전교통공사": "https://www.djtc.kr/kor/board.do?menuIdx=361",
        "서산시": "https://www.seosan.go.kr/www/contents.do?key=1258",
        "대전광역시 서구": "https://www.seogu.go.kr/prog/saeolGosi/GOSI/kor/sub04_02_01/list.do",
        "논산시": "https://www.nonsan.go.kr/kor/html/sub03/03010201.html",
        "용인특례시": "https://www.yongin.go.kr/home/yiNw/yiNwStable/yiNwStable02/yiNwStable02_01.jsp",
        "용인시": "https://www.yongin.go.kr/home/yiNw/yiNwStable/yiNwStable02/yiNwStable02_01.jsp"
    }
    for site in target_sites:
        for k, v in URL_OVERRIDES.items():
            if k == site['org_name'] or k in site['org_name']:
                site['url'] = v

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
        res = requests.get(base_url, headers=headers, verify=False, timeout=7)
        if res.status_code == 404: health_status = "❌ 404 에러"
        elif res.status_code != 200: health_status = f"⚠️ 서버 에러 ({res.status_code})"
    except: health_status = "🔌 연결 실패"
    urls_to_scrape = [base_url] + discover_additional_boards(base_url, domain)
    site_notices = []
    for u in urls_to_scrape:
        data, _ = smart_scrape_board(u, domain, org_name)
        site_notices.extend(data)
    return {'org_name': org_name, 'base_url': base_url, 'notices': site_notices, 'found': len(site_notices) > 0, 'status': health_status}

all_notices, empty_sites = [], []
print("[시작] 빠른 탐색(딥스캔) 가동")
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
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
        new_rows.append([item['출처'], item['등록일'], item['공고제목'], item['상세링크'], notice_key, current_time, item.get('특이사항', '-'), "미검토"])
        history_keys.add(notice_key)
if new_rows: ws_notices.append_rows(new_rows)
new_orgs = [[org] for org in collected_orgs if org not in {str(row.get('org_name', '')) for row in existing_collected}]
if new_orgs: ws_collected.append_rows(new_orgs)
ws_empty.clear()
ws_empty.append_row(['출처기관', '게시판_URL', '분류'])
empty_rows = [[e['출처기관'], e['게시판_URL'], e['분류']] for e in empty_sites if e['출처기관'] not in collected_orgs]
if empty_rows: ws_empty.append_rows(empty_rows)
print("\n[종료] 빠른 탐색 수집 완료!")

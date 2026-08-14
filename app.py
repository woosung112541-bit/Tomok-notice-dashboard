import streamlit as st
import pandas as pd
import os
import subprocess
import sys
import gspread
import plotly.express as px
import time
import re
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

# 한국 표준시(KST) 강제 설정
KST = timezone(timedelta(hours=9))

# 화면 기본 설정
st.set_page_config(page_title="맞춤 공고 수집 대시보드", layout="wide")

# ==========================================
# 대시보드 보안 설정
# ==========================================
DASHBOARD_PASSWORD = "0804"  

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if not st.session_state["password_correct"]:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🔒 대시보드 보안 접속")
            pwd_input = st.text_input("🔑 비밀번호 입력", type="password")
            if st.button("🚀 접속하기", use_container_width=True, type="primary"):
                if pwd_input == DASHBOARD_PASSWORD:
                    st.session_state["password_correct"] = True
                    st.rerun() 
                else:
                    st.error("🚫 비밀번호가 일치하지 않습니다.")
        return False
    return True

if not check_password():
    st.stop()

# ==========================================
# 구글 시트 락 시스템 및 통신
# ==========================================
def manage_sheet_lock(action="check", engine_name=""):
    try:
        gc = gspread.service_account(filename="google_key.json")
        doc = gc.open("맞춤공고_DB")
        try:
            ws = doc.worksheet("settings")
        except gspread.exceptions.WorksheetNotFound:
            ws = doc.add_worksheet(title="settings", rows=2, cols=2)
            ws.update(range_name="A1:B1", values=[["free", str(time.time())]])

        if action == "check":
            status = ws.cell(1, 1).value
            timestamp = ws.cell(1, 2).value
            if status == "running":
                if time.time() - float(timestamp) > 900:
                    ws.update(range_name="A1:B1", values=[["free", str(time.time())]])
                    return False
                return True
            return False
        elif action == "lock_and_log":
            ws.update(
                range_name="A1:B2", 
                values=[
                    ["running", str(time.time())],
                    [engine_name, datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")]
                ]
            )
        elif action == "unlock":
            ws.update(range_name="A1:B1", values=[["free", str(time.time())]])
    except:
        return False

@st.cache_data(ttl=60)
def get_recent_log():
    try:
        gc = gspread.service_account(filename="google_key.json")
        doc = gc.open("맞춤공고_DB")
        ws = doc.worksheet("settings")
        eng = ws.cell(2, 1).value
        tm = ws.cell(2, 2).value
        return eng if eng else "기록 없음", tm if tm else "-"
    except:
        return "기록 없음", "-"

if "GOOGLE_CREDENTIALS" in st.secrets:
    with open("google_key.json", "w", encoding="utf-8") as f:
        f.write(st.secrets["GOOGLE_CREDENTIALS"])

@st.cache_data(ttl=600)
def get_google_sheet(sheet_name):
    try:
        gc = gspread.service_account(filename="google_key.json")
        doc = gc.open("맞춤공고_DB")
        worksheet = doc.worksheet(sheet_name)
        data = worksheet.get_all_records()
        return pd.DataFrame(data)
    except:
        return pd.DataFrame()

def update_notice_status(notice_keys_to_mark, status_value):
    try:
        gc = gspread.service_account(filename="google_key.json")
        doc = gc.open("맞춤공고_DB")
        worksheet = doc.worksheet("notices")
        all_records = worksheet.get_all_values()
        if not all_records: return True
        
        headers = all_records[0]
        if "검토유무" not in headers:
            headers.append("검토유무")
            worksheet.update(range_name="1:1", values=[headers])
            review_col_idx = len(headers) - 1
        else:
            review_col_idx = headers.index("검토유무")
            
        key_col_idx = headers.index("notice_key")
        cells_to_update = []
        
        for row_idx, row in enumerate(all_records):
            if row_idx == 0: continue
            if len(row) <= review_col_idx: row.extend([""] * (review_col_idx - len(row) + 1))
            
            if row[key_col_idx] in notice_keys_to_mark:
                cell = gspread.Cell(row=row_idx+1, col=review_col_idx+1, value=status_value)
                cells_to_update.append(cell)
                
        if cells_to_update: worksheet.update_cells(cells_to_update)
        return True
    except:
        return False

# ==========================================
# 테이블 렌더링 헬퍼 함수
# ==========================================
def render_notice_table(df, key_prefix):
    if df.empty:
        st.info("해당되는 공고가 없습니다.")
        return
        
    display_columns = ['notice_key', '출처', '등록일', '공고제목', '특이사항', '검토유무', '상세링크']
    display_df = df[[c for c in display_columns if c in df.columns]].copy()
    display_df.insert(0, '선택', False)
    
    def highlight_row(row):
        status = str(row.get('검토유무', '')).strip()
        if status == '내업무아님': return ['background-color: #8c8c8c; color: #ffffff; text-decoration: line-through;'] * len(row)
        if status == '내업무맞음': return ['background-color: #cce5ff; color: #004080; font-weight: bold;'] * len(row)
        if status == '완료': return ['background-color: #f0f2f6; color: #a0aab2;'] * len(row)
        return [''] * len(row)
        
    styled_df = display_df.style.apply(highlight_row, axis=1)
    disabled_cols = [col for col in display_df.columns if col != '선택']
    
    edited_df = st.data_editor(
        styled_df,
        column_config={"선택": st.column_config.CheckboxColumn("선택", required=True), "상세링크": st.column_config.LinkColumn("상세링크"), "notice_key": None},
        disabled=disabled_cols, hide_index=True, use_container_width=True, key=f"editor_{key_prefix}"
    )
    
    selected_keys = edited_df[edited_df['선택'] == True]['notice_key'].tolist()
    
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("🔵 업무 맞음", key=f"btn1_{key_prefix}", use_container_width=True) and selected_keys:
            if update_notice_status(selected_keys, "내업무맞음"): get_google_sheet.clear(); st.rerun()
    with c2:
        if st.button("⚫ 업무 아님", key=f"btn2_{key_prefix}", use_container_width=True) and selected_keys:
            if update_notice_status(selected_keys, "내업무아님"): get_google_sheet.clear(); st.rerun()
    with c3:
        if st.button("✅ 검토 완료", key=f"btn3_{key_prefix}", use_container_width=True) and selected_keys:
            if update_notice_status(selected_keys, "완료"): get_google_sheet.clear(); st.rerun()
    with c4:
        if st.button("🔄 초기화", key=f"btn4_{key_prefix}", use_container_width=True) and selected_keys:
            if update_notice_status(selected_keys, "미검토"): get_google_sheet.clear(); st.rerun()

# ==========================================
# 사이드바 메뉴 설정
# ==========================================
st.sidebar.title("📌 메뉴 선택")
menu = st.sidebar.radio("이동할 메뉴를 선택하세요:", ["공고 자동수집", "공고 통계", "🎯 타겟 공고", "사이트 검토 필요", "📝 게시판", "🧪 스텔스 랩 (한수원)"])
st.sidebar.divider()

if menu == "공고 자동수집":
    st.title("🚀 공고 자동 수집 & 실시간 검색")
    df = get_google_sheet("notices")
    if not df.empty:
        st.write(f"현재 총 {len(df)}개의 공고가 로드되었습니다. (UI 생략)")

# ==========================================
# 6. 스텔스 테스트 랩 (비동기 Hit & Run 무적 패치 적용)
# ==========================================
elif menu == "🧪 스텔스 랩 (한수원)":
    st.title("🧪 스텔스 봇 침투 테스트 랩")
    
    test_url = st.text_input("타겟 URL", value="https://ebiz.khnp.co.kr/login.do", disabled=True)
    
    if st.button("🚀 침투 시작", type="primary"):
        with st.status("진행 중...", expanded=True) as status:
            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.service import Service
                from selenium.webdriver.chrome.options import Options
                from selenium.webdriver.common.by import By
                from webdriver_manager.chrome import ChromeDriverManager
                import time
                
                chrome_options = Options()
                chrome_options.add_argument("--headless=new") 
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--window-size=1920,1080")
                chrome_options.add_argument("--lang=ko-KR")
                
                # 무한 로딩 원천 차단
                chrome_options.page_load_strategy = 'none' 
                chrome_options.add_argument("--disable-blink-features=AutomationControlled")
                chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
                chrome_options.add_experimental_option('useAutomationExtension', False)
                
                try: service = Service('/usr/bin/chromedriver')
                except: service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=chrome_options)
                
                # 🛑 무적 패치 1: 15초 넘으면 무조건 로딩 끊어버림
                driver.set_page_load_timeout(15)
                
                driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                    "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
                    "acceptLanguage": 'ko-KR,ko;q=0.9'
                })
                
                st.write("접속 시작 (무한 로딩 15초 제한 컷)...")
                try:
                    driver.get(test_url)
                except:
                    pass # 15초 지나서 타임아웃 나도 당황하지 않고 다음 코드로 넘어감!
                
                st.write("백그라운드 렌더링 대기 중 (10초)...")
                time.sleep(10) 
                
                st.write("팝업 제거 시도 (비동기)...")
                # 🛑 무적 패치 2: 팝업 닫기도 setTimeout으로 쏘고 도망감
                js_close_popup = """
                document.querySelectorAll('a, button, span, img').forEach(el => {
                    var t = (el.innerText || '').trim();
                    var a = (el.getAttribute('alt') || '').trim();
                    if(['닫기', '하루동안 열지 않기', 'X', 'close'].includes(t) || ['닫기', 'close'].includes(a)) {
                        setTimeout(function(){ el.click(); }, 10);
                    }
                });
                """
                try: driver.execute_script(js_close_popup); time.sleep(2) 
                except: pass
                
                st.write("입찰공고조회 메뉴 직접 타격 (비동기 Hit & Run)...")
                # 🛑 무적 패치 3: 메뉴 클릭 후 페이지 이동 대기 없이 바로 파이썬으로 복귀!
                js_ultimate_hack = """
                var plusBtns = document.querySelectorAll('a.plus, a.btn_more, a[title*="더보기"]');
                if(plusBtns.length > 0) {
                    setTimeout(function() { plusBtns[0].click(); }, 10);
                    return 'SUCCESS: 더보기 클릭(비동기)';
                }
                var els = document.querySelectorAll('a, span, li, button');
                for(var i=0; i<els.length; i++) {
                    var el = els[i];
                    if((el.innerText || '').replace(/\\s/g, '').indexOf('입찰공고조회') > -1) {
                        var href = el.getAttribute('href');
                        if(href && href.indexOf('javascript:') > -1) { 
                            var jsCode = href.replace('javascript:', '');
                            setTimeout(function() { eval(jsCode); }, 10);
                            return 'SUCCESS: JS 실행(비동기)'; 
                        }
                        setTimeout(function() { el.click(); }, 10);
                        return 'SUCCESS: 직접 클릭(비동기)';
                    }
                }
                return 'NOT_FOUND';
                """
                
                frames = [None] + driver.find_elements(By.TAG_NAME, "iframe") + driver.find_elements(By.TAG_NAME, "frame")
                for frame in frames:
                    try:
                        if frame: driver.switch_to.frame(frame)
                        res = driver.execute_script(js_ultimate_hack)
                        if 'SUCCESS' in res:
                            driver.switch_to.default_content()
                            break
                        driver.switch_to.default_content()
                    except: driver.switch_to.default_content()
                
                st.write("데이터 렌더링 동적 대기 (최대 30초)...")
                
                # 비주얼 스크래퍼 (이건 화면만 읽어오는 거라 에러 안남)
                js_visual_scraper = """
                var els = document.querySelectorAll('td, span, div, a');
                var items = [];
                for(var i=0; i<els.length; i++) {
                    var el = els[i];
                    if(el.children.length === 0) {
                        var txt = el.textContent.trim();
                        if(txt.length > 0) {
                            var rect = el.getBoundingClientRect();
                            if(rect.width > 0 && rect.height > 0) {
                                items.push({text: txt, y: Math.round(rect.top / 10) * 10, x: Math.round(rect.left)});
                            }
                        }
                    }
                }
                var rows = {};
                items.forEach(function(item) {
                    if(!rows[item.y]) rows[item.y] = [];
                    rows[item.y].push(item);
                });
                var result = [];
                for(var y in rows) {
                    rows[y].sort(function(a, b) { return a.x - b.x; });
                    var rowTexts = rows[y].map(function(a) { return a.text; });
                    var uniqueTexts = [...new Set(rowTexts)];
                    result.push(uniqueTexts.join(' | '));
                }
                return result;
                """

                res_list = None
                search_clicked = False
                
                for attempt in range(15):
                    time.sleep(2)
                    driver.execute_script("window.dispatchEvent(new Event('resize'));")
                    
                    frames = [None] + driver.find_elements(By.TAG_NAME, "iframe") + driver.find_elements(By.TAG_NAME, "frame")
                    
                    for frame in frames:
                        try:
                            if frame: driver.switch_to.frame(frame)
                            visual_rows = driver.execute_script(js_visual_scraper)
                            
                            valid_rows = []
                            ignore_words = ['인증서', '비밀번호', '조회된 데이터', '표시할 데이터', '구매운영단위', '결과상태', '입찰방식', '공고일자', 'PC 요구사항', 'Microsoft', '회사정보', '입찰관리', 'English', '고객센터']
                            
                            if visual_rows:
                                for row in visual_rows:
                                    has_notice_num = bool(re.search(r'[A-Z]\d{2}[A-Z]\d{4,}', row))
                                    has_keyword = any(k in row for k in ['전자입찰', '현장입찰', '공고진행', '입찰진행'])
                                    
                                    if len(row) > 30 and row.count('|') >= 4 and not any(w in row for w in ignore_words):
                                        if has_notice_num or has_keyword:
                                            valid_rows.append(row)
                                        
                            if valid_rows:
                                unique_rows = list(dict.fromkeys(valid_rows))
                                res_list = [f"[{i+1}] {txt}" for i, txt in enumerate(unique_rows[:15])]
                                
                            driver.switch_to.default_content()
                            if res_list: break
                        except:
                            driver.switch_to.default_content()
                    
                    if res_list:
                        break 
                        
                    if attempt == 4 and not search_clicked:
                        st.write("조회 지연 감지. '검색' 버튼 강제 클릭 (비동기)...")
                        # 🛑 무적 패치 4: 검색 버튼도 누르고 도망가기
                        js_search_click = """
                        document.querySelectorAll('a, button, span').forEach(el => {
                            if((el.innerText || '').trim() === '검색') {
                                setTimeout(function(){ el.click(); }, 10);
                            }
                        });
                        """
                        for f in frames:
                            try:
                                if f: driver.switch_to.frame(f)
                                driver.execute_script(js_search_click)
                                driver.switch_to.default_content()
                            except: pass
                        search_clicked = True

                st.write("최종 렌더링 화면 캡처 중...")
                try:
                    screenshot = driver.get_screenshot_as_png()
                    st.image(screenshot, caption="최종 확보된 브라우저 화면")
                except Exception as img_e:
                    st.warning(f"스크린샷 캡처 실패: {img_e}")
                
                status.update(label="처리 완료", state="complete", expanded=True)
                
                if res_list:
                    st.success(f"데이터 추출 성공 ({len(res_list)}건)")
                    st.code("\n".join(res_list))
                else:
                    st.error("데이터 추출 실패 (조건에 맞는 공고 없음 또는 로딩 지연)")
                    
            except Exception as e:
                status.update(label="오류", state="error", expanded=True)
                st.error(f"상세 에러: {e}")
            finally:
                if 'driver' in locals() and driver is not None:
                    driver.quit()

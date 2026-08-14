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

# 🌟 한국 표준시(KST) 강제 설정
KST = timezone(timedelta(hours=9))

# 화면 기본 설정
st.set_page_config(page_title="맞춤 공고 수집 대시보드", layout="wide")

# ==========================================
# 🔐 대시보드 보안 자물쇠 설정
# ==========================================
DASHBOARD_PASSWORD = "0804"  

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if not st.session_state["password_correct"]:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🔒 대시보드 보안 접속")
            st.info("이 대시보드는 우리 팀원만 접근할 수 있습니다.\n\n발급받은 비밀번호를 입력해 주세요.")
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
# 🛑 영구 불멸의 '구글 시트' 자물쇠 시스템
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
    except Exception as e:
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

# ==========================================
# ⚡ 데이터 통신 및 상태 업데이트 함수
# ==========================================
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
    except Exception as e:
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
    except Exception as e:
        st.error(f"🚨 알 수 없는 오류 발생: {e}")
        return False

# ==========================================
# 🎨 테이블 렌더링 헬퍼 함수
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
        title_text = str(row.get('공고제목', ''))
        special_text = str(row.get('특이사항', ''))
        
        if status == '내업무아님': return ['background-color: #8c8c8c; color: #ffffff; text-decoration: line-through;'] * len(row)
        if status == '내업무맞음': return ['background-color: #cce5ff; color: #004080; font-weight: bold;'] * len(row)
        if status == '완료': return ['background-color: #f0f2f6; color: #a0aab2;'] * len(row)
        if '안전점검' in title_text or '안전점검' in special_text: return ['background-color: #e6ffe6; color: #006600; font-weight: bold;'] * len(row)
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
        if st.button("🔵 우리의 업무 맞음 (파랑)", key=f"btn1_{key_prefix}", use_container_width=True):
            if selected_keys:
                if update_notice_status(selected_keys, "내업무맞음"): get_google_sheet.clear(); st.rerun()
    with c2:
        if st.button("⚫ 우리의 업무 아님 (진회색)", key=f"btn2_{key_prefix}", use_container_width=True):
            if selected_keys:
                if update_notice_status(selected_keys, "내업무아님"): get_google_sheet.clear(); st.rerun()
    with c3:
        if st.button("✅ 일반 검토 완료 (연회색)", key=f"btn3_{key_prefix}", use_container_width=True):
            if selected_keys:
                if update_notice_status(selected_keys, "완료"): get_google_sheet.clear(); st.rerun()
    with c4:
        if selected_keys:
            with st.popover("🔄 상태 초기화 (미검토)", use_container_width=True):
                if st.button("네, 초기화 실행", key=f"reset_{key_prefix}", use_container_width=True):
                    if update_notice_status(selected_keys, "미검토"): get_google_sheet.clear(); st.rerun()

# ==========================================
# 사이드바 메뉴 설정
# ==========================================
st.sidebar.title("📌 메뉴 선택")
menu = st.sidebar.radio(
    "이동할 메뉴를 선택하세요:",
    ["공고 자동수집", "공고 통계 및 분석", "🎯 타겟 공고 (내 업무)", "사이트 검토 필요(오류/개편)", "📝 게시판 / 메모장", "🧪 스텔스 테스트 랩 (한수원)"]
)
st.sidebar.divider()

# ==========================================
# 1. 공고 자동수집 메뉴 (생략)
# ==========================================
if menu == "공고 자동수집":
    st.title("🚀 공고 자동 수집 & 실시간 검색")
    df = get_google_sheet("notices")
    if not df.empty:
        st.write(f"현재 총 {len(df)}개의 공고가 로드되었습니다. (UI 생략, 기능 유지)")

# ==========================================
# 6. 🧪 스텔스 테스트 랩 (비주얼 좌표 스크래퍼 완결판)
# ==========================================
elif menu == "🧪 스텔스 테스트 랩 (한수원)":
    st.title("🧪 스텔스 봇 침투 테스트 랩")
    st.info("HTML 태그를 맹신하지 않고, 화면상의 X, Y 좌표를 통해 사람의 눈처럼 텍스트를 조합해냅니다.")
    
    test_url = st.text_input("타겟 URL (고정)", value="https://ebiz.khnp.co.kr/login.do", disabled=True)
    
    if st.button("🚀 스텔스 침투 및 엑스레이 촬영 시작", type="primary"):
        with st.status("서버에 스텔스 봇을 투입합니다...", expanded=True) as status:
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
                
                try: service = Service('/usr/bin/chromedriver')
                except: service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=chrome_options)
                
                driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                    "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
                    "acceptLanguage": 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
                })
                
                st.write("🔗 1. 사이트 접속 및 10초 대기 중...")
                driver.get(test_url)
                time.sleep(10) 
                
                st.write("🛡️ 2. 화면을 가리는 팝업 강제 철거 중...")
                js_close_popup = """
                var pop_btns = document.querySelectorAll('a, button, span, img');
                for(var i=0; i<pop_btns.length; i++) {
                    var txt = (pop_btns[i].innerText || '').trim();
                    var alt = (pop_btns[i].getAttribute('alt') || '').trim();
                    if(['닫기', '하루동안 열지 않기', 'X', 'close'].includes(txt) || ['닫기', 'close'].includes(alt)) {
                        pop_btns[i].click();
                    }
                }
                """
                try: driver.execute_script(js_close_popup); time.sleep(1) 
                except: pass
                
                st.write("🖱️ 3. 중앙 '더보기(+)' 또는 '입찰공고조회' 직접 타격 시도 중...")
                js_ultimate_hack = """
                var plusBtns = document.querySelectorAll('a.plus, a.btn_more, a[title*="더보기"]');
                for(var i=0; i<plusBtns.length; i++) {
                    try { plusBtns[i].click(); return 'SUCCESS: 더보기 클릭'; } catch(e){}
                }
                var els = document.querySelectorAll('a, span, li, button');
                for(var i=0; i<els.length; i++) {
                    if((els[i].innerText || '').replace(/\\s/g, '').indexOf('입찰공고조회') > -1) {
                        var href = els[i].getAttribute('href');
                        if(href && href.indexOf('javascript:') > -1) { eval(href.replace('javascript:', '')); return 'SUCCESS: JS 실행'; }
                        els[i].click(); return 'SUCCESS: 직접 클릭';
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
                
                # 🌟 비주얼 좌표 스크래퍼(Visual Scraper) 자바스크립트
                # HTML 태그를 무시하고 렌더링된 요소의 X, Y 좌표를 통해 표를 직접 조립합니다.
                js_visual_scraper = """
                function getVisualGrid() {
                    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
                    var node;
                    var items = [];
                    // 화면에 렌더링된 모든 글자와 픽셀 위치를 가져옵니다.
                    while(node = walker.nextNode()) {
                        var text = node.nodeValue.trim();
                        if(text.length > 0) {
                            var parent = node.parentElement;
                            if(parent) {
                                var rect = parent.getBoundingClientRect();
                                if(rect.width > 0 && rect.height > 0) {
                                    // Y좌표를 10픽셀 단위로 묶어 약간의 높이 차이 보정 (같은 가로줄 인식)
                                    var y = Math.round(rect.top / 10) * 10;
                                    items.push({text: text, y: y, x: Math.round(rect.left)});
                                }
                            }
                        }
                    }
                    // Y좌표(세로 위치)가 동일한 요소들을 그룹화
                    var rows = {};
                    items.forEach(function(item) {
                        if(!rows[item.y]) rows[item.y] = [];
                        rows[item.y].push(item);
                    });
                    // X좌표(가로 위치) 순으로 정렬하여 | 기호로 결합
                    var result = [];
                    for(var y in rows) {
                        rows[y].sort(function(a, b) { return a.x - b.x; });
                        var rowText = rows[y].map(function(a) { return a.text; }).join(' | ');
                        result.push(rowText);
                    }
                    return result;
                }
                return getVisualGrid();
                """

                st.write("⏳ 4. 시각적 데이터 렌더링 동적 대기 (최대 30초)...")
                
                res_list = None
                search_clicked = False
                
                # 최대 15번 (약 30초) 반복하며 시각적 데이터를 감시
                for attempt in range(15):
                    time.sleep(2)
                    driver.execute_script("window.dispatchEvent(new Event('resize'));") # 찌그러짐 방지
                    
                    frames = [None] + driver.find_elements(By.TAG_NAME, "iframe") + driver.find_elements(By.TAG_NAME, "frame")
                    
                    for frame in frames:
                        try:
                            if frame: driver.switch_to.frame(frame)
                            # 파이썬 BeautifulSoup 대신, 자바스크립트로 브라우저 안에서 시각적으로 조립된 결과물을 받아옴
                            visual_rows = driver.execute_script(js_visual_scraper)
                            
                            valid_rows = []
                            ignore_words = ['인증서', '비밀번호', '조회된 데이터', '표시할 데이터', '구매운영단위', '결과상태', '입찰방식', '공고일자', 'PC 요구사항', 'Microsoft']
                            
                            if visual_rows:
                                for row in visual_rows:
                                    # 파이프(|)가 4개 이상 연결되어 있고 30자가 넘는 줄만 '실제 데이터 행'으로 인정
                                    if len(row) > 30 and row.count('|') >= 4 and not any(w in row for w in ignore_words):
                                        valid_rows.append(row)
                                        
                            if valid_rows:
                                # 중복 제거 로직
                                unique_rows = list(dict.fromkeys(valid_rows))
                                res_list = [f"[{i+1}] {txt}" for i, txt in enumerate(unique_rows[:15])]
                                
                            driver.switch_to.default_content()
                            if res_list: break
                        except:
                            driver.switch_to.default_content()
                    
                    if res_list:
                        break 
                        
                    # 4번 돌았는데(약 8초 경과) 데이터가 안 나오면 '검색' 강제 클릭
                    if attempt == 4 and not search_clicked:
                        st.write("🔄 5. 자동 조회가 지연되어 '검색' 버튼을 강제 클릭합니다...")
                        js_search_click = """
                        var btns = document.querySelectorAll('a, button, span');
                        for(var i=0; i<btns.length; i++){
                            var txt = (btns[i].innerText || btns[i].textContent || '').trim();
                            if(txt === '검색') { btns[i].click(); return true; }
                        } return false;
                        """
                        for frame in frames:
                            try:
                                if frame: driver.switch_to.frame(frame)
                                if driver.execute_script(js_search_click):
                                    search_clicked = True
                                    driver.switch_to.default_content()
                                    break
                                driver.switch_to.default_content()
                            except: pass

                st.write("📸 6. 최종 렌더링 및 추출 시점 화면 확보 중...")
                st.image(driver.get_screenshot_as_png(), caption="데이터 로딩 완료 화면 (스피너가 사라졌는지 확인)")
                
                status.update(label="✅ 침투 및 추출 완료!", state="complete", expanded=True)
                
                if res_list:
                    st.success(f"✅ 축하합니다! 비주얼 스크래핑으로 총 {len(res_list)}개의 공고 데이터를 끄집어냈습니다.")
                    st.code("\n".join(res_list))
                else:
                    st.error("❌ 데이터를 찾을 수 없습니다. (검색 조건에 맞는 공고가 실제로 없거나 로딩이 너무 오래 걸립니다.)")
                
            except Exception as e:
                status.update(label="❌ 오류 발생", state="error", expanded=True)
                st.error(f"오류 상세 내용: {e}")
            finally:
                if 'driver' in locals() and driver is not None:
                    driver.quit()

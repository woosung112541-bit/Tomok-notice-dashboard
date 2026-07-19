import streamlit as st
import pandas as pd
import os
from datetime import datetime, timedelta
import io
import subprocess
import sys
import re
import time

# 1. 시스템 기본 설정
st.set_page_config(page_title="공고 자동 수집 시스템", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_PATH = os.path.join(BASE_DIR, '통합_맞춤공고.xlsx')
CHECK_PATH = os.path.join(BASE_DIR, '수동확인_필요목록.xlsx')
MAIN_SCRIPT_PATH = os.path.join(BASE_DIR, 'main.py')

VENV_PYTHON = os.path.join(BASE_DIR, '.venv', 'Scripts', 'python.exe')
if not os.path.exists(VENV_PYTHON):
    VENV_PYTHON = sys.executable 

# 2. 시스템 헤더
st.title("주요 기관 안전/시설 공고 자동 수집 시스템")
st.markdown("**관리부서:** 토목진단부 | **시스템 목적:** 타겟 기관 신규 공고 및 발주 내역 실시간 모니터링")
st.divider()

# ==========================================
# 데이터 수집 컨트롤러
# ==========================================
st.subheader("신규 데이터 수집 설정")
col_set1, col_set2, col_set3 = st.columns([3, 5, 3])

with col_set1:
    scrape_days = st.number_input("수집 대상 기준일 (최근 N일)", min_value=1, max_value=365, value=10)
with col_set2:
    scrape_keywords = st.text_input("필수 포함 키워드 (쉼표로 구분)", value="안전, 모집, 지정, 공고, 용역")
with col_set3:
    st.markdown("<br>", unsafe_allow_html=True) 
    start_button = st.button("설정값 기반 수집 실행", type="primary", use_container_width=True)

if start_button:
    progress_bar = st.progress(0, text="시스템 준비 중...")
    log_box = st.empty() 
    logs = []
    
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    
    try:
        process = subprocess.Popen(
            [VENV_PYTHON, MAIN_SCRIPT_PATH, str(scrape_days), scrape_keywords], 
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8', 
            errors='replace',
            cwd=BASE_DIR,  
            env=env
        )
        
        for line in process.stdout:
            line = line.strip()
            if line:
                logs.append(line)
                log_box.code('\n'.join(logs[-10:]), language='text')
                
                match = re.search(r'\[(\d+)/(\d+)\]', line)
                if match:
                    current = int(match.group(1))
                    total = int(match.group(2))
                    percent = current / total
                    progress_bar.progress(percent, text=f"데이터 처리 진행 중... ({current}/{total})")
                    
        process.wait() 
        
        if "[종료]" in "".join(logs[-5:]) or "신규 데이터가 없습니다" in "".join(logs[-5:]):
            progress_bar.progress(1.0, text="데이터 수집 완료")
            st.success("데이터 처리가 정상적으로 완료되었습니다. 3초 후 화면이 갱신됩니다.")
            time.sleep(3) 
            st.rerun() 
        else:
            st.error("오류 발생: 데이터 수집이 비정상적으로 종료되었습니다. 시스템 로그를 확인해 주십시오.")
            
    except Exception as e:
        st.error(f"시스템 실행 오류: {e}")

st.divider()

# ==========================================
# 데이터 필터링(사이드바)
# ==========================================
st.sidebar.header("수집 데이터 상세 검색")
search_keyword = st.sidebar.text_input("키워드 검색 (결과 내)", placeholder="예: 용역, 보수")

default_start = datetime.today() - timedelta(days=14)
default_end = datetime.today()
date_range = st.sidebar.date_input("공고 등록일 기간 설정", value=(default_start, default_end))

# ==========================================
# 결과 출력 패널 (Tabs)
# ==========================================
tab1, tab2 = st.tabs(["데이터 수집 결과", "수동 점검 필요 기관"])

# --- [Tab 1] 성공 데이터 ---
with tab1:
    if os.path.exists(FILE_PATH):
        df = pd.read_excel(FILE_PATH)
        df['등록일_날짜'] = pd.to_datetime(df['등록일'], format='%Y.%m.%d', errors='coerce')
        
        filtered_df = df.copy()
        
        if search_keyword:
            filtered_df = filtered_df[filtered_df['공고제목'].str.contains(search_keyword, na=False)]
            
        if len(date_range) == 2:
            start_date = pd.to_datetime(date_range[0])
            end_date = pd.to_datetime(date_range[1])
            filtered_df = filtered_df[(filtered_df['등록일_날짜'] >= start_date) & (filtered_df['등록일_날짜'] <= end_date)]
        
        filtered_df = filtered_df.drop(columns=['등록일_날짜'])

        st.subheader(f"조회 결과: 총 {len(filtered_df)}건")
        
        if len(filtered_df) > 0:
            st.dataframe(
                filtered_df, 
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "상세링크": st.column_config.LinkColumn("원문 링크 (클릭하여 이동)")
                }
            )
            
            st.divider()
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                filtered_df.to_excel(writer, index=False, sheet_name='검색결과')
                
            st.download_button(
                label="현재 조회된 데이터 엑셀 다운로드",
                data=buffer.getvalue(),
                file_name=f"수집결과_보고용_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("설정된 조건에 부합하는 데이터가 존재하지 않습니다.")
    else:
        st.info("수집된 데이터 파일이 존재하지 않습니다. 상단의 '수집 실행' 버튼을 클릭해 주십시오.")

# --- [Tab 2] 수동 확인 데이터 ---
with tab2:
    st.subheader("수동 점검 대상 기관 내역")
    st.markdown("조건에 부합하는 데이터가 없거나, 접근 방식이 특이하여 별도의 수동 점검이 요구되는 기관 목록입니다.")
    
    if os.path.exists(CHECK_PATH):
        df_check = pd.read_excel(CHECK_PATH)
        
        if len(df_check) > 0:
            st.dataframe(
                df_check,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "게시판_URL": st.column_config.LinkColumn("대상 기관 주소 (클릭하여 이동)")
                }
            )
        else:
            st.success("전체 대상 기관의 데이터 수집이 정상적으로 완료되었습니다. (예외 건 없음)")
    else:
        st.info("현재 생성된 점검 목록이 없습니다.")
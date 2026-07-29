import streamlit as st
import pandas as pd
import os
import subprocess
import sys
import gspread

st.set_page_config(page_title="맞춤 공고 수집 대시보드", layout="wide")

if "GOOGLE_CREDENTIALS" in st.secrets:
    with open("google_key.json", "w", encoding="utf-8") as f:
        f.write(st.secrets["GOOGLE_CREDENTIALS"])

def get_google_sheet(sheet_name):
    try:
        gc = gspread.service_account(filename="google_key.json")
        doc = gc.open("맞춤공고_DB")
        worksheet = doc.worksheet(sheet_name)
        data = worksheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        return pd.DataFrame()

# ==========================================
st.sidebar.title("📌 메뉴 선택")
menu = st.sidebar.radio(
    "이동할 메뉴를 선택하세요:",
    ["🚀 공고 자동 수집 (구글시트)", "🏛️ 공고 수집 성공 기관", "⚠️ 추가검토 필요 기관 (미수집)"]
)
st.sidebar.divider()

if menu == "🚀 공고 자동 수집 (구글시트)":
    st.title("🚀 공고 자동 수집 & 실시간 검색 (특이사항 스캔)")
    st.info("💡 공고 상세페이지 및 첨부파일을 스캔하여 [지역제한, 면허] 등의 특이사항을 자동으로 잡아냅니다!")
    
    col1, col2 = st.columns([1, 2])
    with col1: collect_days = st.number_input("📅 수집 기간 (최근 며칠간?)", min_value=1, max_value=365, value=15, step=1)
    with col2: collect_keywords = st.text_input("🔑 수집 키워드 (쉼표 구분)", value="안전, 모집, 지정, 공고, 용역")

    engine_choice = st.radio("⚙️ 수집 엔진 선택", ["⚡ 초고속 순정 모드 (권장: 특이사항 딥스캔 탑재)", "🔬 정밀 튜닝 모드 (셀레니움)"])

    if st.button("🚀 지금 즉시 공고 수집 실행", type="primary"):
        target_script = "main_pure.py" if "순정" in engine_choice else "main.py"
        with st.status(f"🚀 [{target_script}] 로봇 출동! 데이터를 수집 중입니다...", expanded=True) as status:
            try:
                process = subprocess.Popen(
                    [sys.executable, "-u", target_script, str(collect_days), collect_keywords],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', bufsize=1
                )
                for line in iter(process.stdout.readline, ''):
                    if line: st.write(line.strip())
                process.wait()

                if process.returncode == 0:
                    status.update(label="✅ 공고 수집 완료!", state="complete", expanded=False)
                    st.success("특이사항 분석 및 수집이 완료되었습니다.")
                else:
                    status.update(label="❌ 수집 실패", state="error", expanded=True)
            except Exception as e:
                status.update(label="❌ 시스템 오류", state="error", expanded=True)
        st.rerun()

    st.divider()

    df = get_google_sheet("notices")

    if not df.empty:
        if '공고제목' not in df.columns or '출처' not in df.columns:
            st.error("🚨 구글 시트 1행 이름표 오류! [출처, 등록일, 공고제목, 상세링크, notice_key, created_at, 특이사항] 순서인지 확인해주세요.")
        else:
            st.sidebar.subheader("🔍 공고 실시간 검색")
            search_keyword = st.sidebar.text_input("공고제목 / 키워드 검색", "")
            search_org = st.sidebar.text_input("발주기관(출처) 검색", "")
            date_range = st.sidebar.date_input("등록일자 범위 지정", [])

            filtered_df = df.copy()
            if search_keyword: filtered_df = filtered_df[filtered_df['공고제목'].astype(str).str.contains(search_keyword, case=False, na=False)]
            if search_org: filtered_df = filtered_df[filtered_df['출처'].astype(str).str.contains(search_org, case=False, na=False)]
            if len(date_range) == 2:
                start_date, end_date = date_range[0], date_range[1]
                parsed_dates = pd.to_datetime(filtered_df['등록일'].astype(str).str.replace('.', '-'), errors='coerce').dt.date
                filtered_df = filtered_df[(parsed_dates >= start_date) & (parsed_dates <= end_date)]

            st.subheader(f"📋 누적 공고 (검색 결과: {len(filtered_df)}건 / 전체: {len(df)}건)")
            
            # 🌟 표 화면 정리 (내부용 시스템 키인 notice_key와 created_at은 숨기고 핵심만 보여줌)
            display_columns = ['출처', '등록일', '공고제목', '특이사항', '상세링크']
            display_df = filtered_df[[c for c in display_columns if c in filtered_df.columns]]
            
            st.dataframe(display_df, column_config={"상세링크": st.column_config.LinkColumn("상세링크")}, use_container_width=True)
    else:
        st.info("아직 구글 시트에 수집된 데이터가 없거나, 시트가 비어있습니다.")

elif menu == "🏛️ 공고 수집 성공 기관":
    st.title("🏛️ 공고 수집 성공 기관 목록")
    df_orgs = get_google_sheet("collected_orgs")
    if not df_orgs.empty and 'org_name' in df_orgs.columns:
        for org in df_orgs['org_name'].dropna():
            if str(org).strip(): st.write(f"- ✅ **{org}**")

elif menu == "⚠️ 추가검토 필요 기관 (미수집)":
    st.title("⚠️ 추가검토 필요 기관 목록")
    df_empty = get_google_sheet("empty_orgs")
    if not df_empty.empty:
        st.dataframe(df_empty, use_container_width=True)

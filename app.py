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
    [
        "🚀 공고 자동 수집 (구글시트)", 
        "📊 공고 통계 및 분석 (참고용)",
        "🏛️ 공고 수집 성공 기관", 
        "⚠️ 추가검토 필요 기관 (미수집)"
    ]
)
st.sidebar.divider()

# ==========================================
# 1. 🚀 공고 자동 수집 메뉴
# ==========================================
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
            display_columns = ['출처', '등록일', '공고제목', '특이사항', '상세링크']
            display_df = filtered_df[[c for c in display_columns if c in filtered_df.columns]]
            st.dataframe(display_df, column_config={"상세링크": st.column_config.LinkColumn("상세링크")}, use_container_width=True)
    else:
        st.info("아직 구글 시트에 수집된 데이터가 없거나, 시트가 비어있습니다.")

# ==========================================
# 🌟 2. 📊 공고 통계 및 분석 메뉴
# ==========================================
elif menu == "📊 공고 통계 및 분석 (참고용)":
    st.title("📊 공고 통계 및 분석 대시보드")
    st.info("수집된 데이터(구글 시트)를 바탕으로 우리 타겟 시장의 발주 흐름을 가볍게 파악해 보세요.")

    df = get_google_sheet("notices")

    if not df.empty and '공고제목' in df.columns:
        total_notices = len(df)
        total_orgs = df['출처'].nunique()
        
        col1, col2, col3 = st.columns(3)
        col1.metric("총 누적 수집 공고", f"{total_notices} 건")
        col2.metric("공고 발주 기관 수", f"{total_orgs} 곳")
        
        if '등록일' in df.columns:
            parsed_dates = pd.to_datetime(df['등록일'].astype(str).str.replace('.', '-'), errors='coerce').dropna()
            if not parsed_dates.empty:
                latest_date = parsed_dates.max().strftime('%Y-%m-%d')
                col3.metric("마지막 발주(등록) 일자", latest_date)

        st.divider()

        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            st.subheader("🏆 공고 최다 발주처 Top 10")
            org_counts = df['출처'].value_counts().head(10)
            st.bar_chart(org_counts)

        with chart_col2:
            if '특이사항' in df.columns:
                st.subheader("🔥 주요 특이사항 발생 빈도")
                
                # 🌟 [개선점] '아무런 특이사항 없음(-)' 및 빈칸을 완벽하게 걸러내는 필터
                ignore_words = ['-', 'nan', 'none', '', '없음']
                valid_specials = df['특이사항'].astype(str).str.strip()
                
                # '-' 기호나 'nan'이 아닌 진짜 데이터만 추출
                special_df = df[~valid_specials.str.lower().isin(ignore_words)]
                
                if not special_df.empty:
                    # '🔥' 기호를 제거하고 쉼표로 분리
                    specials_list = special_df['특이사항'].astype(str).str.replace('🔥', '').str.split(',')
                    # 리스트를 평탄화하면서 공백 및 빈문자열 한번 더 제거
                    all_specials = [item.strip() for sublist in specials_list if isinstance(sublist, list) for item in sublist if item.strip() and item.strip().lower() not in ignore_words]
                    
                    if all_specials:
                        special_counts = pd.Series(all_specials).value_counts().head(10)
                        st.bar_chart(special_counts)
                    else:
                        st.write("유의미한 특이사항 데이터가 없습니다.")
                else:
                    st.write("유의미한 특이사항 데이터가 없습니다.")

        st.subheader("📈 최근 일별 공고 발주 추이")
        if '등록일' in df.columns and not parsed_dates.empty:
            df['날짜포맷'] = parsed_dates
            date_counts = df['날짜포맷'].value_counts().sort_index()
            recent_date_counts = date_counts.tail(30)
            st.line_chart(recent_date_counts)

    else:
        st.warning("아직 분석할 데이터가 없습니다. 메인 탭에서 공고를 먼저 수집해 주세요!")

# ==========================================
# 3. 기관 목록 메뉴
# ==========================================
elif menu == "🏛️ 공고 수집 성공 기관":
    st.title("🏛️ 공고 수집 성공 기관 목록")
    df_orgs = get_google_sheet("collected_orgs")
    if not df_orgs.empty and 'org_name' in df_orgs.columns:
        for org in df_orgs['org_name'].dropna():
            if str(org).strip(): st.write(f"- ✅ **{org}**")

# ==========================================
# 4. 검토 필요 기관 메뉴
# ==========================================
elif menu == "⚠️ 추가검토 필요 기관 (미수집)":
    st.title("⚠️ 추가검토 필요 기관 목록")
    df_empty = get_google_sheet("empty_orgs")
    if not df_empty.empty:
        st.dataframe(df_empty, use_container_width=True)

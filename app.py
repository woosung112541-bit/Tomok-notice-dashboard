import streamlit as st
import pandas as pd
import os
import subprocess
import sys
import gspread

# 화면 기본 설정이 무조건 가장 먼저 와야 합니다!
st.set_page_config(page_title="맞춤 공고 수집 대시보드", layout="wide")

# ==========================================
# 🔐 [신규] 대시보드 철통 보안 자물쇠 설정
# ==========================================
DASHBOARD_PASSWORD = "0804"  # 👈 여기에 설정하신 비밀번호가 들어갑니다.

def check_password():
    """비밀번호 검증 로직"""
    # 세션 상태에 'password_correct' 기록이 없으면 False로 초기화
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    # 비밀번호가 아직 틀렸거나 입력 전이라면 로그인 창 표시
    if not st.session_state["password_correct"]:
        # 중앙 정렬을 위해 빈 컬럼 사용
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🔒 대시보드 보안 접속")
            st.info("이 대시보드는 우리 팀원만 접근할 수 있습니다.\n\n발급받은 비밀번호를 입력해 주세요.")
            
            pwd_input = st.text_input("🔑 비밀번호 입력", type="password")
            
            if st.button("🚀 접속하기", use_container_width=True, type="primary"):
                if pwd_input == DASHBOARD_PASSWORD:
                    st.session_state["password_correct"] = True
                    st.rerun()  # 로그인 성공 시 화면 새로고침하여 본 화면으로 진입
                else:
                    st.error("🚫 비밀번호가 일치하지 않습니다.")
        return False
    
    # 비밀번호가 맞으면 True 반환
    return True

# 🚨 비밀번호를 통과하지 못하면 밑에 있는 코드는 절대 실행되지 않음! (접속 차단)
if not check_password():
    st.stop()

# ==========================================
# 🌟 여기서부터는 로그인 성공 시 보여지는 '진짜 대시보드' 화면입니다.
# ==========================================

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
        "🚨 사이트 건강 진단 (오류/개편)"
    ]
)
st.sidebar.divider()

# ==========================================
# 1. 🚀 공고 자동 수집 메뉴
# ==========================================
if menu == "🚀 공고 자동 수집 (구글시트)":
    st.title("🚀 공고 자동 수집 & 실시간 검색")
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
                else:
                    status.update(label="❌ 수집 실패", state="error", expanded=True)
            except Exception as e:
                status.update(label="❌ 시스템 오류", state="error", expanded=True)
        st.rerun()

    st.divider()

    df = get_google_sheet("notices")
    if not df.empty and '공고제목' in df.columns:
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
# 2. 📊 공고 통계 메뉴
# ==========================================
elif menu == "📊 공고 통계 및 분석 (참고용)":
    st.title("📊 공고 통계 및 분석 대시보드")
    df = get_google_sheet("notices")
    if not df.empty and '공고제목' in df.columns:
        col1, col2, col3 = st.columns(3)
        col1.metric("총 누적 수집 공고", f"{len(df)} 건")
        col2.metric("공고 발주 기관 수", f"{df['출처'].nunique()} 곳")
        if '등록일' in df.columns:
            parsed_dates = pd.to_datetime(df['등록일'].astype(str).str.replace('.', '-'), errors='coerce').dropna()
            if not parsed_dates.empty: col3.metric("마지막 발주(등록) 일자", parsed_dates.max().strftime('%Y-%m-%d'))

        st.divider()
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.subheader("🏆 최다 발주처 Top 10")
            st.bar_chart(df['출처'].value_counts().head(10))
        with chart_col2:
            if '특이사항' in df.columns:
                st.subheader("🔥 주요 특이사항 발생 빈도")
                ignore_words = ['-', 'nan', 'none', '', '없음']
                valid_specials = df['특이사항'].astype(str).str.strip()
                special_df = df[~valid_specials.str.lower().isin(ignore_words)]
                if not special_df.empty:
                    specials_list = special_df['특이사항'].astype(str).str.replace('🔥', '').str.split(',')
                    all_specials = [item.strip() for sublist in specials_list if isinstance(sublist, list) for item in sublist if item.strip() and item.strip().lower() not in ignore_words]
                    if all_specials: st.bar_chart(pd.Series(all_specials).value_counts().head(10))
        
        st.subheader("📈 최근 일별 공고 발주 추이")
        if '등록일' in df.columns and not parsed_dates.empty:
            df['날짜포맷'] = parsed_dates
            date_counts = df['날짜포맷'].value_counts().sort_index()
            recent_date_counts = date_counts.tail(30)
            st.line_chart(recent_date_counts)

# ==========================================
# 3. 🏛️ 성공 기관 메뉴
# ==========================================
elif menu == "🏛️ 공고 수집 성공 기관":
    st.title("🏛️ 공고 수집 성공 기관 목록")
    df_orgs = get_google_sheet("collected_orgs")
    if not df_orgs.empty and 'org_name' in df_orgs.columns:
        for org in df_orgs['org_name'].dropna():
            if str(org).strip(): st.write(f"- ✅ **{org}**")

# ==========================================
# 4. 🚨 사이트 건강 진단 (Health Check) 메뉴
# ==========================================
elif menu == "🚨 사이트 건강 진단 (오류/개편)":
    st.title("🚨 사이트 건강 진단 (Health Check)")
    st.info("홈페이지가 개편되어 주소가 바뀌었거나, 서버가 죽은 기관을 로봇이 스스로 찾아냅니다.")
    
    df_empty = get_google_sheet("empty_orgs")
    if not df_empty.empty and '분류' in df_empty.columns:
        error_df = df_empty[df_empty['분류'] != '공고 없음']
        empty_df = df_empty[df_empty['분류'] == '공고 없음']
        
        if not error_df.empty:
            st.error(f"⚠️ 비상! 아래 {len(error_df)}개 기관은 홈페이지 주소가 바뀌었거나 서버가 죽은 것 같습니다. 엑셀에서 URL을 수정해 주세요!")
            st.dataframe(error_df, use_container_width=True)
        else:
            st.success("✅ 현재 홈페이지가 폭파되거나 주소가 변경된 기관은 없습니다!")
            
        st.divider()
        st.write(f"💡 사이트는 정상인데 단순히 새 공고가 없는 기관: **{len(empty_df)}곳**")
        with st.expander("단순 공고 없음 기관 목록 보기"):
            st.dataframe(empty_df, use_container_width=True)
    else:
        st.success("점검 기록이 없습니다. 먼저 공고 수집을 실행해 주세요!")

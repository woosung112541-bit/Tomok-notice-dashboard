import streamlit as st
import pandas as pd
import os
import subprocess
import sys
import gspread

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
# 사이드바 메뉴 설정 (요청 반영)
# ==========================================
st.sidebar.title("📌 메뉴 선택")
menu = st.sidebar.radio(
    "이동할 메뉴를 선택하세요:",
    [
        "공고 자동수집", 
        "공고 통계 및 분석",
        "공고수집성공기관", 
        "사이트 검토 필요(오류/개편)"
    ]
)
st.sidebar.divider()

# 하이퍼링크 바로가기 버튼 추가
st.sidebar.subheader("🔗 주요 사이트 바로가기")
st.sidebar.link_button("🏛️ 한국시설안전협회", "http://www.assi.or.kr/sub/board/gongji.asp?boardname=gongji")
st.sidebar.link_button("📑 조달청 통합명부", "https://www.pps.go.kr/kor/bbs/list.do?key=00641")
st.sidebar.link_button("🏗️ 아이건설넷", "https://www.igunsul.net/")
st.sidebar.link_button("🛒 나라장터", "https://www.g2b.go.kr/index.jsp")
st.sidebar.divider()

# ==========================================
# 1. 공고 자동수집 메뉴
# ==========================================
if menu == "공고 자동수집":
    st.title("🚀 공고 자동 수집 & 실시간 검색")
    col1, col2 = st.columns([1, 2])
    with col1: 
        # 1번 요청 반영: 0입력 시 당일만 수집 문구 및 min_value=0 설정
        collect_days = st.number_input("수집 기간 (0입력 시, 당일만 수집)", min_value=0, max_value=365, value=0, step=1)
    with col2: 
        collect_keywords = st.text_input("🔑 수집 키워드 (쉼표 구분)", value="안전, 모집, 지정, 공고, 용역")

    # 2번 요청 반영: 엔진 이름 변경
    engine_choice = st.radio("⚙️ 수집 엔진 선택", ["빠른 탐색(열람가능 사이트)", "정밀 탐색(셀레니움)"])

    # 3번 요청 반영: 버튼 이름 변경
    if st.button("공고 수집", type="primary"):
        target_script = "main_pure.py" if "빠른 탐색" in engine_choice else "main.py"
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
# 2. 공고 통계 및 분석 메뉴 (레이아웃 변경 반영)
# ==========================================
elif menu == "공고 통계 및 분석":
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
        
        # 4번 요청 반영: 좌측 상단 지역별 추이/분류, 우측 하단 최다 발주처 Top 10
        top_col1, top_col2 = st.columns(2)
        with top_col1:
            st.subheader("🗺️ 지역별 공고 현황 및 추이")
            if '특이사항' in df.columns:
                region_df = df[df['특이사항'].str.contains("지역제한", na=False)]
                if not region_df.empty:
                    st.bar_chart(region_df['출처'].value_counts().head(5))
                else:
                    st.info("지역별 분류 데이터를 시각화하는 영역입니다.")
            else:
                st.info("지역별 분류 데이터를 시각화하는 영역입니다.")
        with top_col2:
            st.write("") # 빈 공간

        st.divider()
        
        bottom_col1, bottom_col2 = st.columns(2)
        with bottom_col1:
            st.write("") # 빈 공간
        with bottom_col2:
            st.subheader("🏆 최다 발주처 Top 10")
            st.bar_chart(df['출처'].value_counts().head(10))
    else:
        st.info("통계를 표시할 데이터가 부족합니다.")

# ==========================================
# 3. 공고수집성공기관 메뉴 (하얀 화면 오류 방지)
# ==========================================
elif menu == "공고수집성공기관":
    st.title("🏛️ 공고 수집 성공 기관 목록")
    try:
        df_orgs = get_google_sheet("collected_orgs")
        if not df_orgs.empty and 'org_name' in df_orgs.columns:
            org_list = df_orgs['org_name'].dropna().tolist()
            if org_list:
                for org in org_list:
                    st.write(f"- ✅ **{org}**")
            else:
                st.info("수집 성공한 기관 목록이 비어 있습니다.")
        else:
            st.warning("아직 수집된 성공 기관 데이터가 없습니다. 공고 수집을 먼저 실행해 주세요.")
    except Exception as e:
        st.error("데이터를 불러오는 중 오류가 발생했습니다. 수집을 먼저 실행해 주세요.")

# ==========================================
# 4. 사이트 검토 필요(오류/개편) 메뉴 (멘트 변경 반영)
# ==========================================
elif menu == "사이트 검토 필요(오류/개편)":
    st.title("🚨 사이트 검토 필요 (오류/개편)")
    st.info("홈페이지가 개편되어 주소가 바뀌었거나, 서버가 죽은 기관을 로봇이 스스로 찾아냅니다.")
    
    try:
        df_empty = get_google_sheet("empty_orgs")
        if not df_empty.empty and '분류' in df_empty.columns:
            error_df = df_empty[df_empty['분류'] != '공고 없음']
            empty_df = df_empty[df_empty['분류'] == '공고 없음']
            
            error_count = len(error_df)
            # 4번 요청 반영: 안내 멘트 수정
            st.error(f"**아래 {error_count}개 기관의 수동 검토가 필요합니다. 분류를 참고하여 검토해주세요.**")
            
            if not error_df.empty:
                st.dataframe(error_df, use_container_width=True)
            else:
                st.success("✅ 현재 홈페이지가 폭파되거나 주소가 변경된 기관은 없습니다!")
                
            st.divider()
            st.write(f"💡 사이트는 정상인데 단순히 새 공고가 없는 기관: **{len(empty_df)}곳**")
            with st.expander("단순 공고 없음 기관 목록 보기"):
                st.dataframe(empty_df, use_container_width=True)
        else:
            st.success("점검 기록이 없습니다. 먼저 공고 수집을 실행해 주세요!")
    except Exception as e:
        st.error("점검 데이터를 불러오는 중 오류가 발생했습니다.")

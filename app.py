import streamlit as st
import pandas as pd
import sqlite3
import os
import subprocess
import sys

st.set_page_config(page_title="맞춤 공고 수집 대시보드", layout="wide")

DB_PATH = "notices.db"

# DB 연결 및 데이터 로드 도우미 함수
def load_data_from_db(query):
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# ==========================================
# 👈 [좌측 사이드바: 메뉴 선택 & 검색 필터]
# ==========================================
st.sidebar.title("📌 메뉴 선택")
menu = st.sidebar.radio(
    "이동할 메뉴를 선택하세요:",
    ["🚀 공고 자동 수집 (DB버전)", "🏛️ 공고 수집 성공 기관", "⚠️ 추가검토 필요 기관 (미수집)"]
)
st.sidebar.divider()

# ==========================================
# --- 1번 메뉴: 🚀 공고 자동 수집 ---
# ==========================================
if menu == "🚀 공고 자동 수집 (DB버전)":
    st.title("🚀 공고 자동 수집 & 실시간 검색")
    
    st.info("💡 아래에서 수집을 원하는 기간과 키워드를 지정하고, 사용할 엔진을 선택하세요.")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        collect_days = st.number_input("📅 수집 기간 (최근 며칠간?)", min_value=1, max_value=365, value=15, step=1)
    with col2:
        collect_keywords = st.text_input("🔑 수집 키워드 (쉼표 구분)", value="안전, 모집, 지정, 공고, 용역")

    engine_choice = st.radio(
        "⚙️ 수집 엔진 선택",
        ["⚡ 초고속 순정 모드 (권장: 4분 이내, DB 저장 됨)", "🔬 정밀 튜닝 모드 (셀레니움 탑재: 기존 엑셀 방식 작동)"]
    )

    if st.button("🚀 지금 즉시 공고 수집 실행", type="primary"):
        target_script = "main_pure.py" if "순정" in engine_choice else "main.py"
        
        with st.status(f"🚀 [{target_script}] 로봇 출동! 데이터를 수집 중입니다...", expanded=True) as status:
            try:
                process = subprocess.Popen(
                    [sys.executable, "-u", target_script, str(collect_days), collect_keywords],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    bufsize=1
                )
                for line in iter(process.stdout.readline, ''):
                    if line:
                        st.write(line.strip())
                process.wait()

                if process.returncode == 0:
                    status.update(label="✅ 공고 수집 완료!", state="complete", expanded=False)
                    st.success(f"수집이 성공적으로 마무리되었습니다. ({target_script} 실행 완료)")
                else:
                    status.update(label="❌ 수집 실패 (오류 발생)", state="error", expanded=True)
                    st.error("수집 도중 오류가 발생했습니다.")
            except Exception as e:
                status.update(label="❌ 실행 시스템 오류", state="error", expanded=True)
                st.error(f"실행 중 예외 발생: {e}")
        
        st.rerun()

    st.divider()

    # 🌟 [DB에서 공고 데이터 불러오기]
    df = load_data_from_db("SELECT org_name AS 출처, post_date AS 등록일, title AS 공고제목, link AS 상세링크 FROM notices ORDER BY post_date DESC")

    if not df.empty:
        st.sidebar.subheader("🔍 공고 실시간 검색")
        search_keyword = st.sidebar.text_input("공고제목 / 키워드 검색", "")
        search_org = st.sidebar.text_input("발주기관(출처) 검색", "")
        date_range = st.sidebar.date_input("등록일자 범위 지정", [])

        filtered_df = df.copy()
        
        if search_keyword:
            filtered_df = filtered_df[filtered_df['공고제목'].astype(str).str.contains(search_keyword, case=False, na=False)]
        if search_org:
            filtered_df = filtered_df[filtered_df['출처'].astype(str).str.contains(search_org, case=False, na=False)]
        if len(date_range) == 2:
            start_date, end_date = date_range[0], date_range[1]
            parsed_dates = pd.to_datetime(filtered_df['등록일'].astype(str).str.replace('.', '-'), errors='coerce').dt.date
            filtered_df = filtered_df[(parsed_dates >= start_date) & (parsed_dates <= end_date)]

        st.subheader(f"📋 누적된 맞춤 공고 목록 (검색 결과: {len(filtered_df)}건 / 전체: {len(df)}건)")

        st.dataframe(
            filtered_df,
            column_config={"상세링크": st.column_config.LinkColumn("상세링크")},
            use_container_width=True
        )
    else:
        st.info("아직 수집된 DB 결과가 없습니다. 상단의 버튼을 눌러 수집을 시작해 보세요!")

# ==========================================
# --- 2번 메뉴: 🏛️ 공고 수집 성공 기관 ---
# ==========================================
elif menu == "🏛️ 공고 수집 성공 기관":
    st.title("🏛️ 공고 수집 성공 기관 목록")
    st.caption("DB에 기록된 성공 검증 기관입니다.")

    df_orgs = load_data_from_db("SELECT org_name FROM collected_orgs")
    if not df_orgs.empty:
        st.write(f"현재 총 **{len(df_orgs)}개** 기관에서 공고를 성공적으로 발굴했습니다:")
        for org in df_orgs['org_name']:
            st.write(f"- ✅ **{org}**")
    else:
        st.info("아직 공고 수집에 성공한 기관 기록이 없습니다.")

# ==========================================
# --- 3번 메뉴: ⚠️ 추가검토 필요 기관 ---
# ==========================================
elif menu == "⚠️ 추가검토 필요 기관 (미수집)":
    st.title("⚠️ 추가검토 필요 기관 목록")
    st.caption("※ 여태껏 단 한 번도 공고가 수집된 적 없는 기관들만 모아둔 목록입니다.")

    df_empty = load_data_from_db("SELECT org_name AS 출처기관, url AS 게시판_URL, status AS 분류 FROM empty_orgs")
    if not df_empty.empty:
        st.dataframe(df_empty, use_container_width=True)
    else:
        st.success("🎉 현재 미수집 기관이 없거나, 확인 목록이 비어있습니다!")

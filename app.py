import streamlit as st
import pandas as pd
import os
import subprocess
import sys
import gspread

st.set_page_config(page_title="맞춤 공고 수집 대시보드", layout="wide")

# 🌟 [보안] 스트림릿 금고에서 구글 마스터키를 꺼내 임시 파일로 만듦
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
        st.error(f"구글 시트 연동 오류: {e}")
        return pd.DataFrame()

# ==========================================
st.sidebar.title("📌 메뉴 선택")
menu = st.sidebar.radio(
    "이동할 메뉴를 선택하세요:",
    ["🚀 공고 자동 수집 (구글시트)", "🏛️ 공고 수집 성공 기관", "⚠️ 추가검토 필요 기관 (미수집)"]
)
st.sidebar.divider()

if menu == "🚀 공고 자동 수집 (구글시트)":
    st.title("🚀 공고 자동 수집 & 실시간 검색 (영구보존)")
    st.info("💡 수집된 데이터는 구글 드라이브의 [맞춤공고_DB] 시트에 안전하게 영구 보존됩니다!")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        collect_days = st.number_input("📅 수집 기간 (최근 며칠간?)", min_value=1, max_value=365, value=15, step=1)
    with col2:
        collect_keywords = st.text_input("🔑 수집 키워드 (쉼표 구분)", value="안전, 모집, 지정, 공고, 용역")

    engine_choice = st.radio(
        "⚙️ 수집 엔진 선택",
        ["⚡ 초고속 순정 모드 (권장: 4분 이내, 구글시트 연동 완료)", "🔬 정밀 튜닝 모드 (셀레니움 탑재: 기존 엑셀 방식 작동)"]
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
                    status.update(label="❌ 수집 실패", state="error", expanded=True)
            except Exception as e:
                status.update(label="❌ 시스템 오류", state="error", expanded=True)
                st.error(f"오류: {e}")
        st.rerun()

    st.divider()

    # 구글 시트에서 데이터 불러오기
    df = get_google_sheet("notices")

    if not df.empty:
        # 🛡️ [안전장치] 구글 시트 1행(헤더)이 엉망일 경우를 대비한 방어 코드
        if '공고제목' not in df.columns or '출처' not in df.columns:
            st.error("🚨 구글 시트의 첫 번째 줄(이름표)이 잘못되었습니다!\n\n구글 시트를 열고 1행이 **[출처, 등록일, 공고제목, 상세링크, notice_key, created_at]** 로 적혀있는지 확인해 주세요. (1행이 비어있다면 행 삭제 필요)")
            st.dataframe(df.head()) # 현재 잘못 인식된 표를 보여줌
        else:
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

            st.subheader(f"📋 구글 시트 누적 공고 (검색 결과: {len(filtered_df)}건 / 전체: {len(df)}건)")
            st.dataframe(filtered_df, column_config={"상세링크": st.column_config.LinkColumn("상세링크")}, use_container_width=True)
    else:
        st.info("아직 구글 시트에 수집된 데이터가 없거나, 시트가 비어있습니다.")

elif menu == "🏛️ 공고 수집 성공 기관":
    st.title("🏛️ 공고 수집 성공 기관 목록")
    df_orgs = get_google_sheet("collected_orgs")
    if not df_orgs.empty and 'org_name' in df_orgs.columns:
        st.write(f"현재 총 **{len(df_orgs)}개** 기관에서 발굴 성공:")
        for org in df_orgs['org_name'].dropna():
            if str(org).strip(): 
                st.write(f"- ✅ **{org}**")
    else:
        st.info("기록이 없습니다.")

elif menu == "⚠️ 추가검토 필요 기관 (미수집)":
    st.title("⚠️ 추가검토 필요 기관 목록")
    df_empty = get_google_sheet("empty_orgs")
    if not df_empty.empty:
        st.dataframe(df_empty, use_container_width=True)
    else:
        st.success("미수집 기관이 없습니다!")

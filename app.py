import streamlit as st
import pandas as pd
import json
import os
import subprocess
import sys

st.set_page_config(page_title="맞춤 공고 수집 대시보드", layout="wide")

# ==========================================
# 👈 [좌측 사이드바: 메뉴 선택 & 검색 필터]
# ==========================================
st.sidebar.title("📌 메뉴 선택")
menu = st.sidebar.radio(
    "이동할 메뉴를 선택하세요:",
    ["🚀 공고 자동 수집", "🏛️ 공고 수집 성공 기관", "⚠️ 추가검토 필요 기관 (미수집)"]
)

st.sidebar.divider()

# ==========================================
# --- 1번 메뉴: 🚀 공고 자동 수집 ---
# ==========================================
if menu == "🚀 공고 자동 수집":
    st.title("🚀 공고 자동 수집 & 실시간 검색")

    # 1. 수동 수집 버튼 (실시간 프로그레스 로그 표시)
    if st.button("🚀 지금 즉시 공고 수집 실행", type="primary"):
        with st.status("🚀 공고를 수집 중입니다...", expanded=True) as status:
            try:
                process = subprocess.Popen(
                    [sys.executable, "-u", "main.py"],
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
                    st.success("수집이 성공적으로 마무리되었습니다!")
                else:
                    status.update(label="❌ 수집 실패 (오류 발생)", state="error", expanded=True)
                    st.error("수집 도중 오류가 발생했습니다.")

            except Exception as e:
                status.update(label="❌ 실행 시스템 오류", state="error", expanded=True)
                st.error(f"실행 중 예외 발생: {e}")
        
        st.rerun()

    st.divider()

    output_file = "통합_맞춤공고.xlsx"
    if os.path.exists(output_file):
        df = pd.read_excel(output_file)

        # 🔍 [사이드바 검색 필터]
        st.sidebar.subheader("🔍 공고 실시간 검색")
        search_keyword = st.sidebar.text_input("공고제목 / 키워드 검색", "")
        search_org = st.sidebar.text_input("발주기관(출처) 검색", "")
        date_range = st.sidebar.date_input("등록일자 범위 지정", [])

        # 검색 필터링 로직
        filtered_df = df.copy()
        
        # 1) 키워드 검색
        if search_keyword:
            filtered_df = filtered_df[filtered_df['공고제목'].astype(str).str.contains(search_keyword, case=False, na=False)]
        
        # 2) 기관 검색
        if search_org and '출처' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['출처'].astype(str).str.contains(search_org, case=False, na=False)]
        
        # 3) 날짜 범위 검색
        if len(date_range) == 2 and '등록일' in filtered_df.columns:
            start_date, end_date = date_range[0], date_range[1]
            parsed_dates = pd.to_datetime(filtered_df['등록일'].astype(str).str.replace('.', '-'), errors='coerce').dt.date
            filtered_df = filtered_df[(parsed_dates >= start_date) & (parsed_dates <= end_date)]

        st.subheader(f"📋 수집된 맞춤 공고 목록 (검색 결과: {len(filtered_df)}건 / 전체: {len(df)}건)")

        # 전체 목록 표 출력 (상세링크 클릭 가능)
        st.dataframe(
            filtered_df,
            column_config={"상세링크": st.column_config.LinkColumn("상세링크")},
            use_container_width=True
        )
    else:
        st.info("아직 수집된 결과가 없습니다. 상단의 버튼을 눌러 수집을 시작해 보세요!")

# ==========================================
# --- 2번 메뉴: 🏛️ 공고 수집 성공 기관 ---
# ==========================================
elif menu == "🏛️ 공고 수집 성공 기관":
    st.title("🏛️ 공고 수집 성공 기관 목록")
    st.caption("단 한 번이라도 공고를 발굴하는 데 성공했던 검증 완료 기관들입니다.")

    collected_file = "collected_orgs.json"
    if os.path.exists(collected_file):
        try:
            with open(collected_file, "r", encoding="utf-8") as f:
                c_orgs = json.load(f)

            st.write(f"현재 총 **{len(c_orgs)}개** 기관에서 공고를 성공적으로 발굴해 보았습니다:")
            for org in c_orgs:
                st.write(f"- ✅ **{org}**")
        except Exception:
            st.error("파일을 읽는 중 오류가 발생했습니다.")
    else:
        st.info("아직 공고 수집에 성공한 기관 기록이 없습니다. 수집을 실행하면 자동으로 등록됩니다.")

# ==========================================
# --- 3번 메뉴: ⚠️ 추가검토 필요 기관 (미수집) ---
# ==========================================
elif menu == "⚠️ 추가검토 필요 기관 (미수집)":
    st.title("⚠️ 추가검토 필요 기관 목록")
    st.caption("※ 여태껏 단 한 번도 공고가 수집된 적 없는 기관들만 모아둔 목록입니다.")

    check_file = "수동확인_필요목록.xlsx"
    if os.path.exists(check_file):
        check_df = pd.read_excel(check_file)
        st.dataframe(check_df, use_container_width=True)
    else:
        st.success("🎉 현재 모든 대상 기관이 최소 1회 이상 공고를 발굴했던 검증된 기관이거나, 미수집 기관이 없습니다!")

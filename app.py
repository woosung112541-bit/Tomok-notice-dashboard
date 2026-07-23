import streamlit as st
import pandas as pd
import json
import os
import subprocess
from datetime import datetime

st.set_page_config(page_title="맞춤 공고 수집 대시보드", layout="wide")

# ==========================================
# 👈 [좌측 사이드바: 메뉴 선택 & 검색 필터]
# ==========================================
st.sidebar.title("📌 메뉴 선택")
menu = st.sidebar.radio(
    "이동할 메뉴를 선택하세요:",
    ["🚀 공고 자동 수집", "📁 공고 보관함", "⚙️ 검증 완료 기관 관리"]
)

st.sidebar.divider()

# ==========================================
# --- 1번 메뉴: 🚀 공고 자동 수집 ---
# ==========================================
if menu == "🚀 공고 자동 수집":
    st.title("🚀 공고 자동 수집 & 실시간 검색")

    # 수집 실행 버튼
    if st.button("🚀 지금 즉시 공고 수집 실행", type="primary"):
        with st.spinner("공고를 수집 중입니다... 잠시만 기다려주세요."):
            subprocess.run(["python", "main.py"], capture_output=True, text=True, encoding='utf-8')
            st.success("수집이 완료되었습니다!")
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
            # 등록일 컬럼 날짜 변환 (YYYY.MM.DD / YYYY-MM-DD 지원)
            parsed_dates = pd.to_datetime(filtered_df['등록일'].astype(str).str.replace('.', '-'), errors='coerce').dt.date
            filtered_df = filtered_df[(parsed_dates >= start_date) & (parsed_dates <= end_date)]

        st.subheader(f"📋 수집된 맞춤 공고 목록 (검색 결과: {len(filtered_df)}건 / 전체: {len(df)}건)")

        if not filtered_df.empty and '출처' in filtered_df.columns and filtered_df.iloc[0]['출처'] != '-':

            # 표 좌측에 선택용 체크박스 열 생성
            display_df = filtered_df.copy()
            display_df.insert(0, "선택", False)

            # 클릭 가능한 인터랙티브 데이터 에디터 표
            edited_df = st.data_editor(
                display_df,
                column_config={
                    "선택": st.column_config.CheckboxColumn("선택", default=False, help="보관할 공고를 체크하세요"),
                    "상세링크": st.column_config.LinkColumn("상세링크")
                },
                disabled=[col for col in display_df.columns if col != "선택"],
                hide_index=True,
                use_container_width=True,
                key="notice_editor"
            )

            # 선택한 공고 보관 버튼
            if st.button("📥 선택한 공고 보관", type="primary"):
                selected_rows = edited_df[edited_df["선택"] == True]
                
                if not selected_rows.empty:
                    # '선택' 체크박스 열 제외하고 저장
                    save_df = selected_rows.drop(columns=["선택"])

                    # 1) 저장된_공고모음.xlsx 저장 (중복 제거)
                    saved_file = "저장된_공고모음.xlsx"
                    if os.path.exists(saved_file):
                        old_saved = pd.read_excel(saved_file)
                        updated_saved = pd.concat([old_saved, save_df]).drop_duplicates(subset=['공고제목', '상세링크'])
                    else:
                        updated_saved = save_df

                    updated_saved.to_excel(saved_file, index=False)

                    # 2) 백그라운드 기관 검증 자동 등록 (verified_sites.json)
                    verified_file = "verified_sites.json"
                    verified_sites = set()
                    if os.path.exists(verified_file):
                        try:
                            with open(verified_file, "r", encoding="utf-8") as f:
                                verified_sites = set(json.load(f))
                        except Exception:
                            pass

                    new_orgs = set(save_df['출처'].dropna().unique())
                    verified_sites.update(new_orgs)

                    with open(verified_file, "w", encoding="utf-8") as f:
                        json.dump(list(verified_sites), f, ensure_ascii=False, indent=4)

                    st.success("선택한 공고가 성공적으로 공고 보관함에 저장되었습니다!")
                    st.rerun()
                else:
                    st.warning("보관할 공고의 좌측 체크박스를 먼저 선택해주세요.")
        else:
            st.dataframe(filtered_df, use_container_width=True)
    else:
        st.info("아직 수집된 결과가 없습니다. 상단의 버튼을 눌러 수집을 시작해 보세요!")

    # 추가검토 필요 사이트 목록
    check_file = "수동확인_필요목록.xlsx"
    if os.path.exists(check_file):
        st.divider()
        st.subheader("⚠️ 추가검토(수동확인) 필요 사이트 목록")
        st.caption("※ 아직 검증 등록되지 않은 기관 중, 이번 수집에서 공고를 찾지 못한 곳들입니다.")
        check_df = pd.read_excel(check_file)
        st.dataframe(check_df, use_container_width=True)

# ==========================================
# --- 2번 메뉴: 📁 공고 보관함 ---
# ==========================================
elif menu == "📁 공고 보관함":
    st.title("📁 공고 보관함")

    saved_file = "저장된_공고모음.xlsx"
    if os.path.exists(saved_file):
        saved_df = pd.read_excel(saved_file)

        # 보관함 전용 검색
        st.sidebar.subheader("🔍 보관함 내 검색")
        saved_kw = st.sidebar.text_input("공고제목 / 키워드 검색", "")
        if saved_kw:
            saved_df = saved_df[saved_df['공고제목'].astype(str).str.contains(saved_kw, case=False, na=False)]

        st.write(f"총 **{len(saved_df)}개**의 공고가 보관함에 저장되어 있습니다.")
        st.dataframe(saved_df, use_container_width=True)
    else:
        st.info("아직 저장된 공고가 없습니다. 첫 번째 메뉴에서 마음에 드는 공고를 담아보세요!")

# ==========================================
# --- 3번 메뉴: ⚙️ 검증 완료 기관 관리 ---
# ==========================================
elif menu == "⚙️ 검증 완료 기관 관리":
    st.title("⚙️ 검증 완료된 기관 목록")
    st.caption("이 목록에 등록된 기관은 공고가 나오지 않는 날에도 '추가검토 필요 사이트'에 나타나지 않습니다.")

    verified_file = "verified_sites.json"
    if os.path.exists(verified_file):
        try:
            with open(verified_file, "r", encoding="utf-8") as f:
                v_sites = json.load(f)

            st.write(f"현재 총 **{len(v_sites)}개** 기관이 검증 등록되어 있습니다:")
            for s in v_sites:
                st.write(f"- ✅ **{s}**")
        except Exception:
            st.error("파일을 읽는 중 오류가 발생했습니다.")
    else:
        st.info("아직 검증 등록된 기관이 없습니다. 공고 수집 결과에서 공고를 보관함에 담으면 자동으로 등록됩니다.")

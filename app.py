import streamlit as st
import pandas as pd
import json
import os
import subprocess

st.set_page_config(page_title="맞춤 공고 수집 대시보드", layout="wide")

# ==========================================
# 🎨 [좌측 사이드바: 테마 설정]
# ==========================================
st.sidebar.title("🎨 화면 테마 설정")
theme_choice = st.sidebar.selectbox(
    "원하는 테마를 선택하세요:",
    ["기본 모드 (System)", "🌙 다크 모드 (Dark)", "☀️ 라이트 모드 (Light)"]
)

# 테마 스타일 적용 CSS
if theme_choice == "🌙 다크 모드 (Dark)":
    st.markdown("""
        <style>
            .stApp {
                background-color: #0e1117;
                color: #ffffff;
            }
            .stSidebar {
                background-color: #161b22;
            }
        </style>
    """, unsafe_allow_html=True)
elif theme_choice == "☀️ 라이트 모드 (Light)":
    st.markdown("""
        <style>
            .stApp {
                background-color: #ffffff;
                color: #31333f;
            }
            .stSidebar {
                background-color: #f0f2f6;
            }
        </style>
    """, unsafe_allow_html=True)

st.sidebar.divider()

# ==========================================
# 👈 [좌측 사이드바: 메뉴 선택]
# ==========================================
st.sidebar.title("📌 메뉴 선택")
menu = st.sidebar.radio(
    "이동할 메뉴를 선택하세요:",
    ["🚀 공고 자동 수집", "⭐ 잘 찾은 공고 보관함", "⚙️ 검증 완료 기관 관리"]
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

        # 🔍 [검색 기능] 좌측 사이드바 검색 입력창
        st.sidebar.subheader("🔍 공고 실시간 검색")
        search_keyword = st.sidebar.text_input("공고제목 / 키워드 검색", "")
        search_org = st.sidebar.text_input("발주기관(출처) 검색", "")

        # 필터링 로직
        filtered_df = df.copy()
        if search_keyword:
            filtered_df = filtered_df[filtered_df['공고제목'].astype(str).str.contains(search_keyword, case=False, na=False)]
        if search_org and '출처' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['출처'].astype(str).str.contains(search_org, case=False, na=False)]

        st.subheader(f"📋 수집된 맞춤 공고 목록 (검색 결과: {len(filtered_df)}건 / 전체: {len(df)}건)")

        # 공고 스크랩 및 기관 검증 등록
        if not filtered_df.empty and '출처' in filtered_df.columns and filtered_df.iloc[0]['출처'] != '-':

            selected_indices = st.multiselect(
                "⭐ '잘 찾은 공고'를 선택하세요 (선택 시 해당 기관은 '추가검토 필요'에서 자동 제외):",
                options=filtered_df.index,
                format_func=lambda x: f"[{filtered_df.loc[x, '출처']}] {filtered_df.loc[x, '공고제목']} ({filtered_df.loc[x, '등록일']})"
            )

            if st.button("📥 선택한 공고 보관함 저장 & 기관 검증 등록"):
                if selected_indices:
                    selected_df = filtered_df.loc[selected_indices].copy()

                    # 1) 저장된_공고모음.xlsx 에 저장
                    saved_file = "저장된_공고모음.xlsx"
                    if os.path.exists(saved_file):
                        old_saved = pd.read_excel(saved_file)
                        updated_saved = pd.concat([old_saved, selected_df]).drop_duplicates(subset=['공고제목', '상세링크'])
                    else:
                        updated_saved = selected_df

                    updated_saved.to_excel(saved_file, index=False)

                    # 2) verified_sites.json 에 기관 등록
                    verified_file = "verified_sites.json"
                    verified_sites = set()
                    if os.path.exists(verified_file):
                        try:
                            with open(verified_file, "r", encoding="utf-8") as f:
                                verified_sites = set(json.load(f))
                        except Exception:
                            pass

                    new_orgs = set(selected_df['출처'].dropna().unique())
                    verified_sites.update(new_orgs)

                    with open(verified_file, "w", encoding="utf-8") as f:
                        json.dump(list(verified_sites), f, ensure_ascii=False, indent=4)

                    st.success(f"성공적으로 보관함에 저장되었습니다! 등록된 기관: {', '.join(new_orgs)}")
                    st.rerun()
                else:
                    st.warning("저장할 공고를 먼저 선택해주세요.")

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
# --- 2번 메뉴: ⭐ 잘 찾은 공고 보관함 ---
# ==========================================
elif menu == "⭐ 잘 찾은 공고 보관함":
    st.title("⭐ 잘 찾은 공고 모음 (보관함)")

    saved_file = "저장된_공고모음.xlsx"
    if os.path.exists(saved_file):
        saved_df = pd.read_excel(saved_file)

        # 보관함 전용 검색
        st.sidebar.subheader("🔍 보관함 검색")
        saved_kw = st.sidebar.text_input("보관함 내 검색", "")
        if saved_kw:
            saved_df = saved_df[saved_df['공고제목'].astype(str).str.contains(saved_kw, case=False, na=False)]

        st.write(f"총 **{len(saved_df)}개**의 유효 공고가 보관함에 저장되어 있습니다.")
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
        st.info("아직 검증 등록된 기관이 없습니다. 공고 수집 결과에서 '잘 찾은 공고'를 저장하면 자동으로 등록됩니다.")

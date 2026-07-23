import streamlit as st
import pandas as pd
import json
import os
import subprocess

st.set_page_config(page_title="맞춤 공고 수집 대시보드", layout="wide")

# 탭 구성: [1. 🚀 수동 수집 & 결과] [2. ⭐ 잘 찾은 공고 보관함] [3. ⚙️ 검증 완료 기관 관리]
tab1, tab2, tab3 = st.tabs(["🚀 공고 수집 및 결과", "⭐ 잘 찾은 공고 보관함", "⚙️ 검증 완료 기관 관리"])

# ==========================================
# --- TAB 1: 공고 수집 및 결과 ---
# ==========================================
with tab1:
    st.title("🔎 수동 공고 수집 & 결과 검증")
    
    # 1. 수동 수집 버튼
    if st.button("🚀 지금 즉시 공고 수집 실행", type="primary"):
        with st.spinner("공고를 수집 중입니다... 잠시만 기다려주세요."):
            subprocess.run(["python", "main.py"], capture_output=True, text=True, encoding='utf-8')
            st.success("수집이 완료되었습니다!")
            st.rerun()

    st.divider()

    # 2. 최근 수집 결과 불러오기 (통합_맞춤공고.xlsx)
    output_file = "통합_맞춤공고.xlsx"
    if os.path.exists(output_file):
        df = pd.read_excel(output_file)
        st.subheader("📋 최근 수집된 맞춤 공고 목록")
        
        # 데이터가 정상적으로 수집된 경우만 보관함 저장 기능 제공
        if not df.empty and '출처' in df.columns and df.iloc[0]['출처'] != '-':
            
            # 다중 선택을 통한 보관함 저장 및 사이트 검증 기능
            selected_indices = st.multiselect(
                "⭐ '잘 찾은 공고'를 선택하세요 (선택 시 해당 발주기관은 '추가검토 필요'에서 자동 제외됩니다):",
                options=df.index,
                format_func=lambda x: f"[{df.loc[x, '출처']}] {df.loc[x, '공고제목']} ({df.loc[x, '등록일']})"
            )
            
            if st.button("📥 선택한 공고 보관함 저장 & 기관 검증 등록"):
                if selected_indices:
                    selected_df = df.loc[selected_indices].copy()
                    
                    # (1) 저장된_공고모음.xlsx 파일에 저장 (중복 제거)
                    saved_file = "저장된_공고모음.xlsx"
                    if os.path.exists(saved_file):
                        old_saved = pd.read_excel(saved_file)
                        updated_saved = pd.concat([old_saved, selected_df]).drop_duplicates(subset=['공고제목', '상세링크'])
                    else:
                        updated_saved = selected_df
                    
                    updated_saved.to_excel(saved_file, index=False)
                    
                    # (2) verified_sites.json 장부에 출처 기관명 등록
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
                    
                    st.success(f"성공적으로 보관함에 저장되었습니다! 검증 등록된 기관: {', '.join(new_orgs)}")
                    st.rerun()
                else:
                    st.warning("저장할 공고를 먼저 선택해주세요.")
        
        st.dataframe(df, use_container_width=True)
    else:
        st.info("아직 수집된 결과가 없습니다. 상단의 버튼을 눌러 수집을 시작해보세요!")

    # 3. 추가검토(수동확인) 필요 사이트 목록 표시
    check_file = "수동확인_필요목록.xlsx"
    if os.path.exists(check_file):
        st.divider()
        st.subheader("⚠️ 추가검토(수동확인) 필요 사이트 목록")
        st.caption("※ 아직 검증 등록되지 않은 기관 중, 이번 수집에서 공고를 찾지 못한 곳들입니다.")
        check_df = pd.read_excel(check_file)
        st.dataframe(check_df, use_container_width=True)

# ==========================================
# --- TAB 2: ⭐ 잘 찾은 공고 보관함 ---
# ==========================================
with tab2:
    st.title("⭐ 잘 찾은 공고 모음 (보관함)")
    saved_file = "저장된_공고모음.xlsx"
    if os.path.exists(saved_file):
        saved_df = pd.read_excel(saved_file)
        st.write(f"총 **{len(saved_df)}개**의 유효 공고가 보관함에 저장되어 있습니다.")
        st.dataframe(saved_df, use_container_width=True)
    else:
        st.info("아직 저장된 공고가 없습니다. 첫 번째 탭에서 마음에 드는 공고를 선택해 보관함에 담아보세요!")

# ==========================================
# --- TAB 3: ⚙️ 검증 완료 기관 관리 ---
# ==========================================
with tab3:
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

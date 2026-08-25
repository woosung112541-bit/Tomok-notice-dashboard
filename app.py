import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

import pandas as pd
import streamlit as st
import gspread

import config
import storage

KST = timezone(timedelta(hours=9))

st.set_page_config(page_title="맞춤 공고 수집 대시보드", layout="wide")


# ==========================================
# 🔐 대시보드 보안 자물쇠
# ==========================================
def check_password() -> bool:
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if not st.session_state["password_correct"]:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🔒 대시보드 보안 접속")
            st.info("이 대시보드는 우리 팀원만 접근할 수 있습니다.\n\n발급받은 비밀번호를 입력해 주세요.")
            pwd_input = st.text_input("🔑 비밀번호 입력", type="password")
            if st.button("🚀 접속하기", use_container_width=True, type="primary"):
                if pwd_input == config.DASHBOARD_PASSWORD:
                    st.session_state["password_correct"] = True
                    st.rerun()
                else:
                    st.error("🚫 비밀번호가 일치하지 않습니다.")
        return False
    return True


if not check_password():
    st.stop()

# GOOGLE_CREDENTIALS 시크릿이 있으면 google_key.json으로 기록 (storage.py가 이 파일을 사용)
storage.write_key_file_from_secret()


@st.cache_data(ttl=60)
def get_recent_log():
    try:
        _, doc = storage.connect()
        ws = doc.worksheet(config.SHEET_SETTINGS)
        eng = ws.cell(2, 1).value
        tm = ws.cell(2, 2).value
        return eng or "기록 없음", tm or "-"
    except Exception:
        return "기록 없음", "-"


@st.cache_data(ttl=300)
def get_google_sheet(sheet_name: str) -> pd.DataFrame:
    try:
        _, doc = storage.connect()
        ws = doc.worksheet(sheet_name)
        return pd.DataFrame(ws.get_all_records())
    except Exception:
        return pd.DataFrame()


def update_notice_status(notice_keys_to_mark, status_value) -> bool:
    try:
        _, doc = storage.connect()
        ws = doc.worksheet(config.SHEET_NOTICES)
        all_records = ws.get_all_values()
        if not all_records:
            return True
        headers = all_records[0]
        if "검토유무" not in headers:
            headers.append("검토유무")
            ws.update(range_name="1:1", values=[headers])
            review_col_idx = len(headers) - 1
        else:
            review_col_idx = headers.index("검토유무")
        key_col_idx = headers.index("notice_key")

        cells_to_update = []
        for row_idx, row in enumerate(all_records):
            if row_idx == 0:
                continue
            if len(row) <= review_col_idx:
                row.extend([""] * (review_col_idx - len(row) + 1))
            if row[key_col_idx] in notice_keys_to_mark:
                cells_to_update.append(gspread.Cell(row=row_idx + 1, col=review_col_idx + 1, value=status_value))
        if cells_to_update:
            ws.update_cells(cells_to_update)
        return True
    except Exception:
        return False


@st.cache_data
def get_target_org_list():
    try:
        import os
        base_dir = os.path.dirname(os.path.abspath(__file__))
        df = pd.read_excel(os.path.join(base_dir, config.INPUT_EXCEL_FILENAME), sheet_name=0)
        orgs = df.iloc[:, config.ORG_NAME_COL_INDEX].dropna().astype(str).unique().tolist()
        orgs.extend([s["org_name"] for s in config.EXTRA_SITES])
        return sorted(set(orgs))
    except Exception:
        return [s["org_name"] for s in config.EXTRA_SITES]


def render_notice_table(df: pd.DataFrame, key_prefix: str):
    if df.empty:
        st.info("해당되는 공고가 없습니다.")
        return

    display_columns = ["notice_key", "출처", "등록일", "공고제목", "특이사항", "검토유무", "상세링크"]
    display_df = df[[c for c in display_columns if c in df.columns]].copy()
    display_df.insert(0, "선택", False)

    def highlight_row(row):
        status = str(row.get("검토유무", "")).strip()
        title_text = str(row.get("공고제목", ""))
        special_text = str(row.get("특이사항", ""))
        if status == "내업무아님":
            return ["background-color: #8c8c8c; color: #ffffff; text-decoration: line-through;"] * len(row)
        if status == "내업무맞음":
            return ["background-color: #cce5ff; color: #004080; font-weight: bold;"] * len(row)
        if status == "완료":
            return ["background-color: #f0f2f6; color: #a0aab2;"] * len(row)
        if "안전점검" in title_text or "안전점검" in special_text:
            return ["background-color: #e6ffe6; color: #006600; font-weight: bold;"] * len(row)
        return [""] * len(row)

    styled_df = display_df.style.apply(highlight_row, axis=1)
    disabled_cols = [c for c in display_df.columns if c != "선택"]

    edited_df = st.data_editor(
        styled_df,
        column_config={
            "선택": st.column_config.CheckboxColumn("선택", required=True),
            "상세링크": st.column_config.LinkColumn("상세링크"),
            "notice_key": None,
        },
        disabled=disabled_cols, hide_index=True, use_container_width=True, key=f"editor_{key_prefix}",
    )

    selected_keys = edited_df[edited_df["선택"]]["notice_key"].tolist() if "선택" in edited_df.columns else []
    if selected_keys:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            if st.button("👍 내 업무 맞음", key=f"{key_prefix}_ok", use_container_width=True):
                if update_notice_status(selected_keys, "내업무맞음"):
                    get_google_sheet.clear(); st.rerun()
        with c2:
            if st.button("👎 내 업무 아님", key=f"{key_prefix}_no", use_container_width=True):
                if update_notice_status(selected_keys, "내업무아님"):
                    get_google_sheet.clear(); st.rerun()
        with c3:
            if st.button("✅ 완료 처리", key=f"{key_prefix}_done", use_container_width=True):
                if update_notice_status(selected_keys, "완료"):
                    get_google_sheet.clear(); st.rerun()
        with c4:
            if st.button("↩️ 미검토로 되돌리기", key=f"{key_prefix}_undo", use_container_width=True):
                if update_notice_status(selected_keys, "미검토"):
                    get_google_sheet.clear(); st.rerun()


# ==========================================
# 사이드바 메뉴
# ==========================================
st.sidebar.title("📌 메뉴 선택")
menu = st.sidebar.radio(
    "이동할 메뉴를 선택하세요:",
    ["공고 자동수집", "🚨 수동 확인 필요", "🔗 발주처 URL 관리",
     "공고 통계 및 분석", "🎯 타겟 공고 (내 업무)", "📝 게시판 / 메모장"],
)
st.sidebar.divider()

st.sidebar.subheader("🔗 주요 사이트 바로가기")
for site in config.EXTRA_SITES:
    st.sidebar.link_button(site["org_name"], site["url"])
st.sidebar.link_button("🛒 나라장터", "https://www.g2b.go.kr/index.jsp")
for domain, reason in config.KNOWN_HARD_DOMAINS.items():
    st.sidebar.link_button(f"💧 {domain} (수동 확인)", f"https://{domain}")

st.sidebar.divider()
last_engine, last_time = get_recent_log()
st.sidebar.info(f"**최근 실행:** {last_engine}\n\n**시간:** {last_time}")

# ==========================================
# 🔗 발주처 URL 관리
# ==========================================
if menu == "🔗 발주처 URL 관리":
    st.title("🔗 발주처 전용 URL (게시판 직행) 관리")
    st.info(
        "💡 **로봇이 엑셀의 홈페이지 주소에서 고시공고 게시판을 찾지 못하는 경우, "
        "이곳에 정확한 게시판 직통 URL을 직접 입력해두세요!**\n\n"
        "여기에 등록된 URL은 엑셀 주소보다 무조건 우선 적용됩니다."
    )
    df_url = get_google_sheet(config.SHEET_URL_OVERRIDES)
    if df_url.empty:
        df_url = pd.DataFrame([{"발주기관명": "", "정확한_게시판_URL": "", "비고": ""}])

    st.write("▼ 더블클릭하여 수정, 맨 아래 빈칸으로 새 기관 추가, 행 선택 후 Delete로 삭제")
    edited_url_df = st.data_editor(df_url, num_rows="dynamic", use_container_width=True)

    if st.button("💾 변경사항 저장하여 로봇에 적용하기", type="primary"):
        with st.spinner("구글 시트에 저장 중..."):
            try:
                _, doc = storage.connect()
                try:
                    ws_urls = doc.worksheet(config.SHEET_URL_OVERRIDES)
                except gspread.exceptions.WorksheetNotFound:
                    ws_urls = doc.add_worksheet(config.SHEET_URL_OVERRIDES, 100, 3)
                edited_url_df = edited_url_df.fillna("")
                data_to_save = [edited_url_df.columns.tolist()] + edited_url_df.values.tolist()
                ws_urls.clear()
                ws_urls.update(values=data_to_save, range_name="A1")
                get_google_sheet.clear()
                st.success("✅ 저장 완료! 다음 수집부터 이 직통 주소로 탐색합니다.")
                time.sleep(1.2)
                st.rerun()
            except Exception as e:
                st.error(f"저장 중 오류 발생: {e}")

# ==========================================
# 🚨 수동 확인 필요
# ==========================================
elif menu == "🚨 수동 확인 필요":
    st.title("🚨 자동 수집이 어려운 발주처 (수동 확인 필요)")
    st.caption(
        "봇 방어/보안 프로그램이 강하거나, 게시판 구조를 자동으로 못 찾은 발주처 목록입니다. "
        "예전처럼 '조용히 실패'하는 대신 여기에 사유와 함께 명시적으로 쌓입니다."
    )
    df_manual = get_google_sheet(config.SHEET_MANUAL_CHECK)
    if df_manual.empty:
        st.success("현재 수동 확인이 필요한 발주처가 없습니다.")
    else:
        is_g2b_migrated = df_manual["사유"].astype(str).str.contains("나라장터로 별도 수집", na=False)
        df_real = df_manual[~is_g2b_migrated]
        df_g2b = df_manual[is_g2b_migrated]

        st.markdown(f"#### 🔴 진짜 확인이 필요한 발주처 ({len(df_real)}곳)")
        if df_real.empty:
            st.success("없습니다.")
        else:
            st.dataframe(df_real, use_container_width=True, hide_index=True,
                         column_config={"URL": st.column_config.LinkColumn("URL")})

        if not df_g2b.empty:
            st.markdown(f"#### ⚪ 조달청 이관 기관 - 참고용 ({len(df_g2b)}곳)")
            st.caption("명부에 '조달청 이관' 표시가 된 기관들입니다. 나라장터 API로 별도 수집되고 있어 "
                       "자체 게시판에 공고가 없는 게 정상일 가능성이 높습니다.")
            st.dataframe(df_g2b, use_container_width=True, hide_index=True,
                         column_config={"URL": st.column_config.LinkColumn("URL")})

    st.divider()
    st.subheader("🪵 최근 실행 로그 (실패/경고)")
    df_log = get_google_sheet(config.SHEET_RUN_LOG)
    if df_log.empty:
        st.info("기록된 로그가 없습니다.")
    else:
        st.dataframe(df_log.tail(200), use_container_width=True, hide_index=True)

# ==========================================
# 공고 자동수집
# ==========================================
elif menu == "공고 자동수집":
    st.title("🚀 공고 자동 수집 & 실시간 검색")

    with st.container(border=True):
        st.subheader("⚙️ 수집 기본 설정")
        col1, col2 = st.columns([1, 2])
        with col1:
            collect_days = st.number_input("수집 기간 (0입력 시, 당일만 수집)", min_value=0, max_value=365, value=0, step=1)
        with col2:
            collect_keywords = st.text_input("🔑 수집 키워드 (쉼표 구분)", value="모집, 안전, 공고")

        st.divider()
        st.subheader("🎯 타겟 발주처 설정")
        scan_mode = st.toggle("✅ 전수조사 (모든 등록 기관 스캔)", value=True)

        selected_orgs_str = "ALL"
        if not scan_mode:
            org_list = get_target_org_list()
            selected_orgs = st.multiselect("탐색할 특정 발주처를 선택하세요:", org_list, placeholder="기관명을 검색하거나 선택하세요...")
            if not selected_orgs:
                st.warning("⚠️ 최소 1개 이상의 발주처를 선택해야 합니다.")
            else:
                selected_orgs_str = ",".join(selected_orgs)

        st.caption(
            "ℹ️ 사이트별 수집 방식(requests / selenium / 전용 로직)은 시스템이 자동으로 결정합니다. "
            "더 이상 엔진을 직접 고를 필요가 없습니다."
        )

        if st.button("🚀 공고 수집 시작", type="primary", use_container_width=True):
            if not scan_mode and selected_orgs_str == "ALL":
                st.error("특정 발주처 선택 모드입니다. 기관을 선택해주세요.")
            else:
                try:
                    _, doc = storage.connect()
                except storage.SheetUnavailable as e:
                    st.error(f"구글 시트 연결 실패: {e}")
                    doc = None

                if doc is not None:
                    if storage.manage_sheet_lock(doc, "check"):
                        st.warning("⏳ 현재 다른 팀원이 공고를 수집 중입니다. 잠시 후 시도해주세요.")
                    else:
                        with st.status("🚀 수집 엔진 가동 중...", expanded=True) as status:
                            try:
                                storage.manage_sheet_lock(doc, "lock_and_log", engine_name="통합 엔진")
                                get_recent_log.clear()

                                process = subprocess.Popen(
                                    [sys.executable, "-u", "main.py", str(collect_days), collect_keywords, selected_orgs_str],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", bufsize=1,
                                )
                                for line in iter(process.stdout.readline, ""):
                                    if line:
                                        st.write(line.strip())
                                process.wait()

                                if process.returncode == 0:
                                    status.update(label="✅ 공고 수집 완료!", state="complete", expanded=False)
                                    get_google_sheet.clear()
                                else:
                                    status.update(label="❌ 수집 실패 (로그 확인 필요)", state="error", expanded=True)
                            except Exception as e:
                                status.update(label=f"❌ 시스템 오류: {e}", state="error", expanded=True)
                            finally:
                                storage.manage_sheet_lock(doc, "unlock")
                        st.rerun()

    st.divider()

    df = get_google_sheet(config.SHEET_NOTICES)
    if not df.empty and "공고제목" in df.columns:
        if "검토유무" not in df.columns:
            df["검토유무"] = "미검토"

        st.sidebar.subheader("🔍 공고 실시간 검색")
        search_keyword = st.sidebar.text_input("공고제목 / 특이사항 검색", "")
        search_org = st.sidebar.text_input("발주기관(출처) 검색", "")
        hide_reviewed = st.sidebar.checkbox("✅ 검토 완료된 공고 숨기기", value=True)

        filtered_df = df.copy()
        if hide_reviewed:
            filtered_df = filtered_df[~filtered_df["검토유무"].isin(["완료", "내업무아님", "내업무맞음"])]
        if search_keyword:
            filtered_df = filtered_df[
                filtered_df["공고제목"].astype(str).str.contains(search_keyword, case=False, na=False)
                | filtered_df["특이사항"].astype(str).str.contains(search_keyword, case=False, na=False)
            ]
        if search_org:
            filtered_df = filtered_df[filtered_df["출처"].astype(str).str.contains(search_org, case=False, na=False)]

        col_btn1, col_btn2 = st.columns([3, 1])
        with col_btn2:
            if st.button("✅ 현재 화면 전체 일괄 검토완료", use_container_width=True):
                keys_to_mark = filtered_df["notice_key"].tolist()
                if keys_to_mark and update_notice_status(keys_to_mark, "완료"):
                    get_google_sheet.clear(); st.rerun()

        main_sites_keywords = ["한국시설안전협회", "조달청", "아이건설넷", "나라장터"]
        df_main = filtered_df[filtered_df["출처"].str.contains("|".join(main_sites_keywords), na=False)]
        df_general = filtered_df[~filtered_df["출처"].str.contains("|".join(main_sites_keywords), na=False)]

        st.subheader(f"📋 일반 기관 공고 ({len(df_general)}건)")
        render_notice_table(df_general, "general")
        st.divider()
        st.subheader(f"🌟 주요 4대 중앙 공고 ({len(df_main)}건)")
        render_notice_table(df_main, "main_site")
    else:
        st.info("아직 구글 시트에 수집된 데이터가 없습니다.")

# ==========================================
# 기타 메뉴 (원본과 동일하게 자리만 유지 - 필요 시 후속 확장)
# ==========================================
elif menu == "공고 통계 및 분석":
    st.title("📊 공고 통계 및 분석 대시보드")
    st.write("추후 확장 예정")
elif menu == "🎯 타겟 공고 (내 업무)":
    st.title("🎯 수동 분류된 '내 업무' 공고 리스트")
    df = get_google_sheet(config.SHEET_NOTICES)
    if not df.empty and "검토유무" in df.columns:
        render_notice_table(df[df["검토유무"] == "내업무맞음"], "target_work")
    else:
        st.info("데이터가 없습니다.")
elif menu == "📝 게시판 / 메모장":
    st.title("📝 팀 게시판 및 메모장")
    st.write("추후 확장 예정")

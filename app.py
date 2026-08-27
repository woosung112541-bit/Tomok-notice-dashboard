import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

import pandas as pd
import streamlit as st
import gspread

import config
import storage
import site_registry

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
    ["공고 자동수집", "🔍 실패 로그 분석", "🔗 발주처 URL 관리",
     "공고 통계 및 분석", "🎯 타겟 공고 (내 업무)", "📝 게시판 / 메모장"],
)
st.sidebar.divider()

st.sidebar.subheader("🔗 주요 사이트 바로가기")
for site in config.EXTRA_SITES:
    st.sidebar.link_button(site["org_name"], site["url"])
st.sidebar.link_button("🛒 나라장터", "https://www.g2b.go.kr/index.jsp")
for domain, info in config.KNOWN_HARD_SITES.items():
    st.sidebar.link_button(f"💧 {info['label']}", info["url"])

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
        "이곳에 정확한 게시판 직통 URL을 등록해두세요!**\n\n"
        "여기에 등록된 URL은 엑셀 주소보다 무조건 우선 적용됩니다."
    )

    base_dir = os.path.dirname(os.path.abspath(__file__))
    default_url_map = site_registry.get_org_default_url_map(base_dir)

    df_url = get_google_sheet(config.SHEET_URL_OVERRIDES)
    override_map = {}
    if not df_url.empty:
        for _, r in df_url.iterrows():
            override_map[str(r.get("발주기관명", ""))] = {
                "url": str(r.get("정확한_게시판_URL", "")),
                "note": str(r.get("비고", "")),
            }

    tab_edit, tab_add = st.tabs(["✏️ 등록된 발주처 수정", "➕ 새 발주처 추가"])

    # ── 탭 1: 이미 명부에 등록된 발주처 중 하나를 '골라서' 수정 ──────────────────
    with tab_edit:
        org_list = sorted(default_url_map.keys())
        labeled_options = [
            f"⭐ {name}" if name in override_map else name for name in org_list
        ]
        picked_label = st.selectbox("발주처 선택 (⭐ = 이미 직통 URL이 등록된 곳)", labeled_options)
        picked_org = picked_label[2:] if picked_label.startswith("⭐ ") else picked_label

        current_override = override_map.get(picked_org)
        current_url = current_override["url"] if current_override else default_url_map.get(picked_org, "")
        current_note = current_override["note"] if current_override else ""

        st.caption(f"현재 사용 중인 주소 ({'직통 URL 등록됨' if current_override else '명부 기본값'}):")
        st.code(current_url or "(등록된 URL 없음)")

        new_url = st.text_input("새 직통 URL", value=current_url, key="edit_url_input")
        new_note = st.text_input("비고", value=current_note, key="edit_note_input")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 이 발주처에 저장", type="primary", use_container_width=True):
                if not new_url.startswith("http"):
                    st.error("URL은 http:// 또는 https:// 로 시작해야 합니다.")
                else:
                    try:
                        _, doc = storage.connect()
                        storage.upsert_url_override(doc, picked_org, new_url, new_note)
                        get_google_sheet.clear()
                        st.success(f"✅ '{picked_org}' 직통 URL이 저장되었습니다.")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"저장 중 오류: {e}")
        with c2:
            if current_override and st.button("↩️ 기본값으로 되돌리기 (오버라이드 삭제)", use_container_width=True):
                try:
                    _, doc = storage.connect()
                    storage.delete_url_override(doc, picked_org)
                    get_google_sheet.clear()
                    st.success(f"✅ '{picked_org}' 오버라이드가 삭제되었습니다. 명부 기본 URL로 되돌아갑니다.")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"삭제 중 오류: {e}")

    # ── 탭 2: 명부에 아예 없는 새 발주처를 추가 (코드/엑셀 수정 없이 바로 수집 대상에 포함됨) ──
    with tab_add:
        st.caption("여기서 추가한 발주처는 다음 수집부터 바로 대상에 포함됩니다 (코드/엑셀 수정 불필요).")
        new_org_name = st.text_input("새 발주기관명", key="new_org_name")
        new_org_url = st.text_input("게시판 직통 URL", key="new_org_url")
        new_org_note = st.text_input("비고", key="new_org_note")
        if st.button("➕ 새 발주처 추가", type="primary"):
            if not new_org_name.strip():
                st.error("발주기관명을 입력해주세요.")
            elif new_org_name.strip() in default_url_map or new_org_name.strip() in override_map:
                st.error("이미 존재하는 발주기관명입니다. '등록된 발주처 수정' 탭에서 수정해주세요.")
            elif not new_org_url.startswith("http"):
                st.error("URL은 http:// 또는 https:// 로 시작해야 합니다.")
            else:
                try:
                    _, doc = storage.connect()
                    storage.upsert_url_override(doc, new_org_name.strip(), new_org_url.strip(), new_org_note)
                    get_google_sheet.clear()
                    st.success(f"✅ 새 발주처 '{new_org_name}'가 추가되었습니다.")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"추가 중 오류: {e}")

    st.divider()
    st.subheader(f"📋 현재 등록된 직통 URL 목록 ({len(override_map)}건)")
    if not df_url.empty:
        st.dataframe(df_url, use_container_width=True, hide_index=True,
                     column_config={"정확한_게시판_URL": st.column_config.LinkColumn("정확한_게시판_URL")})
    else:
        st.info("아직 등록된 직통 URL이 없습니다.")

# ==========================================
# 🔍 실패 로그 분석
# ==========================================
elif menu == "🔍 실패 로그 분석":
    st.title("🔍 실패 로그 분석")
    st.caption(
        "봇 방어/보안 프로그램이 강하거나, 게시판 구조를 자동으로 못 찾은 발주처 목록입니다. "
        "예전처럼 '조용히 실패'하는 대신 여기에 사유와 함께 명시적으로 쌓입니다."
    )
    df_manual = get_google_sheet(config.SHEET_MANUAL_CHECK)
    if df_manual.empty:
        st.success("현재 확인이 필요한 실패 항목이 없습니다.")
    else:
        is_g2b_migrated = df_manual["사유"].astype(str).str.contains("나라장터로 별도 수집", na=False)
        is_network_blocked = df_manual["사유"].astype(str).str.contains("클라우드 IP", na=False)
        df_real = df_manual[~is_g2b_migrated & ~is_network_blocked]
        df_network = df_manual[is_network_blocked]
        df_g2b = df_manual[is_g2b_migrated]

        st.markdown(f"#### 🔴 구조/셀렉터 확인이 필요한 발주처 ({len(df_real)}곳)")
        if df_real.empty:
            st.success("없습니다.")
        else:
            st.dataframe(df_real, use_container_width=True, hide_index=True,
                         column_config={"URL": st.column_config.LinkColumn("URL")})

        if not df_network.empty:
            st.markdown(f"#### 🌐 접속 자체가 차단된 것으로 보이는 발주처 ({len(df_network)}곳)")
            st.caption("셀렉터 문제가 아니라 서버 접속(타임아웃)부터 실패한 경우입니다. "
                       "국내 IP 경유가 필요할 가능성이 높습니다 (하단 '수동 확인' 페이지 하단 안내 참고).")
            st.dataframe(df_network, use_container_width=True, hide_index=True,
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
        proxy_notes = df_log[df_log["단계"] == "proxy_status"]
        if not proxy_notes.empty:
            last_proxy_note = proxy_notes.iloc[-1]
            st.caption(f"🌐 가장 최근 실행의 프록시 상태: **{last_proxy_note['오류메시지']}** "
                       f"({last_proxy_note['시각']})")
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

        use_proxy = st.toggle("🌐 무료 프록시로 우회 시도 (실험적)", value=False)
        if use_proxy:
            st.caption(
                "⚠️ 무료 공개 프록시를 매번 새로 찾아 시도합니다. **작동을 보장하지 않습니다** — "
                "살아있는 국내(KR) 프록시가 없으면 자동으로 프록시 없이 진행되고, 그 여부는 "
                "실행 로그 맨 위 '[프록시]'로 시작하는 줄에서 확인할 수 있습니다. 확실한 우회가 "
                "필요하면 사무실 회선 기반 셀프호스팅 러너가 더 안정적입니다."
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
                        progress_bar = st.progress(0, text="수집 준비 중...")
                        with st.status("🚀 수집 엔진 가동 중...", expanded=True) as status:
                            try:
                                storage.manage_sheet_lock(doc, "lock_and_log", engine_name="통합 엔진")
                                get_recent_log.clear()

                                process = subprocess.Popen(
                                    [sys.executable, "-u", "main.py", str(collect_days), collect_keywords,
                                     selected_orgs_str, "1" if use_proxy else "0"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", bufsize=1,
                                )
                                for raw_line in iter(process.stdout.readline, ""):
                                    if not raw_line:
                                        continue
                                    line = raw_line.strip()
                                    # engine.py가 사이트 하나 처리를 끝낼 때마다 찍는 진행률 마커.
                                    # 로그 포맷("[시각] [INFO] ...")과 섞이지 않도록 별도의 단순한
                                    # "PROGRESS:완료수:전체수" 줄로 내려오며, 여기서만 파싱해서
                                    # 막대바를 갱신하고 일반 로그 창에는 출력하지 않는다.
                                    if line.startswith("PROGRESS:"):
                                        try:
                                            _, done_str, total_str = line.split(":")
                                            done, total = int(done_str), int(total_str)
                                            pct = min(done / total, 1.0) if total else 0.0
                                            progress_bar.progress(pct, text=f"{done}/{total}곳 처리 완료 ({int(pct * 100)}%)")
                                        except (ValueError, ZeroDivisionError):
                                            pass
                                    else:
                                        st.write(line)
                                process.wait()

                                if process.returncode == 0:
                                    progress_bar.progress(1.0, text="✅ 전체 완료 (100%)")
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

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
import github_actions

KST = timezone(timedelta(hours=9))

st.set_page_config(page_title="Tomok Notice Dashboard", page_icon="📋", layout="wide")


def check_password() -> bool:
    if not config.DASHBOARD_PASSWORD:
        return True
    if st.session_state.get("password_ok"):
        return True
    pw = st.text_input("비밀번호", type="password")
    if pw == config.DASHBOARD_PASSWORD:
        st.session_state["password_ok"] = True
        st.rerun()
    elif pw:
        st.error("비밀번호가 틀렸습니다.")
    return False


def get_recent_log():
    """settings 탭에 기록된 '최근 실행' 정보를 가져온다 (manage_sheet_lock이
    실행마다 엔진명+시각을 기록함 - 클라우드/사무실PC 어느 쪽이든 반영됨)."""
    try:
        _, doc = storage.connect()
        ws = storage._get_or_create_worksheet(doc, config.SHEET_SETTINGS, ["status", "locked_at", "engine"])
        values = ws.get_all_values()
        if values and len(values) > 0:
            row = values[0]
            engine_name = row[2] if len(row) > 2 and row[2] else "-"
            locked_at = row[1] if len(row) > 1 and row[1] else "-"
            return engine_name, locked_at
    except Exception:
        pass
    return "-", "-"


@st.cache_data(ttl=60)
def get_google_sheet(sheet_name: str) -> pd.DataFrame:
    try:
        _, doc = storage.connect()
        ws = doc.worksheet(sheet_name)
        records = ws.get_all_records()
        return pd.DataFrame(records)
    except Exception:
        return pd.DataFrame()


def update_notice_status(notice_keys_to_mark, status_value) -> bool:
    try:
        _, doc = storage.connect()
        ws = doc.worksheet(config.SHEET_NOTICES)
        records = ws.get_all_records()
        headers = ws.row_values(1)
        status_col = headers.index("검토유무") + 1
        key_col = headers.index("notice_key") + 1
        for i, r in enumerate(records, start=2):
            if str(r.get("notice_key", "")) in notice_keys_to_mark:
                ws.update_cell(i, status_col, status_value)
        return True
    except Exception as e:
        st.error(f"상태 업데이트 실패: {e}")
        return False


def _render_stuck_lock_warning(doc, key_suffix: str):
    """'다른 실행이 진행 중' 경고와 함께, 취소/비정상종료로 락이 안 풀렸을 때
    수동으로 즉시 풀 수 있는 버튼을 보여준다. (15분이 지나면 자동으로도 풀리지만,
    GitHub Actions에서 '취소'를 누르면 프로세스가 강제 종료되면서 락을 푸는 코드가
    실행될 기회 없이 죽어버려, 그 15분을 그냥 기다려야 하는 문제가 실제로 있었다.)
    """
    st.warning("⏳ 현재 다른 실행(클라우드 또는 사무실 PC)이 진행 중입니다. 잠시 후 시도해주세요.")
    with st.expander("혹시 방금 실행을 '취소'하셨나요? (강제로 잠금 풀기)"):
        st.caption(
            "⚠️ 실제로 다른 곳에서 아직 실행 중이라면 누르지 마세요 - 두 실행이 동시에 "
            "돌면서 서로 꼬일 수 있습니다. 방금 GitHub Actions나 이 화면에서 실행을 "
            "중간에 '취소'하신 경우에만 눌러주세요 (취소하면 잠금을 풀 틈도 없이 "
            "바로 꺼지기 때문에, 원래는 15분 뒤 자동으로 풀리는데 그걸 기다리지 않아도 되게 해줍니다)."
        )
        if st.button("🔓 지금 바로 잠금 강제 해제", key=f"force_unlock_{key_suffix}"):
            storage.manage_sheet_lock(doc, "unlock")
            st.success("잠금을 해제했습니다. 다시 시도해주세요.")
            st.rerun()


@st.cache_data(ttl=300)
def get_target_org_list():
    orgs = set()

    # 1) 등록명부 엑셀
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        df = pd.read_excel(os.path.join(base_dir, config.INPUT_EXCEL_FILENAME), sheet_name=0)
        orgs.update(df.iloc[:, config.ORG_NAME_COL_INDEX].dropna().astype(str).unique().tolist())
    except Exception:
        pass

    # 2) 코드에 항상 포함되는 사이트 (한국시설안전협회 등)
    orgs.update(s["org_name"] for s in config.EXTRA_SITES)

    # 3) "➕ 새 발주처 추가"로 등록한 곳들 - url_overrides 시트에는 저장되는데
    # 이 드롭다운은 엑셀만 보고 있어서 여기 추가한 게 하나도 안 뜨는 버그가 있었다.
    # 이제 이 시트도 함께 읽어서 합친다.
    try:
        _, doc = storage.connect()
        ws = doc.worksheet(config.SHEET_URL_OVERRIDES)
        for r in ws.get_all_records():
            name = str(r.get("발주기관명", "")).strip()
            if name:
                orgs.add(name)
    except Exception:
        pass

    orgs.add(config.G2B_VIRTUAL_ORG_NAME)
    return sorted(orgs)


def render_notice_table(df: pd.DataFrame, key_prefix: str):
    if df.empty:
        st.info("데이터가 없습니다.")
        return

    display_columns = ["출처", "등록일", "공고제목", "특이사항", "검토유무", "상세링크"]
    show_df = df[[c for c in display_columns if c in df.columns]].copy()
    show_df.insert(0, "선택", False)

    edited_df = st.data_editor(
        show_df, hide_index=True, use_container_width=True, key=f"{key_prefix}_editor",
        column_config={
            "선택": st.column_config.CheckboxColumn("선택", required=True),
            "상세링크": st.column_config.LinkColumn("상세링크"),
        },
        disabled=[c for c in show_df.columns if c != "선택"],
    )

    selected_indices = edited_df[edited_df["선택"]].index
    selected_keys = df.loc[selected_indices, "notice_key"].tolist() if "notice_key" in df.columns else []

    col1, col2, col3 = st.columns(3)
    if col1.button("✅ 내 업무 맞음으로 표시", key=f"{key_prefix}_mark_yes"):
        if selected_keys and update_notice_status(selected_keys, "내업무맞음"):
            get_google_sheet.clear()
            st.rerun()
    if col2.button("❌ 내 업무 아님으로 표시", key=f"{key_prefix}_mark_no"):
        if selected_keys and update_notice_status(selected_keys, "내업무아님"):
            get_google_sheet.clear()
            st.rerun()
    if col3.button("↩️ 미검토로 되돌리기", key=f"{key_prefix}_mark_reset"):
        if selected_keys and update_notice_status(selected_keys, "미검토"):
            get_google_sheet.clear()
            st.rerun()


# ==========================================
# 로그인 체크
# ==========================================
if not check_password():
    st.stop()

st.sidebar.title("📌 메뉴 선택")
menu = st.sidebar.radio(
    "이동할 메뉴를 선택하세요:",
    ["공고 자동수집", "🔍 실패 로그 분석", "🔗 발주처 URL 관리",
     "공고 통계 및 분석", "🎯 타겟 공고 (내 업무)", "🚫 자동 제외된 공고",
     "🗒️ 전수조사 로그 (AI 분석용)", "📝 게시판 / 메모장"],
)
st.sidebar.divider()

st.sidebar.subheader("🔗 주요 사이트 바로가기")
for site in config.EXTRA_SITES:
    st.sidebar.link_button(site["org_name"], site["url"])
st.sidebar.link_button("🛒 나라장터", "https://www.g2b.go.kr/index.jsp")
st.sidebar.link_button("🏢 대전 동구청 고시공고", "https://www.donggu.go.kr/dg/kor/contents/916")
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
        "자동 탐색이 실패하거나 엉뚱한 페이지를 잡는 발주처는, 여기서 정확한 "
        "게시판 URL을 직접 등록해두면 그 주소로 바로 수집합니다."
    )

    org_list = get_target_org_list()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    default_url_map = site_registry.get_org_default_url_map(base_dir)

    df_url = get_google_sheet(config.SHEET_URL_OVERRIDES)
    override_map = {}
    if not df_url.empty:
        for _, r in df_url.iterrows():
            override_map[str(r.get("발주기관명", ""))] = str(r.get("정확한_게시판_URL", ""))

    tab_edit, tab_add = st.tabs(["✏️ 등록된 발주처 수정", "➕ 새 발주처 추가"])

    with tab_edit:
        picked_org = st.selectbox("발주처 선택:", org_list, key="edit_org_picker")
        current_url = override_map.get(picked_org, default_url_map.get(picked_org, ""))
        st.caption(f"현재 사용 중인 주소: {current_url or '(등록된 주소 없음)'}")

        new_url = st.text_input("새 URL", value=current_url, key="edit_url_input")
        new_note = st.text_input("비고 (선택)", value="", key="edit_note_input")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 이 URL로 저장", use_container_width=True):
                try:
                    _, doc = storage.connect()
                    storage.upsert_url_override(doc, picked_org, new_url, new_note)
                    get_google_sheet.clear()
                    get_target_org_list.clear()
                    st.success(f"✅ '{picked_org}' 직통 URL이 저장되었습니다.")
                except Exception as e:
                    st.error(f"저장 중 오류: {e}")
        with c2:
            if st.button("↩️ 기본값으로 되돌리기 (오버라이드 삭제)", use_container_width=True):
                try:
                    _, doc = storage.connect()
                    storage.delete_url_override(doc, picked_org)
                    get_google_sheet.clear()
                    get_target_org_list.clear()
                    st.success(f"✅ '{picked_org}' 오버라이드가 삭제되었습니다. 명부 기본 URL로 되돌아갑니다.")
                except Exception as e:
                    st.error(f"삭제 중 오류: {e}")

        st.divider()
        st.caption("URL을 저장하신 다음, 여기서 바로 이 발주처 하나만 빠르게 테스트해볼 수 있습니다 (다른 메뉴로 이동할 필요 없음).")
        if st.button("🧪 지금 바로 이 발주처만 테스트", use_container_width=True):
            with st.status(f"🧪 '{picked_org}' 테스트 중...", expanded=True) as status:
                try:
                    process = subprocess.Popen(
                        [sys.executable, "-u", "main.py", "60", ", ".join(config.DEFAULT_KEYWORDS), picked_org, "0"],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                        encoding="utf-8", bufsize=1,
                    )
                    for raw_line in iter(process.stdout.readline, ""):
                        if not raw_line:
                            continue
                        line = raw_line.strip()
                        if not line.startswith("PROGRESS:"):
                            st.write(line)
                    process.wait()
                    if process.returncode == 0:
                        status.update(label=f"✅ '{picked_org}' 테스트 완료 (위 로그에서 결과 확인)", state="complete")
                        get_google_sheet.clear()
                    else:
                        status.update(label="❌ 테스트 실패 (로그 확인)", state="error")
                except Exception as e:
                    status.update(label=f"❌ 시스템 오류: {e}", state="error")
            st.caption("(수집 기간 60일, 기본 키워드로 자동 테스트했습니다 - 나머지 설정은 '공고 자동수집' 화면에서 조정할 수 있습니다.)")

    # ── 탭 2: 명부에 아예 없는 새 발주처를 추가 (코드/엑셀 수정 없이 바로 수집 대상에 포함됨) ──
    with tab_add:
        new_org_name = st.text_input("새 발주처명", key="new_org_name")
        new_org_url = st.text_input("게시판 URL", key="new_org_url")
        new_org_note = st.text_input("비고 (선택)", value="", key="new_org_note")
        if st.button("➕ 새 발주처 추가", type="primary"):
            if not new_org_name.strip() or not new_org_url.strip():
                st.warning("발주처명과 URL을 모두 입력해주세요.")
            else:
                try:
                    _, doc = storage.connect()
                    storage.upsert_url_override(doc, new_org_name.strip(), new_org_url.strip(), new_org_note)
                    get_google_sheet.clear()
                    get_target_org_list.clear()
                    st.success(f"✅ 새 발주처 '{new_org_name}'가 추가되었습니다.")
                except Exception as e:
                    st.error(f"추가 중 오류: {e}")

    st.divider()
    st.subheader(f"📋 현재 등록된 직통 URL 목록 ({len(override_map)}건)")
    if not df_url.empty:
        display_df = df_url.copy()
        display_df.insert(0, "삭제", False)
        edited_df = st.data_editor(
            display_df, use_container_width=True, hide_index=True, key="url_override_editor",
            column_config={
                "삭제": st.column_config.CheckboxColumn("삭제", required=True),
                "정확한_게시판_URL": st.column_config.LinkColumn("정확한_게시판_URL"),
            },
            disabled=[c for c in display_df.columns if c != "삭제"],
        )
        to_delete = edited_df[edited_df["삭제"]]["발주기관명"].tolist()
        if to_delete:
            st.warning(f"선택됨: {', '.join(to_delete)}")
            if st.button("🗑️ 선택한 항목 삭제", type="primary"):
                try:
                    _, doc = storage.connect()
                    for org in to_delete:
                        storage.delete_url_override(doc, org)
                    get_google_sheet.clear()
                    get_target_org_list.clear()
                    st.success(f"✅ {len(to_delete)}건 삭제되었습니다.")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"삭제 중 오류: {e}")
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
        is_g2b_migrated = df_manual["사유"].astype(str).str.contains("나라장터로", na=False)
        st.subheader(f"⚠️ 실제 확인 필요 ({(~is_g2b_migrated).sum()}곳)")
        st.dataframe(df_manual[~is_g2b_migrated], hide_index=True, use_container_width=True)
        with st.expander(f"✅ 정상 (나라장터로 이관/연결됨) - {is_g2b_migrated.sum()}곳"):
            st.dataframe(df_manual[is_g2b_migrated], hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("📜 전체 실행 로그 (run_log)")
    df_log = get_google_sheet(config.SHEET_RUN_LOG)
    if df_log.empty:
        st.info("아직 기록된 로그가 없습니다.")
    else:
        search_term = st.text_input("발주처/오류메시지 검색:", key="log_search")
        show_log = df_log
        if search_term:
            mask = df_log.apply(lambda row: search_term in str(row.values), axis=1)
            show_log = df_log[mask]
        st.dataframe(show_log.iloc[::-1], hide_index=True, use_container_width=True)
        st.download_button(
            "⬇️ CSV로 다운로드",
            show_log.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{datetime.now(KST).strftime('%Y-%m-%dT%H-%M')}_run_log.csv",
        )

# ==========================================
# 공고 자동수집
# ==========================================
elif menu == "공고 자동수집":
    st.title("📋 공고 자동수집")

    col_days, col_kw = st.columns([1, 2])
    with col_days:
        collect_days = st.number_input("🗓️ 수집 기간 (최근 며칠)", min_value=0, max_value=90, value=config.DEFAULT_DAYS_AGO)
    with col_kw:
        collect_keywords = st.text_input("🔑 수집 키워드 (쉼표 구분)", value=", ".join(config.DEFAULT_KEYWORDS))

    scan_mode = st.toggle("🌐 전수조사 (모든 등록 기관 스캔)", value=True)
    selected_orgs_str = "ALL"
    if not scan_mode:
        org_list = get_target_org_list()
        selected_orgs = st.multiselect("탐색할 특정 발주처를 선택하세요:", org_list, placeholder="기관명을 검색하거나 선택하세요...")
        if not selected_orgs:
            st.warning("발주처를 하나 이상 선택해주세요.")
        else:
            selected_orgs_str = ",".join(selected_orgs)

    use_proxy = st.toggle("🧪 무료 프록시로 우회 시도 (실험적, 국내 IP 차단 사이트용)", value=False)

    st.divider()
    col_cloud, col_office = st.columns(2)

    with col_cloud:
        st.subheader("🚀 지금 바로 수집 (클라우드)")
        st.caption("이 화면에서 직접 실행합니다. 실시간 로그가 아래에 표시됩니다.")
        if st.button("🚀 지금 바로 수집 시작", type="primary", use_container_width=True):
            if not scan_mode and selected_orgs_str == "ALL":
                st.error("발주처를 선택해주세요.")
            else:
                try:
                    _, doc = storage.connect()
                except Exception:
                    doc = None
                if doc is not None and storage.manage_sheet_lock(doc, "check"):
                    _render_stuck_lock_warning(doc, "cloud")
                else:
                    progress_bar = st.progress(0)
                    log_box = st.empty()
                    log_lines = []
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
                        if line.startswith("PROGRESS:"):
                            try:
                                done, total = line.split(":")[1:3]
                                progress_bar.progress(min(int(done) / max(int(total), 1), 1.0))
                            except Exception:
                                pass
                        else:
                            log_lines.append(line)
                            log_box.code("\n".join(log_lines[-40:]))
                    process.wait()
                    get_google_sheet.clear()
                    st.success("✅ 수집이 완료되었습니다.")

    with col_office:
        st.subheader("🏢 사무실 PC로 확실하게 수집")
        st.caption("GitHub Actions를 통해 대전 사무실 PC(실제 국내 IP)에서 실행합니다. 비동기로 진행되며, 완료까지 몇 분 걸릴 수 있습니다.")
        if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
            st.info("GITHUB_TOKEN / GITHUB_REPO 시크릿이 설정되지 않아 이 버튼은 비활성화되어 있습니다.")
        else:
            already_running = False
            doc = None
            try:
                _, doc = storage.connect()
                already_running = storage.manage_sheet_lock(doc, "check")
            except Exception:
                already_running = False  # 확인 실패해도 요청 자체는 시도해본다

            if already_running:
                _render_stuck_lock_warning(doc, "office")
            else:
                if st.button("🏢 사무실 PC로 수집 시작", use_container_width=True):
                    if not scan_mode and selected_orgs_str == "ALL":
                        st.error("발주처를 선택해주세요.")
                    else:
                        ok = github_actions.dispatch_workflow(
                            str(collect_days), collect_keywords, selected_orgs_str, "1" if use_proxy else "0")
                        if ok:
                            st.success("✅ 사무실 PC로 실행 요청을 보냈습니다. GitHub Actions에서 진행 상황을 확인하세요.")
                        else:
                            st.error("❌ 요청 전송에 실패했습니다. GITHUB_TOKEN 권한을 확인해주세요.")

            run_info = github_actions.get_latest_run_status()
            if run_info:
                status_kor = {"completed": "완료", "in_progress": "진행 중", "queued": "대기 중"}.get(run_info["status"], run_info["status"])
                conclusion_kor = {"success": "✅ 성공", "failure": "❌ 실패", None: "-"}.get(run_info["conclusion"], run_info["conclusion"])
                st.write(f"**상태**: {status_kor} / {conclusion_kor}  \n**시작 시각**: {run_info['created_at']}")
                st.link_button("GitHub Actions에서 실시간 로그 보기", run_info["html_url"])

    # ── 수집된 공고 실시간 검색/검토 ─────────────────────────────────────────
    # 검색 컨트롤은 사이드바에 둔다 (어느 메뉴에 있든 스크롤 없이 바로 보이도록).
    st.sidebar.divider()
    st.sidebar.subheader("🔍 공고 실시간 검색")
    title_search = st.sidebar.text_input("공고제목 / 특이사항 검색", key="sidebar_title_search")
    org_search = st.sidebar.text_input("발주기관(출처) 검색", key="sidebar_org_search")
    hide_reviewed = st.sidebar.checkbox("✅ 검토 완료된 공고 숨기기", value=True, key="sidebar_hide_reviewed")

    df_notices = get_google_sheet(config.SHEET_NOTICES)
    if not df_notices.empty:
        filtered = df_notices.copy()
        if title_search:
            mask = (filtered["공고제목"].astype(str).str.contains(title_search, case=False, na=False) |
                    filtered["특이사항"].astype(str).str.contains(title_search, case=False, na=False))
            filtered = filtered[mask]
        if org_search:
            filtered = filtered[filtered["출처"].astype(str).str.contains(org_search, case=False, na=False)]
        if hide_reviewed and "검토유무" in filtered.columns:
            filtered = filtered[filtered["검토유무"] == "미검토"]

        st.divider()
        if st.button("✅ 현재 화면 전체 일괄 검토완료"):
            all_keys = filtered["notice_key"].tolist() if "notice_key" in filtered.columns else []
            if all_keys and update_notice_status(all_keys, "내업무아님"):
                get_google_sheet.clear()
                st.rerun()

        # "주요 4대 중앙 공고": EXTRA_SITES 3곳(한국시설안전협회/조달청 통합명부/
        # 아이건설넷) + 나라장터(G2B API 결과는 출처에 "(나라장터)"가 붙어서 옴).
        central_names = [s["org_name"] for s in config.EXTRA_SITES] + ["나라장터"]
        is_central = filtered["출처"].astype(str).apply(lambda x: any(c in x for c in central_names))
        central_df = filtered[is_central]
        general_df = filtered[~is_central]

        st.subheader(f"🌟 주요 4대 중앙 공고 ({len(central_df)}건)")
        if central_df.empty:
            st.info("해당되는 공고가 없습니다.")
        else:
            render_notice_table(central_df, "central_notices")

        st.subheader(f"📋 일반 기관 공고 ({len(general_df)}건)")
        if general_df.empty:
            st.info("해당되는 공고가 없습니다.")
        else:
            render_notice_table(general_df, "general_notices")

# ==========================================
# 공고 통계 및 분석
# ==========================================
elif menu == "공고 통계 및 분석":
    st.title("📊 공고 통계 및 분석 대시보드")
    df = get_google_sheet(config.SHEET_NOTICES)
    if df.empty:
        st.info("아직 수집된 데이터가 없습니다.")
    else:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("전체 공고 수", f"{len(df):,}건")
        col2.metric("고유 발주처 수", f"{df['출처'].nunique():,}곳" if "출처" in df.columns else "-")
        status_counts = df["검토유무"].value_counts() if "검토유무" in df.columns else pd.Series(dtype=int)
        col3.metric("내 업무 맞음", f"{int(status_counts.get('내업무맞음', 0)):,}건")
        col4.metric("미검토", f"{int(status_counts.get('미검토', 0)):,}건")

        st.divider()

        c_left, c_right = st.columns(2)
        with c_left:
            st.subheader("발주처별 공고 건수 Top 15")
            if "출처" in df.columns:
                st.bar_chart(df["출처"].value_counts().head(15))
        with c_right:
            st.subheader("검토 상태 분포")
            if not status_counts.empty:
                st.bar_chart(status_counts)

        st.subheader("날짜별 공고 등록 추이")
        if "등록일" in df.columns:
            dates = pd.to_datetime(df["등록일"], format="%Y.%m.%d", errors="coerce")
            daily = dates.dt.date.value_counts().dropna().sort_index()
            if not daily.empty:
                st.line_chart(daily)
            else:
                st.caption("날짜 형식을 인식하지 못해 추이를 그릴 수 없습니다.")

        st.divider()
        st.subheader("📌 이번 명부 기준 수집 현황 (발주처 단위)")
        try:
            collected_df = get_google_sheet(config.SHEET_COLLECTED_ORGS)
            manual_df = get_google_sheet(config.SHEET_MANUAL_CHECK)
            c1, c2 = st.columns(2)
            c1.metric("✅ 정상 수집 발주처 수", f"{len(collected_df):,}곳")
            c2.metric("🔍 수동확인 필요 발주처 수", f"{len(manual_df):,}곳")
            if not manual_df.empty and "사유" in manual_df.columns:
                st.caption("수동확인 사유별 분류는 '🔍 실패 로그 분석' 화면에서 더 자세히 볼 수 있습니다.")
        except Exception:
            st.caption("발주처 현황 시트를 아직 불러올 수 없습니다.")

# ==========================================
# 🎯 타겟 공고 (내 업무)
# ==========================================
elif menu == "🎯 타겟 공고 (내 업무)":
    st.title("🎯 수동 분류된 '내 업무' 공고 리스트")
    df = get_google_sheet(config.SHEET_NOTICES)
    if not df.empty and "검토유무" in df.columns:
        render_notice_table(df[df["검토유무"] == "내업무맞음"], "target_work")
    else:
        st.info("데이터가 없습니다.")

# ==========================================
# 🚫 자동 제외된 공고
# ==========================================
elif menu == "🚫 자동 제외된 공고":
    st.title("🚫 자동 제외된 공고")
    st.caption(
        "제목에 업무 무관 키워드(공시송달·무연고·견적제출공고·기간제·분묘개장·주민등록·"
        "보상계획·수강생·합격자·임용·모니터링)가 있어서 자동으로 걸러진 공고 목록입니다. "
        "완전히 삭제하지는 않고 여기에 모아두니, 혹시 잘못 걸러진 게 있는지 심심할 때 훑어보세요. "
        "(단, 이 단어가 있어도 '안전점검' 등 핵심 키워드가 함께 있으면 걸러지지 않고 정상 목록에 들어갑니다.)"
    )
    df_excluded = get_google_sheet(config.SHEET_EXCLUDED_NOTICES)
    if df_excluded.empty:
        st.info("아직 자동 제외된 공고가 없습니다.")
    else:
        display_cols = ["출처", "등록일", "공고제목", "제외사유", "상세링크"]
        show_df = df_excluded[[c for c in display_cols if c in df_excluded.columns]].iloc[::-1]
        st.dataframe(
            show_df, hide_index=True, use_container_width=True,
            column_config={"상세링크": st.column_config.LinkColumn("상세링크")},
        )

# ==========================================
# 🗒️ 전수조사 로그 (AI 분석용)
# ==========================================
elif menu == "🗒️ 전수조사 로그 (AI 분석용)":
    st.title("🗒️ 전수조사 로그 (AI 분석용)")
    st.caption(
        "성공/실패 관계없이 이번 실행에서 처리한 사이트 전체를 한 줄씩 기록합니다. "
        "'🔍 실패 로그 분석'에는 실패한 것만 남지만, 여기는 성공한 것까지 다 남아서 "
        "'전체 중 정확히 몇 곳이 어떤 방식으로 됐는지' 전체 그림을 볼 수 있습니다. "
        "맨 아래 텍스트를 통째로 복사해서 AI에게 붙여넣으면 바로 분석을 부탁할 수 있어요."
    )

    df_summary = get_google_sheet(config.SHEET_RUN_SUMMARY)
    df_sites = get_google_sheet(config.SHEET_SITE_RESULTS)

    if df_summary.empty or "실행ID" not in df_summary.columns:
        st.info("아직 기록된 실행이 없습니다. 공고 수집을 한 번 실행한 뒤 다시 확인해주세요.")
    else:
        run_options = df_summary["실행ID"].iloc[::-1].tolist()
        picked_run = st.selectbox("확인할 실행을 고르세요 (최신 실행이 맨 위):", run_options)

        run_summary_row = df_summary[df_summary["실행ID"] == picked_run].iloc[-1]
        if not df_sites.empty and "실행ID" in df_sites.columns:
            run_sites = df_sites[df_sites["실행ID"] == picked_run]
        else:
            run_sites = df_sites.iloc[0:0]

        st.subheader("📌 실행 요약")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("실행위치", run_summary_row.get("실행위치", "-"))
        c2.metric("총 소요시간", f"{run_summary_row.get('총소요시간(초)', '-')}초")
        c3.metric("성공", f"{run_summary_row.get('성공수', 0)}곳")
        c4.metric("실패/수동확인", f"{run_summary_row.get('실패_수동확인수', 0)}곳")
        st.dataframe(run_summary_row.to_frame().T, hide_index=True, use_container_width=True)

        st.subheader(f"📋 사이트별 결과 ({len(run_sites)}건)")
        if run_sites.empty:
            st.info("이 실행에 대한 사이트별 결과가 없습니다 (나라장터/방위사업청만 단독 실행한 경우일 수 있습니다).")
        else:
            st.dataframe(run_sites, hide_index=True, use_container_width=True)

        st.divider()
        st.subheader("📋 AI에게 그대로 붙여넣을 텍스트")
        lines = [f"=== 실행 요약 (ID: {picked_run}) ==="]
        for col in df_summary.columns:
            lines.append(f"{col}: {run_summary_row.get(col, '')}")
        lines.append("")
        lines.append(f"=== 사이트별 결과 ({len(run_sites)}건) ===")
        for _, row in run_sites.iterrows():
            line = (f"[{row.get('결과', '')}] {row.get('발주처', '')} | 방식:{row.get('처리방식', '')} | "
                    f"수집:{row.get('수집건수', '')}건 | 제외:{row.get('제외건수', '')}건 | "
                    f"{row.get('소요시간(초)', '')}초")
            if str(row.get("사유", "")).strip():
                line += f" | 사유: {row.get('사유', '')}"
            lines.append(line)
        st.code("\n".join(lines), language=None)

# ==========================================
# 📝 게시판 / 메모장
# ==========================================
elif menu == "📝 게시판 / 메모장":
    st.title("📝 팀 게시판 및 메모장")
    st.caption("팀원들과 공유할 메모나 특이사항을 남겨두는 공간입니다. 구글시트에 저장되어 접속하는 모두에게 보입니다.")

    try:
        _, doc = storage.connect()
    except storage.SheetUnavailable as e:
        st.error(f"구글 시트 연결 실패: {e}")
        doc = None

    if doc is not None:
        with st.form("new_note_form", clear_on_submit=True):
            author = st.text_input("작성자 (선택)", placeholder="예: 김담당")
            content = st.text_area("새 메모", height=100,
                                    placeholder="예: 이번 주 목요일까지 유성구청 안전점검 건 마감 확인 필요")
            if st.form_submit_button("✍️ 등록", type="primary") and content.strip():
                storage.add_team_note(doc, content.strip(), author.strip())
                get_google_sheet.clear()
                st.rerun()

        st.divider()
        notes_df = get_google_sheet(config.SHEET_TEAM_NOTES)
        if notes_df.empty:
            st.info("아직 작성된 메모가 없습니다.")
        else:
            for _, row in notes_df.iloc[::-1].iterrows():
                with st.container(border=True):
                    st.write(row.get("내용", ""))
                    c1, c2 = st.columns([5, 1])
                    author_label = row.get("작성자", "") or "익명"
                    c1.caption(f"{row.get('시각', '')} · {author_label}")
                    if c2.button("🗑️ 삭제", key=f"del_note_{row.get('id', '')}"):
                        storage.delete_team_note(doc, row.get("id", ""))
                        get_google_sheet.clear()
                        st.rerun()

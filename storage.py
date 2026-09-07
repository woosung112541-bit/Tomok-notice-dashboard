"""
storage.py
------------
구글시트를 데이터 백엔드로 쓰는 모든 읽기/쓰기 로직을 여기 모아둔다.
"""

import json
import time
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials

import config

KST = timezone(timedelta(hours=9))
KEY_FILE_PATH = "google_key.json"
LOCK_STALE_SECONDS = 900  # 15분 - 이보다 오래 'running' 상태면 죽은 잠금으로 간주하고 풀어준다


class SheetUnavailable(Exception):
    pass


def write_key_file_from_secret() -> None:
    """config.GOOGLE_CREDENTIALS(JSON 문자열)를 google_key.json 파일로 저장한다.
    Streamlit Cloud처럼 파일 시스템에 미리 키 파일이 없는 환경에서 필요하다.
    GitHub Actions 쪽은 워크플로우 자체에서 이미 파일을 만들어주므로, 이미 파일이
    있으면 건드리지 않는다."""
    import os
    if os.path.exists(KEY_FILE_PATH):
        return
    if not config.GOOGLE_CREDENTIALS:
        return
    with open(KEY_FILE_PATH, "w", encoding="utf-8") as f:
        f.write(config.GOOGLE_CREDENTIALS)


def connect():
    """구글시트에 연결한다. 반환: (gspread client, 스프레드시트 문서 객체)."""
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(KEY_FILE_PATH, scopes=scopes)
        gc = gspread.authorize(creds)
        doc = gc.open("Tomok-notice-dashboard-data")
        return gc, doc
    except Exception as e:
        raise SheetUnavailable(str(e))


def _get_or_create_worksheet(doc, title: str, headers: list[str] | None = None):
    try:
        ws = doc.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        ws = doc.add_worksheet(title=title, rows=1000, cols=max(len(headers or []), 10))
        if headers:
            ws.append_row(headers)
    return ws


def manage_sheet_lock(doc, action: str, engine_name: str = "통합 엔진") -> bool:
    """settings 탭 A1(상태)/B1(시각)/C1(엔진명)으로 간단한 락을 관리한다.
    action: "check" (현재 잠겨있는지 bool 반환), "lock_and_log" (잠그기), "unlock" (풀기).
    15분 넘게 'running'이면 죽은 락으로 간주하고 자동으로 풀어준다 (GitHub Actions에서
    '취소'를 누르면 프로세스가 강제 종료되면서 unlock 코드가 실행될 기회 없이 죽어서,
    이 안전장치 없이는 영영 잠긴 채로 남는 문제가 있었다)."""
    ws = _get_or_create_worksheet(doc, config.SHEET_SETTINGS, ["status", "locked_at", "engine"])
    values = ws.get_all_values()
    status = values[0][0] if values and len(values[0]) > 0 else "free"
    locked_at_str = values[0][1] if values and len(values[0]) > 1 else ""

    is_stale = False
    if status == "running" and locked_at_str:
        try:
            locked_at = datetime.strptime(locked_at_str, "%Y-%m-%d %H:%M:%S")
            if (datetime.now(KST).replace(tzinfo=None) - locked_at).total_seconds() > LOCK_STALE_SECONDS:
                is_stale = True
        except ValueError:
            is_stale = True

    if action == "check":
        return status == "running" and not is_stale

    if action == "lock_and_log":
        ws.update(range_name="A1:C1", values=[["running", datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), engine_name]])
        return True

    if action == "unlock":
        # A1(status)만 "free"로 바꾸고, B1(시각)/C1(엔진명)은 그대로 남겨둔다 -
        # 이 값들이 대시보드의 "최근 실행" 표시로 계속 쓰이기 때문에, 실행이
        # 끝났다고 지워버리면 "마지막으로 언제 실행했는지"를 알 수 없게 된다.
        ws.update(range_name="A1", values=[["free"]])
        return True

    return False


def load_run_context(doc) -> dict:
    """notices/collected_orgs 워크시트 핸들과, 이미 알고 있는 notice_key 집합(history_keys),
    url_overrides(발주처명 -> URL)를 한 번에 불러온다."""
    ws_notices = _get_or_create_worksheet(
        doc, config.SHEET_NOTICES,
        ["출처", "등록일", "공고제목", "상세링크", "notice_key", "수집시각", "특이사항", "검토유무"])
    ws_collected = _get_or_create_worksheet(doc, config.SHEET_COLLECTED_ORGS, ["발주처", "최근수집시각"])

    history_keys = {str(r.get("notice_key", "")) for r in ws_notices.get_all_records()}

    ws_overrides = _get_or_create_worksheet(doc, config.SHEET_URL_OVERRIDES, ["발주기관명", "정확한_게시판_URL", "비고"])
    url_overrides = {}
    for r in ws_overrides.get_all_records():
        name = str(r.get("발주기관명", "")).strip()
        url = str(r.get("정확한_게시판_URL", "")).strip()
        if name and url:
            url_overrides[name] = url

    return {
        "ws_notices": ws_notices,
        "ws_collected": ws_collected,
        "history_keys": history_keys,
        "url_overrides": url_overrides,
    }


def append_notices(ws_notices, items: list[dict], history_keys: set, current_time: str) -> int:
    """새 공고만 골라 notices 시트에 append. 몇 건 추가됐는지 반환."""
    new_rows = []
    for item in items:
        notice_key = f"{item['출처']}|||{item['공고제목']}"
        if notice_key in history_keys:
            continue
        new_rows.append([
            item["출처"], item["등록일"], item["공고제목"], item["상세링크"],
            notice_key, current_time, item.get("특이사항", "-"), "미검토",
        ])
        history_keys.add(notice_key)
    if new_rows:
        ws_notices.append_rows(new_rows)
    return len(new_rows)


def load_excluded_history_keys(doc) -> set:
    """excluded_notices 탭에 이미 있는 notice_key 집합을 불러온다 (중복 재적재 방지)."""
    ws = _get_or_create_worksheet(doc, config.SHEET_EXCLUDED_NOTICES,
                                   ["출처", "등록일", "공고제목", "상세링크", "notice_key", "수집시각", "특이사항", "제외사유"])
    return {str(r.get("notice_key", "")) for r in ws.get_all_records()}


def append_excluded_notices(doc, items: list[dict], history_keys: set, current_time: str) -> int:
    """제외 키워드에 걸려 별도 분류된 공고를 excluded_notices 탭에 추가한다.
    "🚫 자동 제외된 공고" 메뉴에서 나중에 훑어볼 수 있도록 완전히 버리지 않고 보관한다."""
    headers = ["출처", "등록일", "공고제목", "상세링크", "notice_key", "수집시각", "특이사항", "제외사유"]
    ws = _get_or_create_worksheet(doc, config.SHEET_EXCLUDED_NOTICES, headers)
    new_rows = []
    for item in items:
        notice_key = f"{item['출처']}|||{item['공고제목']}"
        if notice_key in history_keys:
            continue
        matched = [kw for kw in config.EXCLUDE_KEYWORDS if kw in item["공고제목"]]
        new_rows.append([
            item["출처"], item["등록일"], item["공고제목"], item["상세링크"],
            notice_key, current_time, item.get("특이사항", "-"), ", ".join(matched) or "-",
        ])
        history_keys.add(notice_key)
    if new_rows:
        ws.append_rows(new_rows)
    return len(new_rows)


def append_collected_orgs(ws_collected, org_names: set) -> None:
    """이번 실행에서 정상적으로 공고를 수집한 발주처 목록을 기록한다 (최근수집시각 갱신)."""
    if not org_names:
        return
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    existing = ws_collected.get_all_records()
    existing_names = {str(r.get("발주처", "")) for r in existing}
    new_rows = [[name, now_str] for name in org_names if name not in existing_names]
    if new_rows:
        ws_collected.append_rows(new_rows)
    # 이미 있던 발주처는 시각만 갱신 (행 전체를 다시 쓰는 대신, 간단히 재기록)
    updated_names = org_names & existing_names
    if updated_names:
        all_values = ws_collected.get_all_values()
        for i, row in enumerate(all_values[1:], start=2):
            if row and row[0] in updated_names:
                ws_collected.update(range_name=f"B{i}", values=[[now_str]])


def write_manual_check_list(doc, manual_items: list[dict]) -> None:
    """자동화 불가로 판정된 발주처를 manual_check 탭에 최신 상태로 덮어쓴다."""
    headers = ["발주처", "URL", "사유", "최종확인시각"]
    ws = _get_or_create_worksheet(doc, config.SHEET_MANUAL_CHECK, headers)
    if not manual_items:
        return
    rows = [[m.get(h, "") for h in headers] for m in manual_items]
    ws.clear()
    ws.update(range_name="1:1", values=[headers])
    ws.append_rows(rows)


def write_run_log(doc, run_log: list[dict]) -> None:
    """이번 실행에서 쌓인 실패/경고/시스템 로그(utils.logging_setup.RUN_LOG)를
    run_log 탭에 append한다."""
    if not run_log:
        return
    headers = ["시각", "발주처", "URL", "단계", "오류유형", "오류메시지"]
    ws = _get_or_create_worksheet(doc, config.SHEET_RUN_LOG, headers)
    rows = [[r.get(h, "") for h in headers] for r in run_log]
    ws.append_rows(rows)


# ── 팀 게시판 / 메모장 ("📝 게시판 / 메모장" 메뉴용) ────────────────────────────
def add_team_note(doc, content: str, author: str = "") -> None:
    """새 메모를 team_notes 탭에 추가한다. id는 삭제할 때 정확히 그 행만 찾기 위한 값."""
    headers = ["id", "시각", "작성자", "내용"]
    ws = _get_or_create_worksheet(doc, config.SHEET_TEAM_NOTES, headers)
    note_id = str(int(time.time() * 1000))  # 밀리초 타임스탬프 - 같은 팀 규모에서 충돌 걱정 없음
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row([note_id, now, author, content])


def delete_team_note(doc, note_id: str) -> None:
    """id로 정확히 그 메모 한 줄만 찾아서 삭제한다."""
    ws = _get_or_create_worksheet(doc, config.SHEET_TEAM_NOTES, ["id", "시각", "작성자", "내용"])
    try:
        cell = ws.find(str(note_id), in_column=1)
    except gspread.exceptions.CellNotFound:
        cell = None
    if cell:
        ws.delete_rows(cell.row)


# ── "🗒️ 전수조사 로그 (AI 분석용)" - 성공/실패 관계없이 실행 전체를 기록 ─────────────
def write_site_results(doc, run_id: str, run_time: str, site_results: list[dict]) -> None:
    """이번 실행에서 처리한 사이트마다 한 줄씩(성공/실패 관계없이 전부) 남긴다.
    run_log(=실패 로그)와 달리, 성공한 사이트도 다 남는다는 게 핵심 차이점이다."""
    if not site_results:
        return
    headers = ["실행ID", "시각", "발주처", "URL", "처리방식", "결과", "수집건수", "제외건수", "소요시간(초)", "사유"]
    ws = _get_or_create_worksheet(doc, config.SHEET_SITE_RESULTS, headers)
    rows = [[run_id, run_time, r.get("발주처", ""), r.get("URL", ""), r.get("처리방식", ""),
             r.get("결과", ""), r.get("수집건수", 0), r.get("제외건수", 0),
             r.get("소요시간(초)", ""), r.get("사유", "")] for r in site_results]
    ws.append_rows(rows)


def write_run_summary(doc, summary: dict) -> None:
    """실행 1회당 요약 정보를 한 줄 남긴다 (AI에게 통째로 넣기 좋도록 한 화면에
    실행 전체 그림이 다 들어가게 설계함)."""
    headers = [
        "실행ID", "시작시각", "종료시각", "총소요시간(초)", "실행위치",
        "수집기간(일)", "키워드", "대상발주처", "프록시사용",
        "전체사이트수", "성공수", "실패_수동확인수", "신규공고수", "자동제외수",
    ]
    ws = _get_or_create_worksheet(doc, config.SHEET_RUN_SUMMARY, headers)
    ws.append_row([summary.get(h, "") for h in headers])


# ── 발주처 URL 오버라이드 (개별 upsert/삭제 - 대시보드에서 목록으로 관리하기 위함) ──────
def upsert_url_override(doc, org_name: str, url: str, note: str = "") -> None:
    """특정 발주처의 직통 URL을 등록/수정한다. 이미 있으면 그 행만 갱신, 없으면 새로 추가."""
    headers = ["발주기관명", "정확한_게시판_URL", "비고"]
    ws = _get_or_create_worksheet(doc, config.SHEET_URL_OVERRIDES, headers)
    records = ws.get_all_values()
    if not records:
        ws.append_row(headers)
        records = [headers]

    target_row = None
    for i, row in enumerate(records[1:], start=2):
        if row and row[0] == org_name:
            target_row = i
            break

    if target_row:
        ws.update(range_name=f"A{target_row}:C{target_row}", values=[[org_name, url, note]])
    else:
        ws.append_row([org_name, url, note])


def delete_url_override(doc, org_name: str) -> None:
    """특정 발주처의 오버라이드 행을 통째로 삭제한다 (명부 기본 URL로 되돌아감)."""
    ws = _get_or_create_worksheet(doc, config.SHEET_URL_OVERRIDES, ["발주기관명", "정확한_게시판_URL", "비고"])
    try:
        cell = ws.find(org_name, in_column=1)
    except gspread.exceptions.CellNotFound:
        cell = None
    if cell:
        ws.delete_rows(cell.row)

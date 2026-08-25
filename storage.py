"""
storage.py
----------
구글 시트(gspread) 관련 로직을 한 곳에 모은다.
app.py와 main.py 양쪽에서 이 모듈만 사용하고, gspread를 직접 다루지 않는다.

시트 구성 (config.py의 SHEET_* 참고):
  notices        : 수집된 공고 원장
  collected_orgs : 이번까지 한 번이라도 공고가 발견된 발주처 이름 집합
  empty_orgs     : 이번 실행에서 공고가 없었거나 실패한 발주처
  url_overrides  : 담당자가 직접 관리하는 '실제 게시판 직통 URL' 매핑
  settings       : 동시 실행 방지 락 + 최근 실행 기록
  run_log        : (신규) 실행 중 발생한 실패/경고 로그
  manual_check   : (신규) 자동화가 어렵다고 판단되어 수동 확인이 필요한 발주처 목록
"""

import time
from datetime import datetime, timezone, timedelta

import gspread

import config

KST = timezone(timedelta(hours=9))


class SheetUnavailable(Exception):
    """구글 시트에 연결할 수 없을 때 발생시키는 예외. main.py에서 명확히 처리하기 위함."""


def write_key_file_from_secret() -> None:
    """GOOGLE_CREDENTIALS 시크릿이 있으면 google_key.json으로 기록한다.
    (app.py, main.py 양쪽에서 실행 시작 시 한 번 호출)"""
    val = config.get_secret("GOOGLE_CREDENTIALS")
    if val:
        with open(config.GOOGLE_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(val)


def connect():
    """gspread 클라이언트 + 문서 핸들을 반환한다. 실패 시 SheetUnavailable을 발생시킨다."""
    try:
        gc = gspread.service_account(filename=config.GOOGLE_KEY_FILE)
        doc = gc.open(config.GOOGLE_SHEET_NAME)
        return gc, doc
    except Exception as e:
        raise SheetUnavailable(f"구글 시트 연결 실패: {e}") from e


def _get_or_create_worksheet(doc, title: str, headers: list[str] | None = None):
    try:
        return doc.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        ws = doc.add_worksheet(title=title, rows=1000, cols=max(10, len(headers or []) + 2))
        if headers:
            ws.update(range_name="1:1", values=[headers])
        return ws


def load_run_context(doc):
    """수집 실행 전, 중복 방지를 위한 기존 데이터(공고 key, 이미 확인된 발주처, URL 오버라이드)를 불러온다."""
    ws_notices = doc.worksheet(config.SHEET_NOTICES)
    ws_collected = doc.worksheet(config.SHEET_COLLECTED_ORGS)

    existing_notices = ws_notices.get_all_records()
    history_keys = {str(row.get("notice_key", "")) for row in existing_notices}

    existing_collected = ws_collected.get_all_records()
    collected_orgs = {str(row.get("org_name", "")) for row in existing_collected if str(row.get("org_name", ""))}

    url_overrides = {}
    try:
        ws_urls = doc.worksheet(config.SHEET_URL_OVERRIDES)
        for r in ws_urls.get_all_records():
            org = str(r.get("발주기관명", "")).strip()
            url_val = str(r.get("정확한_게시판_URL", "")).strip()
            if org and url_val.startswith("http"):
                url_overrides[org] = url_val
    except Exception:
        pass  # url_overrides 탭이 없어도 정상 동작해야 하므로 여기만 예외적으로 조용히 넘어감

    return {
        "ws_notices": ws_notices,
        "ws_collected": ws_collected,
        "history_keys": history_keys,
        "collected_orgs": collected_orgs,
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


def append_collected_orgs(ws_collected, org_names: set) -> None:
    if not org_names:
        return
    existing = {str(r.get("org_name", "")) for r in ws_collected.get_all_records()}
    rows = [[name] for name in org_names if name not in existing]
    if rows:
        ws_collected.append_rows(rows)


def write_run_log(doc, run_log_entries: list[dict]) -> None:
    """이번 실행에서 발생한 실패/경고 로그를 run_log 탭에 남긴다."""
    if not run_log_entries:
        return
    headers = ["시각", "발주처", "URL", "단계", "오류유형", "오류메시지"]
    ws = _get_or_create_worksheet(doc, config.SHEET_RUN_LOG, headers)
    rows = [[e.get(h, "") for h in headers] for e in run_log_entries]
    ws.append_rows(rows)


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


# ── 대시보드 동시 실행 방지 락 ─────────────────────────────────────────────────
def manage_sheet_lock(doc, action: str = "check", engine_name: str = "") -> bool:
    """
    action: 'check' | 'lock_and_log' | 'unlock'
    settings 시트 A1=상태(free/running), B1=timestamp, A2=마지막 실행 이름, B2=마지막 실행 시각
    """
    try:
        ws = _get_or_create_worksheet(doc, config.SHEET_SETTINGS)
        if ws.cell(1, 1).value is None:
            ws.update(range_name="A1:B1", values=[["free", str(time.time())]])

        if action == "check":
            status = ws.cell(1, 1).value
            timestamp = ws.cell(1, 2).value
            if status == "running":
                # 15분 이상 지나면 죽은 락으로 간주하고 해제 (프로세스가 비정상 종료된 경우 대비)
                if timestamp and time.time() - float(timestamp) > 900:
                    ws.update(range_name="A1:B1", values=[["free", str(time.time())]])
                    return False
                return True
            return False
        elif action == "lock_and_log":
            ws.update(range_name="A1:B2", values=[
                ["running", str(time.time())],
                [engine_name, datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")],
            ])
        elif action == "unlock":
            ws.update(range_name="A1:B1", values=[["free", str(time.time())]])
        return False
    except Exception:
        return False

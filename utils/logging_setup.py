"""
utils/logging_setup.py
-------------------------
실행 로그(run_log)를 위한 유틸리티. log_info/log_failure/log_manual_required/
log_system_note가 RUN_LOG 리스트에 쌓이고, 실행이 끝나면 storage.write_run_log()가
이걸 구글시트에 한꺼번에 기록한다.
"""

import logging
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 이번 실행에서 쌓인 실패/경고/시스템 로그. main.py가 실행 끝에 storage.write_run_log()로
# 한꺼번에 구글시트에 저장한다.
RUN_LOG = []


def _now_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def log_info(message: str) -> None:
    logger.info(message)


def log_failure(org_name: str, url: str, step: str, error) -> None:
    error_type = type(error).__name__ if isinstance(error, Exception) else "Info"
    logger.warning(f"[{org_name}] ({step}) {error_type}: {error} | url={url}")
    RUN_LOG.append({
        "시각": _now_str(),
        "발주처": org_name,
        "URL": url,
        "단계": step,
        "오류유형": error_type,
        "오류메시지": str(error),
    })


def log_manual_required(org_name: str, url: str, reason: str) -> None:
    logger.info(f"[{org_name}] 자동 수집 불가 -> 실패 로그 등록: {reason}")
    RUN_LOG.append({
        "시각": _now_str(),
        "발주처": org_name,
        "URL": url,
        "단계": "manual_required",
        "오류유형": "수동확인",
        "오류메시지": reason,
    })


def log_system_note(category: str, message: str) -> None:
    logger.info(f"[시스템] {message}")
    RUN_LOG.append({
        "시각": _now_str(),
        "발주처": "-",
        "URL": "-",
        "단계": category,
        "오류유형": "시스템",
        "오류메시지": message,
    })

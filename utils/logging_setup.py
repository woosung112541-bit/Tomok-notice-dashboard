"""
utils/logging_setup.py
-----------------------
'침묵의 에러(except: pass)'를 없애기 위한 로깅 유틸.

기존 코드의 가장 큰 문제 중 하나는 스크래핑 실패가 나도 어디서도 기록이 남지 않아
사후에 원인을 추적할 수 없었다는 점이다. 여기서는:

  1) 표준 logging으로 콘솔(=GitHub Actions 로그, Streamlit 실행 로그)에 출력하고
  2) 동시에 RUN_LOG 리스트에 구조화된 형태로 쌓아서
  3) main.py 종료 시 storage.py를 통해 구글시트 'run_log' 탭에 append 할 수 있게 한다.

절대 bare `except: pass`로 예외를 삼키지 말고, 반드시 log_failure()를 호출한다.
"""

import logging
import sys
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("pq_scanner")

# 이번 실행(run) 동안의 구조화된 로그. main.py 종료 시 구글시트로 flush.
RUN_LOG: list[dict] = []


def _now_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def log_info(message: str) -> None:
    logger.info(message)


def log_failure(org_name: str, url: str, stage: str, error: Exception | str) -> None:
    """
    스크래핑 중 실패를 기록한다. bare except 대신 반드시 이 함수를 호출할 것.

    stage 예시: 'fetch'(페이지 요청 실패), 'selenium_load', 'parse_row',
                'file_download', 'custom_flow' 등
    """
    err_type = type(error).__name__ if isinstance(error, Exception) else "Info"
    err_msg = str(error)
    logger.warning(f"[{org_name}] ({stage}) {err_type}: {err_msg} | url={url}")
    RUN_LOG.append({
        "시각": _now_str(),
        "발주처": org_name,
        "URL": url,
        "단계": stage,
        "오류유형": err_type,
        "오류메시지": err_msg[:300],
    })


def log_manual_required(org_name: str, url: str, reason: str) -> None:
    """자동 수집을 포기하고 실패 로그(대시보드 '🔍 실패 로그 분석')에 남길 때 기록."""
    logger.info(f"[{org_name}] 자동 수집 불가 -> 실패 로그 등록: {reason}")
    RUN_LOG.append({
        "시각": _now_str(),
        "발주처": org_name,
        "URL": url,
        "단계": "manual_required",
        "오류유형": "-",
        "오류메시지": reason,
    })


def log_system_note(stage: str, message: str) -> None:
    """실패는 아니지만 나중에 '실패 로그 분석' 화면에서 확인하고 싶은 실행 정보
    (예: 이번 실행에 프록시를 실제로 찾아서 썼는지)를 run_log에 정식으로 남긴다.
    지금까지는 이런 정보가 실행 중 잠깐 뜨는 콘솔 로그에만 남고 사라져서,
    나중에 '이번에 프록시가 진짜 걸렸었나?'를 로그만 보고는 알 수 없었다."""
    logger.info(f"[시스템] {message}")
    RUN_LOG.append({
        "시각": _now_str(),
        "발주처": "시스템",
        "URL": "-",
        "단계": stage,
        "오류유형": "Info",
        "오류메시지": message,
    })

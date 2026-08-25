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
    """자동 수집을 포기하고 '수동 확인'으로 분류할 때 기록."""
    logger.info(f"[{org_name}] 자동 수집 불가 -> 수동 확인 필요: {reason}")
    RUN_LOG.append({
        "시각": _now_str(),
        "발주처": org_name,
        "URL": url,
        "단계": "manual_required",
        "오류유형": "-",
        "오류메시지": reason,
    })

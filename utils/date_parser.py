"""
utils/date_parser.py
-----------------------
텍스트에서 날짜를 찾아내는 유틸리티. 게시판 행 텍스트 안에 여러 개의 날짜 비슷한
문자열이 섞여 있을 수 있어서(번호, 조회수, 등록일, 게재기간의 시작/종료일 등),
정규식으로 날짜 패턴을 다 찾은 다음 그 중 '가장 이른 날짜'를 실제 등록일로
간주한다 (등록일은 항상 마감일/게재종료일보다 이르기 때문).
"""

import re
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# "2026-08-21", "26.08.21", "2026년 08월 21일", "2026/08/21" 등 흔한 표기를 폭넓게 허용.
_DATE_PATTERN = re.compile(r'(20\d{2}|\d{2})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})')


def find_all_dates_in_text(text: str) -> list[datetime]:
    """텍스트 안의 모든 날짜 후보를 찾아 datetime 리스트로 반환한다 (파싱 실패한
    후보는 조용히 건너뛴다)."""
    results = []
    for match in _DATE_PATTERN.finditer(text):
        year_str, month_str, day_str = match.groups()
        try:
            year = int(year_str)
            if year < 100:
                year += 2000
            month = int(month_str)
            day = int(day_str)
            results.append(datetime(year, month, day))
        except ValueError:
            continue
    return results


def find_earliest_date(text: str) -> datetime | None:
    """텍스트 안에서 가장 이른 날짜를 반환한다. 못 찾으면 None."""
    dates = find_all_dates_in_text(text)
    return min(dates) if dates else None

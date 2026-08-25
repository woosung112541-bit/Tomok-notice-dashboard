"""
utils/date_parser.py
---------------------
게시판 한 행(row)의 텍스트 안에서 날짜를 '불도저 스캔'으로 찾아낸다.
(제미나이 원칙 #4: 태그 구조를 따지지 말고, 텍스트 안의 날짜 패턴을 무조건 다 긁는다)

지원 형식 예: 2026-08-25 / 2026.08.25 / 26/08/25 / 2026년 08월 25일
"""

import re
from datetime import datetime

DATE_PATTERN = re.compile(r'(20\d{2}|\d{2})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})')


def find_earliest_date(text: str) -> datetime | None:
    """텍스트에서 발견되는 모든 날짜 중 가장 이른 날짜를 반환한다. 없으면 None."""
    found = []
    for match in DATE_PATTERN.finditer(text):
        y, m, d = match.groups()
        if len(y) == 2:
            y = "20" + y
        try:
            found.append(datetime(int(y), int(m), int(d)))
        except ValueError:
            continue
    return min(found) if found else None


def find_all_dates_in_row(row_texts) -> list[datetime]:
    """BeautifulSoup row.stripped_strings 같은 문자열 이터러블을 받아 날짜 목록을 반환."""
    dates = []
    for text in row_texts:
        d = find_earliest_date(text)
        if d:
            dates.append(d)
    return dates

"""
scrapers/generic_requests.py
-----------------------------
2순위(제미나이 원칙 #3 기준: API > requests > selenium): 자바스크립트 렌더링이 필요 없는
일반적인 지자체/기관 게시판. 빠르고 가볍다. 여기서 0건이 나오면 engine.py가 자동으로
generic_selenium으로 승격시킨다 (조용히 포기하지 않음).
"""

import requests
from bs4 import BeautifulSoup

import config
from scrapers.base import (extract_row_fields, matches_keywords, deep_scan_notice,
                            select_rows, find_next_page_url, page_has_stop_signal)
from utils.logging_setup import log_failure, log_info


def scrape_board(url: str, org_name: str, target_date_limit, keywords: list[str],
                  history_keys: set | None = None) -> tuple[list[dict], int, bool]:
    """
    반환: (수집된 공고 리스트, 발견된 행 개수, 네트워크_접속_실패_여부)
    행 개수를 함께 반환하는 이유: '행은 있는데 조건에 안 맞아서 0건'과
    '애초에 행 자체를 못 찾음(=JS 렌더링 필요 가능성)'을 engine.py가 구분해야 하기 때문.
    네트워크_접속_실패_여부(True)는 타임아웃/연결거부처럼 사이트 자체가 지금 서버 위치에서
    아예 접속이 안 되는 경우로, '수동 확인' 사유를 셀렉터 문제와 다르게 안내하기 위함.

    history_keys : 이미 예전에 저장해둔 notice_key 집합. 페이지네이션을 몇 페이지나
    따라갈지 정할 때 쓴다 - 하루에 공고를 많이 올리는 게시판은 1페이지가 전부 새
    글로만 채워져 있을 수 있으므로, 이미 아는 공고나 수집 기간보다 오래된 공고를
    만날 때까지 계속 다음 페이지로 넘어간다(page_has_stop_signal 참고).
    """
    history_keys = history_keys or set()
    headers = config.REQUEST_HEADERS
    results = []
    all_rows = []
    current_url = url
    visited = {url}

    for page_num in range(1, config.MAX_PAGINATION_SAFETY_CAP + 1):
        try:
            res = requests.get(current_url, headers=headers, verify=False, timeout=config.get_request_timeout_tuple())
            soup = BeautifulSoup(res.text, "html.parser")
            rows = select_rows(soup)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if page_num == 1:
                # 접속 자체가 안 되는 경우 (타임아웃/연결거부): 클라우드/해외 IP를 차단하는
                # 사이트일 가능성이 높음. 셀렉터 문제와 구분해서 로그를 남긴다.
                log_failure(org_name, url, "fetch", f"[네트워크 접속 실패 - IP 차단 가능성] {e}")
                return results, 0, True
            break  # 2페이지 이후 실패는 1페이지 결과라도 살리고 여기서 마무리
        except Exception as e:
            if page_num == 1:
                log_failure(org_name, url, "fetch", e)
                return results, 0, False
            break

        all_rows.extend(rows)

        if not rows or page_has_stop_signal(rows, org_name, target_date_limit, history_keys):
            break  # 이미 아는 지점(또는 수집기간 밖)에 도달 -> 더 갈 필요 없음

        next_url = find_next_page_url(soup, current_url, page_num)
        if not next_url or next_url in visited:
            break
        visited.add(next_url)
        current_url = next_url

    if page_num > 1:
        log_info(f"[{org_name}] 페이지네이션으로 {page_num}페이지까지 확인 후 중단")

    for row in all_rows:
        try:
            fields = extract_row_fields(row, url, target_date_limit)
        except Exception as e:
            log_failure(org_name, url, "parse_row", e)
            continue
        if not fields:
            continue
        if not matches_keywords(fields["title"], keywords):
            continue
        special = deep_scan_notice(fields["link"])
        results.append({
            "출처": org_name, "등록일": fields["date_str"],
            "공고제목": fields["title"], "상세링크": fields["link"],
            "특이사항": special,
        })

    return results, len(all_rows), False

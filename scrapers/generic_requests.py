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
from scrapers.base import extract_row_fields, matches_keywords, deep_scan_notice, select_rows, find_pagination_urls
from utils.logging_setup import log_failure, log_info


def scrape_board(url: str, org_name: str, target_date_limit, keywords: list[str]) -> tuple[list[dict], int, bool]:
    """
    반환: (수집된 공고 리스트, 발견된 행 개수, 네트워크_접속_실패_여부)
    행 개수를 함께 반환하는 이유: '행은 있는데 조건에 안 맞아서 0건'과
    '애초에 행 자체를 못 찾음(=JS 렌더링 필요 가능성)'을 engine.py가 구분해야 하기 때문.
    네트워크_접속_실패_여부(True)는 타임아웃/연결거부처럼 사이트 자체가 지금 서버 위치에서
    아예 접속이 안 되는 경우로, '수동 확인' 사유를 셀렉터 문제와 다르게 안내하기 위함.
    """
    headers = config.REQUEST_HEADERS
    results = []
    all_rows = []
    try:
        res = requests.get(url, headers=headers, verify=False, timeout=config.REQUEST_TIMEOUT_TUPLE)
        soup = BeautifulSoup(res.text, "html.parser")
        rows = select_rows(soup)
        all_rows.extend(rows)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        # 접속 자체가 안 되는 경우 (타임아웃/연결거부): 클라우드/해외 IP를 차단하는 사이트일 가능성이 높음.
        # 셀렉터 문제와 구분해서 로그를 남긴다.
        log_failure(org_name, url, "fetch", f"[네트워크 접속 실패 - IP 차단 가능성] {e}")
        return results, 0, True
    except Exception as e:
        log_failure(org_name, url, "fetch", e)
        return results, 0, False

    # 하루에 공고를 많이 올리는 게시판은 1페이지만 보면 최근 것도 이미 2페이지로
    # 밀려나 있을 수 있다. 1페이지에 페이지 번호 링크가 보이면 몇 페이지 더 따라간다.
    extra_page_urls = find_pagination_urls(soup, url)
    if extra_page_urls:
        log_info(f"[{org_name}] 페이지네이션 감지 - 추가로 {len(extra_page_urls)}페이지 더 확인")
        for page_url in extra_page_urls:
            try:
                page_res = requests.get(page_url, headers=headers, verify=False, timeout=config.REQUEST_TIMEOUT_TUPLE)
                page_soup = BeautifulSoup(page_res.text, "html.parser")
                all_rows.extend(select_rows(page_soup))
            except Exception as e:
                log_failure(org_name, page_url, "fetch_pagination", e)

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

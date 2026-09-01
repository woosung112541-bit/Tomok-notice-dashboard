"""
scrapers/custom/d2b.py
------------------------
방위사업청 국방전자조달시스템(D2B) 전용 핸들러.

이 사이트는 일반 HTML 게시판이 아니라, 검색 화면에서 POST로 JSON 데이터를 받아오는
방식이다 (브라우저 개발자도구 Network 탭으로 실제 요청/응답을 직접 확인해서 만들었다).
세션 쿠키가 필요해서, 먼저 목록 화면을 한 번 GET해서 쿠키를 받은 다음 그 쿠키로
검색 API를 POST한다.

핵심 발견 (실제 화면으로 확인):
1) 기본 화면은 '개찰일자'(입찰이 열리는 미래 날짜) 기준으로 정렬되고 전체 건수가
   400건이 넘는다. 일반적인 '최신 등록순 페이지네이션 후 중지' 방식으로는 원하는
   키워드가 있는 공고가 있어도 뒤쪽 페이지에 흩어져 있어서 찾기 어렵다.
2) 대신 이 사이트 자체의 '입찰건명' 검색 기능(anmt_name 파라미터)을 그대로
   활용해서, 우리가 찾는 키워드 각각으로 직접 검색해 필요한 것만 가져온다.
3) 응답 JSON의 'rpstItnm'이 제목, 'anmtDate2'가 실제 공고일자(YYYYMMDD),
   'codeVld3'가 실제 발주부대명(예: 제7보병사단, 해군군수사령부 등)이다.
4) 개별 공고로 바로 가는 직통 링크는 못 찾았다 (JS로 상세 팝업을 띄우는 방식으로
   보임) - 상세링크는 일단 검색 목록 화면 자체로 채워둔다.
"""

import urllib.parse
from datetime import datetime, timezone, timedelta

import requests

from scrapers.base import is_excluded_title, matches_positive_keywords
from utils.logging_setup import log_failure, log_info

KST = timezone(timedelta(hours=9))

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}


def scrape(url: str, org_name: str, target_date_limit, keywords: list[str]) -> tuple[list[dict], list[dict]]:
    results = []
    excluded_results = []
    seen_keys = set()

    entry_url = url
    api_url = urllib.parse.urljoin(entry_url, "getServiceBidAnnounceListNew.json")
    headers = {**REQUEST_HEADERS, "Referer": entry_url}

    session = requests.Session()
    try:
        # 1) 목록 화면을 먼저 열어서 세션 쿠키(JSESSIONID 등)를 받는다 - 쿠키 없이
        # 바로 API를 부르면 서버가 거부한다.
        session.get(entry_url, headers=headers, timeout=15, verify=False)
    except Exception as e:
        log_failure(org_name, entry_url, "d2b_session", e)
        return results, excluded_results

    now = datetime.now(KST)
    # 이 사이트 날짜 필터는 '개찰일자'(입찰이 열리는 미래 날짜) 기준이라, 우리가
    # 원하는 '최근에 게시된 공고'와는 의미가 다르다. 넉넉하게(과거 30일~미래 90일)
    # 잡아서 서버 쪽에서는 큰 그물로만 거르고, 실제 '최근 게시 여부' 판단은 아래에서
    # anmtDate2(공고일자)로 직접 한다.
    date_from = (now - timedelta(days=30)).strftime("%Y%m%d")
    date_to = (now + timedelta(days=90)).strftime("%Y%m%d")

    # 이 사이트는 '입찰건명' 검색어를 한 번에 하나만 받으므로, 우리가 찾는 키워드
    # 각각으로 따로 검색해서 합친다.
    for kw in (keywords or [""]):
        payload = {
            "date_divs": "1", "date_from": date_from, "date_to": date_to,
            "search_divs": "", "anmt_divs": "", "dprt_name": "", "dprt_code": "",
            "edix_gtag": "", "anmt_name": kw, "numb_divs": "1", "lice_code": "",
            "lice_name": "", "area_name": "", "search_numb": "", "currentPageNo": "1",
        }
        try:
            res = session.post(api_url, data=payload, headers=headers, timeout=20, verify=False)
            data = res.json()
        except Exception as e:
            log_failure(org_name, api_url, "d2b_fetch", f"[검색어: {kw}] {e}")
            continue

        items = data.get("list", [])
        log_info(f"[방위사업청] '{kw}' 검색 -> {len(items)}건 수신")

        for item in items:
            title = item.get("rpstItnm", "")
            if not title or not matches_positive_keywords(title, keywords):
                continue

            date_str = item.get("anmtDate2") or item.get("anmtDate") or ""
            try:
                post_date = datetime.strptime(date_str, "%Y%m%d")
            except ValueError:
                continue
            if post_date < target_date_limit:
                continue

            unit_name = str(item.get("codeVld3", "")).strip() or org_name
            dedup_key = (unit_name, title)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            item_row = {
                "출처": f"{unit_name} (방위사업청 D2B)",
                "등록일": post_date.strftime("%Y.%m.%d"),
                "공고제목": title,
                "상세링크": entry_url,  # 개별 공고 직통 링크를 못 찾아 검색 화면으로 대체
                "특이사항": "-",
            }
            if is_excluded_title(title):
                excluded_results.append(item_row)
            else:
                results.append(item_row)

    return results, excluded_results

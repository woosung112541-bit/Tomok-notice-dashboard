"""
scrapers/api_g2b.py
---------------------
1순위(제미나이 원칙 #3): 공식 Open API가 있는 나라장터는 화면을 긁지 않고 API를 쓴다.

조달청_입찰공고정보서비스 OPEN API(BidPublicInfoService02) 규격에 맞춰:
1. BASE_URL 및 5개 오퍼레이션명 뒤에 '02' 적용
2. '입력범위값 초과 에러(07)' 방지를 위해 조회 기간(days_ago)을 5일 단위로 분할 호출
3. nkoneps.com.response.ResponseError 및 response.header 에러 코드 상세 로깅
"""

from datetime import datetime, timezone, timedelta
from urllib.parse import unquote

import requests

from scrapers.base import deep_scan_notice, is_excluded_title
from utils.logging_setup import log_failure, log_system_note

KST = timezone(timedelta(hours=9))

BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService02"

ENDPOINTS = [
    "getBidPblancListInfoCnstwk02",  # 공사
    "getBidPblancListInfoServc02",   # 용역
    "getBidPblancListInfoThng02",    # 물품
    "getBidPblancListInfoFrgcpt02",  # 외자
    "getBidPblancListInfoEtc02",     # 기타공고
]

# 02 버전의 조회기간 입력범위 초과(resultCode 07) 방지를 위한 분할 단위(일)
MAX_CHUNK_DAYS = 5


def _build_date_chunks(now: datetime, days_ago: int) -> list[tuple[str, str]]:
    """days_ago 기간을 MAX_CHUNK_DAYS(5일) 단위의 (시작일시, 종료일시) 튜플 리스트로 분할"""
    total_start = (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)
    total_end = now.replace(hour=23, minute=59, second=0, microsecond=0)

    chunks = []
    cur_start = total_start
    while cur_start <= total_end:
        cur_end = min(
            cur_start + timedelta(days=MAX_CHUNK_DAYS - 1, hours=23, minutes=59),
            total_end,
        )
        chunks.append((cur_start.strftime("%Y%m%d%H%M"), cur_end.strftime("%Y%m%d%H%M")))
        cur_start = (cur_end + timedelta(minutes=1)).replace(hour=0, minute=0)
    return chunks


def fetch(api_key: str, days_ago: int) -> tuple[list[dict], list[dict]]:
    """반환: (수집된 공고 리스트, 제외 키워드에 걸려 별도 분류된 공고 리스트)"""
    if not api_key:
        log_failure("나라장터", "-", "config", "G2B_API_KEY 시크릿이 설정되지 않음")
        return [], []

    api_key = unquote(api_key)
    now = datetime.now(KST)
    date_chunks = _build_date_chunks(now, days_ago)

    results = []
    excluded_results = []
    seen = set()

    for endpoint in ENDPOINTS:
        url = f"{BASE_URL}/{endpoint}"
        endpoint_count = 0

        for start_dt, end_dt in date_chunks:
            params = {
                "serviceKey": api_key,
                "numOfRows": "500",
                "pageNo": "1",
                "inqryDiv": "1",
                "inqryBgnDt": start_dt,
                "inqryEndDt": end_dt,
                "type": "json",
            }
            try:
                res = requests.get(url, params=params, timeout=30)
                if res.status_code != 200:
                    log_failure("나라장터", url, "fetch", f"HTTP {res.status_code} - {res.text[:300]}")
                    continue

                data = res.json()
                if "response" not in data:
                    log_failure("나라장터", url, "api_raw_error", f"({start_dt}~{end_dt}) 응답원문: {res.text[:300]}")
                    continue

                header = data.get("response", {}).get("header", {})
                if header.get("resultCode") != "00":
                    log_failure(
                        "나라장터",
                        url,
                        "api_error",
                        f"({start_dt}~{end_dt}) [{header.get('resultCode')}] {header.get('resultMsg')}",
                    )
                    continue

                raw_items = data.get("response", {}).get("body", {}).get("items")
                if not raw_items:
                    items = []
                elif isinstance(raw_items, dict):
                    items = raw_items.get("item", [])
                    if isinstance(items, dict):
                        items = [items]
                elif isinstance(raw_items, list):
                    items = raw_items
                else:
                    items = []

            except Exception as e:
                raw_text = res.text[:300] if "res" in locals() else "응답없음"
                log_failure("나라장터", url, "fetch", f"{e} | 응답원문: {raw_text}")
                continue

            endpoint_count += len(items)

            for item in items:
                title = item.get("bidNtceNm", "")
                if not title:
                    continue

                org = item.get("dmdInsttNm", "조달청")
                dedup_key = (org, title)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                region = item.get("prtcptPosblRgnNm", "")
                quelfc = item.get("bidQuelfcCdNm", "")
                link = item.get("bidNtceDtlUrl", "")

                special_parts = []
                api_specials = []
                if region:
                    api_specials.append(f"지역제한({region})")
                if quelfc:
                    api_specials.append("자격제한(상세확인)")
                if api_specials:
                    special_parts.append("🔥 " + ", ".join(api_specials))

                deep_special = deep_scan_notice(link) if link else "-"
                if deep_special != "-":
                    special_parts.append(deep_special)

                item_row = {
                    "출처": f"{org} (나라장터)",
                    "등록일": item.get("bidNtceDt", "")[:10].replace("-", "."),
                    "공고제목": title,
                    "상세링크": link,
                    "특이사항": " / ".join(special_parts) if special_parts else "-",
                }
                if is_excluded_title(title):
                    excluded_results.append(item_row)
                else:
                    results.append(item_row)

        log_system_note("g2b_endpoint", f"{endpoint}: {endpoint_count}건 수신")

    return results, excluded_results

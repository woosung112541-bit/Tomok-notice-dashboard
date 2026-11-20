"""
scrapers/api_g2b.py
---------------------
1순위(제미나이 원칙 #3): 공식 Open API가 있는 나라장터는 화면을 긁지 않고 API를 쓴다.
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


def fetch(api_key: str, days_ago: int) -> tuple[list[dict], list[dict]]:
    """반환: (수집된 공고 리스트, 제외 키워드에 걸려 별도 분류된 공고 리스트)"""
    if not api_key:
        log_failure("나라장터", "-", "config", "G2B_API_KEY 시크릿이 설정되지 않음")
        return [], []

    api_key = unquote(api_key)

    now = datetime.now(KST)
    end_dt = now.strftime("%Y%m%d2359")
    start_dt = (now - timedelta(days=days_ago)).strftime("%Y%m%d0000")

    results = []
    excluded_results = []
    seen = set()

    for endpoint in ENDPOINTS:
        url = f"{BASE_URL}/{endpoint}"
        params = {
            "serviceKey": api_key,
            "numOfRows": "999",
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
                log_failure("나라장터", url, "api_raw_error", f"응답원문: {res.text[:300]}")
                continue

            header = data.get("response", {}).get("header", {})
            if header.get("resultCode") != "00":
                log_failure(
                    "나라장터",
                    url,
                    "api_error",
                    f"[{header.get('resultCode')}] {header.get('resultMsg')}",
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

        log_system_note("g2b_endpoint", f"{endpoint}: {len(items)}건 수신")

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

    return results, excluded_results

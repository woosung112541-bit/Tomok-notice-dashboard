"""
scrapers/api_g2b.py
---------------------
1순위(제미나이 원칙 #3): 공식 Open API가 있는 나라장터는 화면을 긁지 않고 API를 쓴다.
"""

from datetime import datetime, timezone, timedelta
from urllib.parse import unquote

import requests

from scrapers.base import deep_scan_notice
from utils.logging_setup import log_failure

KST = timezone(timedelta(hours=9))

ENDPOINTS = [
    "getFcltyBidPblancListInfoServc",
    "getServcBidPblancListInfoServc",
    "getBidPblancListInfoServc",
]


def fetch(api_key: str, days_ago: int, keywords: list[str]) -> list[dict]:
    if not api_key:
        log_failure("나라장터", "-", "config", "G2B_API_KEY 시크릿이 설정되지 않음")
        return []

    # 공공데이터포털(data.go.kr) 서비스키를 'Encoding' 버전으로 저장해두면,
    # requests가 params로 넘길 때 다시 한 번 URL 인코딩을 해서 '%'가 이중으로 인코딩되고
    # 서버가 HTTP 400(잘못된 요청)으로 거부한다. 이미 인코딩된 키를 넣었더라도
    # 한 번 디코딩해서 넘기면 정상 동작한다 (디코딩 키를 넣은 경우는 그대로 통과됨).
    api_key = unquote(api_key)

    now = datetime.now(KST)
    end_dt = now.strftime("%Y%m%d2359")
    start_dt = (now - timedelta(days=days_ago)).strftime("%Y%m%d0000")

    results = []
    seen = set()

    for endpoint in ENDPOINTS:
        url = f"http://apis.data.go.kr/1230000/BidPublicInfoService04/{endpoint}"
        params = {
            "serviceKey": api_key, "numOfRows": "999", "pageNo": "1",
            "inqryDiv": "1", "inqryBgnDt": start_dt, "inqryEndDt": end_dt, "type": "json",
        }
        try:
            res = requests.get(url, params=params, timeout=30)
            if res.status_code != 200:
                log_failure("나라장터", url, "fetch", f"HTTP {res.status_code} - {res.text[:200]}")
                continue
            items = res.json().get("response", {}).get("body", {}).get("items", [])
        except Exception as e:
            log_failure("나라장터", url, "fetch", e)
            continue

        for item in items:
            title = item.get("bidNtceNm", "")
            if keywords and not any(kw in title for kw in keywords):
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

            results.append({
                "출처": f"{org} (나라장터)",
                "등록일": item.get("bidNtceDt", "")[:10].replace("-", "."),
                "공고제목": title,
                "상세링크": link,
                "특이사항": " / ".join(special_parts) if special_parts else "-",
            })

    return results

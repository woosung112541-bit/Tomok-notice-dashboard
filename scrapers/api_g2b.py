"""
scrapers/api_g2b.py
---------------------
1순위(제미나이 원칙 #3): 공식 Open API가 있는 나라장터는 화면을 긁지 않고 API를 쓴다.

업무구분(물품/용역/공사/외자 + 기타공고) 5가지 오퍼레이션을 모두 호출한다. 예전에는
잘못된 주소(BidPublicInfoService04, /ad/ 경로 누락)와 지어낸 오퍼레이션명을 쓰고
있어서 전부 "NO_OPENAPI_SERVICE_ERROR"로 실패하고 있었다 - 공공데이터포털의 실제
'활용신청 상세기능정보' 화면에서 정확한 End Point와 오퍼레이션명을 확인해서 바로잡음.

키워드 필터는 적용하지 않는다 (사용자 결정: "키워드 없이 전부 수집, 대신 대시보드
에서 검색해서 보기"). 나라장터 정식 입찰공고 제목은 게시판 공지 제목과 달리
"OO 교량 정밀안전진단 용역"처럼 실제 사업명이라 "모집" 같은 게시판용 키워드가
애초에 거의 안 맞는다 - 잘못 거르느니 전부 가져와서 대시보드 검색으로 보게 한다.
"""

from datetime import datetime, timezone, timedelta
from urllib.parse import unquote

import requests

from scrapers.base import deep_scan_notice
from utils.logging_setup import log_failure, log_system_note

KST = timezone(timedelta(hours=9))

# 공공데이터포털 '활용신청 상세기능정보' 화면에서 직접 확인한 실제 End Point.
# (예전 코드는 http://apis.data.go.kr/1230000/BidPublicInfoService04/ 를 썼는데,
#  이 주소 자체가 존재하지 않아서 5개 오퍼레이션 전부 실패하고 있었다.)
BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"

# 마찬가지로 화면에서 직접 확인한 정확한 오퍼레이션명 (업무구분별 입찰공고목록조회 4개
# + 어디에도 안 맞는 공고를 담는 '기타공고조회' 1개, 총 5개).
ENDPOINTS = [
    "getBidPblancListInfoCnstwk",  # 공사
    "getBidPblancListInfoServc",   # 용역
    "getBidPblancListInfoThng",    # 물품
    "getBidPblancListInfoFrgcpt",  # 외자
    "getBidPblancListInfoEtc",     # 기타공고 (4개 업무구분에 안 맞는 나머지)
]


def fetch(api_key: str, days_ago: int) -> list[dict]:
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
        url = f"{BASE_URL}/{endpoint}"
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

            results.append({
                "출처": f"{org} (나라장터)",
                "등록일": item.get("bidNtceDt", "")[:10].replace("-", "."),
                "공고제목": title,
                "상세링크": link,
                "특이사항": " / ".join(special_parts) if special_parts else "-",
            })

    return results

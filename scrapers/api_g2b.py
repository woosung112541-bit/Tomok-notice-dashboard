"""
scrapers/api_g2b.py
---------------------
1순위(제미나이 원칙 #3): 공식 Open API가 있는 나라장터는 화면을 긁지 않고 API를 쓴다.

업무구분(물품/용역/공사/외자) 4가지 오퍼레이션을 모두 호출한다. 예전에는 시설공사/
용역/일반 3개만 있어서 물품·외자 공고가 통째로 빠져 있었다.

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

# "getFcltyBidPblancListInfoServc"(시설공사), "getServcBidPblancListInfoServc"(용역),
# "getBidPblancListInfoServc"(일반/공사)는 기존에 실제로 동작이 확인된 오퍼레이션이다.
# "getThngBidPblancListInfoServc"(물품), "getFrgcptBidPblancListInfoServc"(외자)는
# 같은 명명 규칙(get + 업무구분 + BidPblancListInfoServc)에 따라 새로 추가한 것으로,
# 아직 실제 응답을 확인하지 못했다. 혹시 정확한 오퍼레이션명이 아니어서 실패해도
# 아래 for문이 사이트별로 개별 실패 처리를 하므로 나머지 3개는 정상 동작한다 -
# 실행 로그의 "나라장터" 관련 줄에서 이 두 개가 성공했는지 확인해달라.
ENDPOINTS = [
    "getFcltyBidPblancListInfoServc",   # 시설공사
    "getServcBidPblancListInfoServc",   # 용역
    "getBidPblancListInfoServc",        # 일반(공사 등)
    "getThngBidPblancListInfoServc",    # 물품 (신규 추가, 검증 필요)
    "getFrgcptBidPblancListInfoServc",  # 외자 (신규 추가, 검증 필요)
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

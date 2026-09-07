"""
utils/proxy.py
----------------
무료 공개 프록시를 통해 요청을 우회시키는 기능 (토글로 켜고 끌 수 있음).

⚠️ 정직하게 밝혀두는 한계
- 여기서 쓰는 프록시는 전부 '무료 공개 프록시'다. 실제 가정집 회선이 아니라
  대부분 데이터센터/오픈릴레이 서버라서, 지금 우리가 막히고 있는 이유
  ('클라우드/데이터센터 IP 차단')와 똑같은 이유로 이 프록시들도 막힐 수 있다.
  즉 켠다고 100% 해결되지는 않는다.
- 무료 프록시는 수명이 매우 짧다(몇 분~몇 시간 단위로 죽는다). 그래서 매번
  실행할 때마다 새로 목록을 받아와서, 그 순간 살아있는 걸 하나 골라 쓰는
  방식으로만 동작한다. 어떤 실행에선 되고 어떤 실행에선 하나도 안 잡힐 수 있다.
- 정말 안정적으로 필요하다면(특히 대전 지역처럼 중요도가 높은 경우), 회사
  사무실 회선에 GitHub Actions 셀프호스팅 러너를 두는 쪽이 훨씬 신뢰도가
  높다 (README 참고) — 그건 '진짜' 대전 IP라서 프록시보다 확실하다.
"""

import requests

import config
from utils.logging_setup import log_info, log_failure


def _fetch_candidate_proxies() -> list[str]:
    """무료 프록시 목록 제공 사이트(ProxyScrape)에서 한국(KR) IP 후보를 받아온다."""
    try:
        res = requests.get(config.FREE_PROXY_API_URL, timeout=10)
        lines = [line.strip() for line in res.text.splitlines() if line.strip() and ":" in line]
        return lines[:config.PROXY_CANDIDATES_LIMIT]
    except Exception as e:
        log_failure("프록시", config.FREE_PROXY_API_URL, "proxy_fetch", e)
        return []


def _test_proxy(proxy: str) -> bool:
    """실제로 그 프록시를 통해 사이트에 접속해봐서 살아있는지 확인한다."""
    try:
        res = requests.get(
            config.PROXY_TEST_URL,
            proxies={"http": f"http://{proxy}", "https": f"http://{proxy}"},
            timeout=config.PROXY_TEST_TIMEOUT,
        )
        return res.status_code == 200
    except Exception:
        return False


def pick_working_proxy() -> str | None:
    """살아있는 프록시 하나를 찾아 'ip:port' 형태로 반환한다. 하나도 못 찾으면 None."""
    candidates = _fetch_candidate_proxies()
    log_info(f"[프록시] 무료 국내(KR) 프록시 후보 {len(candidates)}개 수신 - 살아있는지 확인 중...")
    for proxy in candidates:
        if _test_proxy(proxy):
            log_info(f"[프록시] 사용 가능한 프록시 발견: {proxy} (이번 실행은 이 프록시를 통해 우회)")
            return proxy
    log_info("[프록시] 살아있는 무료 프록시를 찾지 못함 - 프록시 없이 그대로 진행합니다.")
    return None

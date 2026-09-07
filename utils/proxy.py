"""
utils/proxy.py
-----------------
무료 공개 프록시(ProxyScrape) 중 한국(KR) IP를 찾아서 실제로 살아있는지
naver.com으로 테스트한 뒤, 살아있는 것 하나를 골라 반환한다. 클라우드에서
국내 IP 차단 사이트를 우회해볼 때 쓰는 실험적 기능이다 (성공 보장 안 됨).
"""

import requests

import config
from utils.logging_setup import log_system_note


def _test_proxy(proxy_url: str) -> bool:
    try:
        res = requests.get(
            "https://www.naver.com",
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=5,
        )
        return res.status_code == 200
    except Exception:
        return False


def pick_working_proxy() -> str | None:
    """ProxyScrape 무료 API에서 KR 프록시 목록을 받아, 실제로 살아있는 첫 번째
    프록시를 'http://ip:port' 형태로 반환한다. 없으면 None."""
    try:
        res = requests.get(config.FREE_PROXY_API_URL, timeout=10)
        candidates = [line.strip() for line in res.text.splitlines() if line.strip()]
    except Exception as e:
        log_system_note("proxy_status", f"프록시 목록 조회 실패: {e}")
        return None

    for candidate in candidates[:20]:  # 너무 오래 걸리지 않도록 상위 일부만 시도
        proxy_url = f"http://{candidate}"
        if _test_proxy(proxy_url):
            log_system_note("proxy_status", f"프록시 사용함: {candidate}")
            return proxy_url

    log_system_note("proxy_status", "살아있는 프록시를 못 찾음")
    return None

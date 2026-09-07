"""
site_registry.py
-------------------
등록명부 엑셀 + config.EXTRA_SITES + 구글시트 url_overrides를 합쳐서, 실제로
수집을 돌릴 사이트 목록을 만든다.

각 사이트에는 handler_type을 부여한다:
  - 'custom'   : config.CUSTOM_HANDLER_DOMAINS에 등록된 도메인 (예: khnp.co.kr, igunsul.net, d2b.go.kr)
  - 'generic'  : 그 외 모든 사이트 (requests -> selenium 자동 승격)
"""

import os
import urllib.parse

import pandas as pd

import config


def _load_sites_from_excel(base_dir: str) -> list[dict]:
    """등록명부 엑셀을 읽어서 [{"org_name":..., "url":...}] 리스트로 반환."""
    path = os.path.join(base_dir, config.INPUT_EXCEL_FILENAME)
    df = pd.read_excel(path, sheet_name=0)
    sites = []
    for _, row in df.iterrows():
        org_name = row.iloc[config.ORG_NAME_COL_INDEX]
        url = row.iloc[config.URL_COL_INDEX]
        if pd.isna(org_name) or pd.isna(url):
            continue
        sites.append({"org_name": str(org_name).strip(), "url": str(url).strip()})
    return sites


def _handler_type_for(domain: str) -> str:
    for known_domain in config.CUSTOM_HANDLER_DOMAINS:
        if known_domain in domain:
            return "custom"
    return "generic"


def get_org_default_url_map(base_dir: str) -> dict[str, str]:
    """발주처명 -> 명부/고정목록 상의 기본 URL. 대시보드에서 오버라이드 입력 전
    '원래 등록된 주소가 뭐였는지' 보여주기 위한 용도."""
    sites = _load_sites_from_excel(base_dir) + list(config.EXTRA_SITES)
    return {s["org_name"]: s["url"] for s in sites}


def build_target_sites(base_dir: str, url_overrides: dict[str, str],
                        target_orgs: str = "ALL") -> list[dict]:
    """
    base_dir      : 등록명부 엑셀이 있는 디렉터리
    url_overrides : storage.load_run_context()가 구글시트에서 읽어온 {발주기관명: URL}
    target_orgs   : "ALL" 또는 "기관A,기관B" 형태의 콤마 구분 문자열 (부분 조사용)
    """
    sites = _load_sites_from_excel(base_dir) + [dict(s) for s in config.EXTRA_SITES]

    # url_overrides에만 있고 명부/EXTRA_SITES 어디에도 없는 새 발주처는 새 항목으로 추가
    # ("➕ 새 발주처 추가"로만 등록된 곳들 - 예: 방위사업청)
    known_names = {s["org_name"] for s in sites}
    for org_name, url in url_overrides.items():
        if org_name not in known_names:
            sites.append({"org_name": org_name, "url": url})

    # 오버라이드 적용 (기존 명부 URL을 사용자가 직접 고친 주소로 교체)
    for site in sites:
        if site["org_name"] in url_overrides:
            site["url"] = url_overrides[site["org_name"]]

    if target_orgs != "ALL":
        wanted = {o.strip() for o in target_orgs.split(",") if o.strip()}
        sites = [s for s in sites if s["org_name"] in wanted]

    for site in sites:
        site["domain"] = urllib.parse.urlparse(site["url"]).netloc
        site["handler_type"] = _handler_type_for(site["domain"])

    return sites

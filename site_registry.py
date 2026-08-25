"""
site_registry.py
-----------------
'어떤 발주처를, 어떤 URL로, 어떤 방식으로' 수집할지를 결정하는 단일 지점.

우선순위:
  1) 등록명부 엑셀의 '링크' 열 (기본 URL)
  2) 구글시트 url_overrides 탭에 담당자가 직접 등록한 '실제 게시판 직통 URL' (있으면 위를 덮어씀)
  3) EXTRA_SITES (조달청 통합명부, 한국시설안전협회, 아이건설넷 등 고정 사이트)

각 사이트에는 handler_type을 부여한다:
  - 'custom'   : config.CUSTOM_HANDLER_DOMAINS에 등록된 도메인 (예: khnp.co.kr, igunsul.net)
  - 'generic'  : 그 외 전부. engine.py에서 requests -> 실패 시 selenium 순으로 자동 시도.
"""

import os
from urllib.parse import urlparse

import pandas as pd

import config
from utils.logging_setup import log_failure


def get_domain(url: str) -> str:
    try:
        return urlparse(str(url)).netloc
    except Exception:
        return ""


def _handler_type_for(domain: str) -> str:
    for known_domain in config.CUSTOM_HANDLER_DOMAINS:
        if known_domain in domain:
            return "custom"
    return "generic"


def _load_sites_from_excel(base_dir: str) -> list[dict]:
    excel_path = os.path.join(base_dir, config.INPUT_EXCEL_FILENAME)
    sites = []
    try:
        df = pd.read_excel(excel_path, sheet_name=0)
    except Exception as e:
        log_failure("등록명부", excel_path, "load_excel", e)
        return sites

    for _, row in df.iterrows():
        if len(row) <= max(config.ORG_NAME_COL_INDEX, config.URL_COL_INDEX):
            continue
        org_name = str(row.iloc[config.ORG_NAME_COL_INDEX]).strip()
        if not org_name or org_name.lower() == "nan":
            continue
        url_val = str(row.iloc[config.URL_COL_INDEX]).strip()
        if url_val.startswith("http"):
            sites.append({"url": url_val, "org_name": org_name})
    return sites


def build_target_sites(base_dir: str, url_overrides: dict[str, str],
                        target_orgs: str = "ALL") -> list[dict]:
    """
    base_dir      : 등록명부 엑셀이 있는 디렉터리
    url_overrides : storage.load_run_context()가 구글시트에서 읽어온 {발주기관명: URL}
    target_orgs   : "ALL" 또는 "기관A,기관B" 형태의 콤마 구분 문자열 (부분 조사용)
    """
    sites = _load_sites_from_excel(base_dir)

    # 담당자가 구글시트에 등록한 직통 URL로 덮어쓰기 (기관명에 부분일치)
    for site in sites:
        for org_key, url_val in url_overrides.items():
            if org_key in site["org_name"]:
                site["url"] = url_val

    sites.extend(config.EXTRA_SITES)

    # URL 기준 중복 제거 (뒤에 오는 것이 우선 -> EXTRA_SITES/오버라이드가 우선 적용됨)
    unique = {s["url"]: s for s in sites}.values()
    all_sites = list(unique)

    if target_orgs != "ALL":
        allowed = {o.strip() for o in target_orgs.split(",") if o.strip()}
        all_sites = [s for s in all_sites if s["org_name"] in allowed]

    for site in all_sites:
        site["domain"] = get_domain(site["url"])
        site["handler_type"] = _handler_type_for(site["domain"])

    return all_sites

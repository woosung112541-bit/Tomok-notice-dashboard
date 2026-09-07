"""
github_actions.py
--------------------
Streamlit 대시보드에서 GitHub Actions 워크플로우를 원격으로 실행시키고,
최근 실행 상태를 조회하는 기능. "🏢 사무실 PC로 확실하게 수집" 버튼이 이걸 쓴다.
"""

import requests

import config

API_BASE = "https://api.github.com"
WORKFLOW_FILE = "auto_run.yml"


def _headers():
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def dispatch_workflow(days_ago: str, keywords: str, target_orgs: str, use_proxy: str) -> bool:
    """workflow_dispatch 이벤트를 보내서 사무실 PC(셀프호스팅 러너)에서 실행을 시작시킨다."""
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        return False
    url = f"{API_BASE}/repos/{config.GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    payload = {
        "ref": config.GITHUB_BRANCH,
        "inputs": {
            "days_ago": str(days_ago),
            "keywords": keywords,
            "target_orgs": target_orgs,
            "use_proxy": str(use_proxy),
        },
    }
    res = requests.post(url, headers=_headers(), json=payload, timeout=15)
    return res.status_code == 204


def get_latest_run_status() -> dict | None:
    """가장 최근 실행 상태를 가져온다. {status, conclusion, html_url, created_at} 또는 None."""
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        return None
    url = f"{API_BASE}/repos/{config.GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/runs"
    try:
        res = requests.get(url, headers=_headers(), params={"per_page": 1}, timeout=15)
        runs = res.json().get("workflow_runs", [])
    except Exception:
        return None
    if not runs:
        return None
    run = runs[0]
    return {
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "html_url": run.get("html_url"),
        "created_at": run.get("created_at"),
    }

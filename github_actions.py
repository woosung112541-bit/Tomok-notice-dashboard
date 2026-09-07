"""
github_actions.py
-------------------
Streamlit 대시보드에서 GitHub Actions 워크플로우(.github/workflows/auto_run.yml)를
원격으로 실행시키고 상태를 확인하는 기능. '🏢 사무실 PC로 확실하게 수집' 버튼용.

이 방식은 Streamlit이 직접 스크립트를 실행하는 게 아니라, GitHub에게 "이 워크플로우
실행해줘"라고 신호만 보낸다. 실제 실행은 대전 사무실 PC(셀프호스팅 러너)에서
비동기로 일어나므로, 여기서는 실시간 로그를 스트리밍할 수 없다 - 대신 (1) 요청이
정상적으로 접수됐는지와 (2) 새로고침 시 최신 실행 상태를 보여준다. 자세한 로그는
GitHub Actions 페이지 링크로 안내한다.

필요한 시크릿:
  GITHUB_TOKEN : 이 저장소에 대해 'Actions: Read and write' 권한이 있는
                 GitHub Personal Access Token (Fine-grained 토큰 권장)
  GITHUB_REPO  : "owner/repository" 형식 (예: "nc-company/Tomok-notice-dashboard")
"""

import requests

import config

API_BASE = "https://api.github.com"
WORKFLOW_FILE = "auto_run.yml"


def is_configured() -> bool:
    return bool(config.GITHUB_TOKEN and config.GITHUB_REPO)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def dispatch_workflow(days_ago: int, keywords: str, target_orgs: str, use_proxy: bool,
                       ref: str = "main") -> tuple[bool, str]:
    """워크플로우 실행을 요청한다. 반환: (성공여부, 안내 메시지)."""
    if not is_configured():
        return False, "GITHUB_TOKEN / GITHUB_REPO 시크릿이 설정되지 않았습니다."

    url = f"{API_BASE}/repos/{config.GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    payload = {
        "ref": ref,
        "inputs": {
            "days_ago": str(days_ago),
            "keywords": keywords,
            "target_orgs": target_orgs,
            "use_proxy": "1" if use_proxy else "0",
        },
    }
    try:
        res = requests.post(url, headers=_headers(), json=payload, timeout=15)
    except Exception as e:
        return False, f"요청 중 오류: {e}"

    if res.status_code == 204:
        return True, "사무실 PC로 실행 요청을 보냈습니다."
    if res.status_code == 401:
        return False, "GITHUB_TOKEN이 잘못됐거나 만료됐습니다."
    if res.status_code == 404:
        return False, ("워크플로우를 찾을 수 없습니다. GITHUB_REPO 값과 저장소에 "
                        f"'{WORKFLOW_FILE}' 파일이 있는지, 브랜치명이 '{ref}'인지 확인해주세요.")
    return False, f"GitHub API 오류 (HTTP {res.status_code}): {res.text[:200]}"


def get_latest_run() -> dict | None:
    """가장 최근 실행 상태를 가져온다. {status, conclusion, html_url, created_at} 또는 None."""
    if not is_configured():
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
        "status": run.get("status"),          # queued / in_progress / completed
        "conclusion": run.get("conclusion"),  # success / failure / None(진행중)
        "html_url": run.get("html_url"),
        "created_at": run.get("created_at"),
    }

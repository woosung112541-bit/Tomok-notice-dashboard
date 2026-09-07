# Tomok Notice Dashboard (재구축본)

대전 소재 회사에서 84곳 이상의 공공기관 안전점검/정밀진단/성능평가 관련 입찰공고를
자동으로 모아 보여주는 대시보드. GitHub + Streamlit Cloud 프론트엔드, 구글시트를
데이터 백엔드로 쓴다.

## 폴더 구조

```
rewrite/
  app.py                   # Streamlit 대시보드
  main.py                  # CLI 진입점
  config.py                # 설정값 + 시크릿 로딩
  storage.py                # 구글시트 전담
  site_registry.py         # 명부엑셀 + URL오버라이드로 대상 사이트 구성
  engine.py                # 자동 단계 상승 오케스트레이션
  github_actions.py        # Streamlit→GitHub Actions 원격 실행/상태조회
  scrapers/
    base.py                # 공통 파싱 + 제목추출 + 페이지네이션 + 키워드필터
    generic_requests.py    # 2순위: requests + BS4
    generic_selenium.py    # 3순위: 범용 Selenium
    api_g2b.py             # 1순위: 나라장터 Open API
    custom/khnp.py         # 한국수력원자력 K-Pro 전용 (보안 프로그램으로 사실상 불가)
    custom/igunsul.py      # 아이건설넷 로그인 후 조회
    custom/d2b.py          # 방위사업청 D2B (POST JSON API)
  utils/
    logging_setup.py       # RUN_LOG + log_failure/log_manual_required/log_system_note
    date_parser.py         # 텍스트 날짜 스캔
    proxy.py               # 무료 공개 프록시 탐색/검증
  .github/workflows/auto_run.yml  # 사무실 PC 셀프호스팅 러너용
  .streamlit/secrets.toml.example
```

## 배포 전 설정할 것 (필수)

- Streamlit Secrets / GitHub Actions Secrets에 다음을 등록:
  `GOOGLE_CREDENTIALS`, `G2B_API_KEY`, `IGUNSUL_ID`, `IGUNSUL_PW`,
  `DASHBOARD_PASSWORD`, `GITHUB_TOKEN`, `GITHUB_REPO`
- 등록명부 엑셀(`등록명부 정리시트.xlsx`)을 프로젝트 루트에 배치
- 사무실 PC에 GitHub Actions 셀프호스팅 러너 설치 (Python 3.11, `C:\Program Files\Python311\python.exe`)

## 핵심 아키텍처

### 두 개의 수집 경로
- **🚀 클라우드**: Streamlit이 직접 main.py 실행
- **🏢 사무실 PC**: GitHub Actions workflow_dispatch로 원격 실행 (실제 국내 IP로 접속 가능)

### 단계적 자동 처리 (engine.py)
1. custom (khnp, igunsul, d2b): 전용 핸들러 직행
2. requests: 실패 시 selenium으로 승격 (네트워크 자체 실패는 승격 안 함 - 시간 낭비 방지)
3. selenium: 그래도 안 되면 사유별 분류 후 manual_check 탭에 등록

### 나라장터(G2B) API
- 정확한 End Point: `https://apis.data.go.kr/1230000/ad/BidPublicInfoService`
- 5개 업무구분(공사/용역/물품/외자/기타공고) 전부 호출, 키워드 필터 없이 전부 수집
- "나라장터 (API - 사이트 스캔 없이 바로 조회)" 가상 항목으로 단독 테스트 가능

### 키워드 필터 3단계
1. `DEFAULT_KEYWORDS`: 모집,안전,공고,진단,정밀,점검,성능,수행
2. `EXCLUDE_KEYWORDS`: 공시송달/무연고/견적제출공고/기간제/분묘개장/주민등록/보상계획/수강생/합격자/임용/모니터링 - 걸리면 제외
3. `CORE_SAFETY_KEYWORDS`: 안전점검/정밀안전진단 등 - 이게 있으면 제외 키워드가 있어도 무조건 포함 (강제포함이 최우선)

제외된 공고는 완전히 버리지 않고 `excluded_notices` 시트에 남겨서 "🚫 자동 제외된 공고" 메뉴에서 훑어볼 수 있다.

### 페이지네이션 (scrapers/base.py)
적응형 방식: 이미 아는 공고(history_keys)나 수집기간보다 오래된 공고를 만날 때까지
다음 페이지로 계속 넘어간다 (`MAX_PAGINATION_SAFETY_CAP=8`로 안전 상한).

### 제목 추출 (scrapers/base.py `_pick_title`)
- 공고번호 패턴("OO 공고 제2026-1호")과 순수 날짜(범위) 텍스트는 후보에서 제외
- `<a>` 태그가 없는 행(예: `<tr onclick="...">`)도 지원 - 셀 텍스트만으로 동작, 링크는 게시판 주소로 대체

### 리퍼러 우회 (config.get_request_headers)
일부 사이트는 직접 URL 접속 시 "처리 중 오류" 페이지로 돌려보내고, 자기 사이트
안에서 넘어온 경우만 통과시키는 리퍼러 체크를 한다. 모든 요청에 그 사이트 자신의
루트 주소를 Referer로 자동 채워서 우회한다 (requests, Selenium 둘 다 - Selenium은
CDP `Page.navigate`로 리퍼러 지정).

### "🗒️ 전수조사 로그 (AI 분석용)" - AI 분석용 종합 로그
`run_log`(실패 로그)에는 성공한 사이트가 안 남는 문제를 해결하기 위해 신설.
`site_results`(사이트별 성공/실패 전부), `run_summary`(실행 1회 요약) 두 시트를
실행ID로 연결해서 기록. 대시보드에서 복사 버튼 있는 텍스트로 바로 AI에게 붙여넣을 수 있다.

## 해결된 사이트별 이슈 정리

| 발주처 | 문제 | 해결 |
|---|---|---|
| 나라장터 | 잘못된 API 주소/오퍼레이션명 | 정확한 End Point로 전면 수정 |
| 방위사업청(D2B) | 개찰일자 정렬 + 400건↑이라 키워드 매칭 안 됨 | POST JSON 검색 API로 전용 핸들러 신규 제작 |
| 세종도시교통공사 | 자체 게시판 없이 나라장터로 리다이렉트 | `KNOWN_G2B_REDIRECT_ORGS`에 등록, "정상" 사유로 표시 |
| 대전 동구청(일자리경제과) | `<a>` 태그 없는 onclick 행 + 날짜범위가 제목으로 잘못 뽑힘 | 앵커 없이도 제목 추출 + 날짜패턴 제외 로직 추가 |
| 아이건설넷 | 로그인 칸이 아닌 검색창에 입력, 버튼 클릭도 팝업에 막힘 | placeholder 기반 정확한 필드 타겟팅 + Enter키 우선 로그인 + 화면 에러 문구 진단 로직 |
| 한국수력원자력(KHNP) | AnySign/TouchEn 보안 프로그램 | 자동화 포기, 수동확인으로 수용 |
| 인천국제공항공사 | 사무실 PC에서도 접속 차단 | 미해결, 추가 조사 필요 |

## 실행 취소 시 잠금이 안 풀리는 문제 대응

GitHub Actions에서 '취소'를 누르면 프로세스가 강제 종료되어 잠금 해제 코드가
실행되지 못한다. 15분 지나면 자동으로 풀리는 안전장치가 있고, 대시보드에도
"혹시 방금 취소하셨나요?" 버튼으로 즉시 강제 해제할 수 있다.

## 사무실 PC(Windows) 실행 시 한글이 깨지는 문제 대응

GitHub Actions가 워크플로우의 한글 값을 스크립트 텍스트에 직접 끼워 넣으면,
Windows PowerShell이 cp949로 잘못 해석해서 글자가 깨지는 문제가 있었다. 키워드/
발주처명 같은 한글 값은 환경변수로 전달하고, `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`을
추가해서 콘솔 출력도 UTF-8로 고정했다.

## 낙동강유역환경청 등 "펼쳐진 li형" 게시판 지원 (환경부 계열 mcee.go.kr)

**실제로 발견된 심각한 문제**: 낙동강유역환경청은 명부에 "*24년부터 조달청*"으로
표시되어 "자체 게시판에 공고 없는 게 정상"으로 취급되고 있었는데, 실제로 확인해보니
**완전히 틀린 가정**이었다 - 이 사이트는 총 2,159건에 오늘(2026-09-07)도 새 글이
올라오는 활발한 게시판이었고, "건설공사 안전점검 수행기관 지정 공고" 같은 딱 찾는
유형의 공고도 있었다. 게다가 소관 부처가 환경부 → 기후에너지환경부로 개편되면서
도메인도 `me.go.kr` → `mcee.go.kr`로 바뀌어 있었다.

실제 화면 구조를 직접 확인한 결과, 이 사이트는 번호/제목/등록자/날짜/조회수가
**각각 독립된 형제 `<li>`로 나란히 펼쳐져 있고, 이를 하나로 묶는 상위 태그
(`<tr>`나 공통 `<li>`) 자체가 없는** 특이한 구조였다 - 그래서 기존의 "행 하나 =
공고 하나" 전제가 통째로 깨져서 아무것도 못 찾고 있었다.

`scrapers/base.py`의 `select_rows()`에 이 구조를 인식하는 로직을 추가했다:
`<li class="title">`(실제 화면으로 확인한, 제목 칸에 항상 붙는 클래스명)를
기준점 삼아, 바로 앞 형제 1개(번호)와 **다음 `li.title`이 나오기 전까지**의 뒤쪽
형제들(등록자/날짜/조회수 등)을 모아 새 `<div>`로 합성 '행'을 재구성한다.
"다음 title이 나올 때까지"로 경계를 잡기 때문에 사이트마다 컬럼 개수가 달라도
자동으로 대응된다. 원본 트리를 건드리지 않도록 각 `<li>`는 복사(`copy.copy`)해서
붙인다.

실제 화면 HTML을 그대로 재현해서(공고 2건) 정확히 2개의 행으로 재구성되고, 제목/
날짜/링크(서로 다른 boardId)가 정확히 분리되는 것과, 키워드 필터까지("안전점검
수행기관"→포함, "보상계획"→제외) 실제 공고 내용 그대로 검증했다. 기존 사이트들
(아산시, 대전동구청, 일반 `ul.board_list`)에 회귀가 없는 것도 확인했다 - 새 로직은
기존 셀렉터가 전부 실패했을 때만 최후 수단으로 시도된다.

**영향 범위**: 같은 mcee.go.kr 시스템을 쓰는 한강유역환경청·금강유역환경청·
영산강유역환경청·원주지방환경청·대구지방환경청 등도 같은 구조일 가능성이 높아,
이 수정 하나로 여러 곳이 한 번에 정상화될 수 있다. `config.py`의
`KNOWN_G2B_REDIRECT_ORGS`/명부의 "*24년부터 조달청*" 표시가 실제로는 틀렸을 수
있다는 뜻이므로, 다음 전수조사 결과를 보고 이 기관들의 "조달청 이관" 표시를
재검토할 필요가 있다.

## 알려진 이슈 / 참고사항

- **인천국제공항공사**: 사무실 PC(실제 국내 IP)로 돌려도 여전히 접속 시간 초과가
  발생함. 클라우드 IP 차단과는 다른 원인일 가능성이 있어 추가 조사가 필요하다.
- **KHNP**: AnySign/TouchEn 계열 보안 프로그램 때문에 자동화를 포기하고 수동확인
  대상으로 받아들이기로 했다. 코드(`scrapers/custom/khnp.py`)는 남겨뒀지만
  실제 셀렉터는 검증되지 않은 추정치다.
- **아이건설넷**: 여러 차례 수정 끝에 로그인 입력/제출 로직은 상당히 견고해졌지만,
  마지막 테스트에서도 로그인 자체가 성공했는지 최종 확인이 안 된 상태. 브라우저로
  직접 로그인 테스트가 필요할 수 있다.

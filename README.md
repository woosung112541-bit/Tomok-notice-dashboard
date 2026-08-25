# PQ 공고 자동 수집 시스템 (재구축판)

지자체·공기업·조달청 등 다수 발주처 게시판을 자동으로 순회해 조건에 맞는 공고를
찾아 구글 시트에 쌓고, Streamlit 대시보드에서 검토하는 시스템.

기존 저장소(`main.py` / `main_major.py` / `main_max.py` / `main_pure.py` 4벌)를
분석한 뒤, **단일 엔진 + 자동 단계 상승(escalation) 구조**로 다시 짰다. 자세한
문제 진단은 대화 중 전달한 `project_overview.md`를 참고.

## 폴더 구조

```
app.py                  # Streamlit 대시보드 (UI 전용)
main.py                 # 수집 실행 진입점 (CLI / GitHub Actions / app.py에서 subprocess로 호출)
config.py               # 설정값 + 시크릿 로딩 (하드코딩된 비밀번호/키 없음)
storage.py              # 구글 시트 읽기/쓰기 전담
site_registry.py        # 명부 엑셀 + URL 오버라이드로 '수집 대상 목록' 구성
engine.py               # 사이트별 자동 단계 상승(오케스트레이션) + 병렬 실행
scrapers/
  base.py               # 공통 파싱 로직 (행 파싱, 첨부파일 딥스캔)
  generic_requests.py   # 2순위: requests + BeautifulSoup
  generic_selenium.py   # 3순위: 범용 Selenium
  api_g2b.py            # 1순위: 나라장터 Open API
  custom/
    khnp.py             # 4순위: 한국수력원자력 K-Pro 전용 (팝업닫기→메뉴클릭→대기→클릭)
    igunsul.py           # 4순위: 아이건설넷 로그인 전용
utils/
  logging_setup.py      # 실행 로그 (콘솔 + 구조화된 RUN_LOG, 실패 원인 추적용)
  date_parser.py         # 텍스트 안 날짜 추출
.github/workflows/auto_run.yml   # 수동 실행용 GitHub Actions
.streamlit/secrets.toml.example  # 로컬 개발용 시크릿 템플릿 (실제 값은 커밋 금지)
```

## 이전 구조 대비 무엇이 바뀌었나

1. **엔진 4개 → 1개**: 더 이상 "빠른/정밀/극한/주요4대"를 사람이 고르지 않는다.
   `engine.py`가 사이트별로 `requests → (실패 시) selenium → (그래도 실패 시) 수동확인`
   순서를 자동으로 시도한다. 이전 버전은 대시보드 라디오 버튼 기본값이 Selenium이
   전혀 없는 "빠른 탐색"이라, 별도로 바꾸지 않으면 JS 렌더링이 필요한 사이트가
   전부 조용히 누락됐다 — 이 문제 자체가 구조적으로 사라진다.
2. **KHNP 등 '자체 시스템형' 사이트 전용 처리**: `scrapers/custom/khnp.py`에
   말씀하신 흐름(팝업 닫기 → 입찰공고 메뉴 → 입찰공고조회 → 대기 → 클릭)을
   구현했다. **다만 이 사이트는 봇 방어가 강해 실제 DOM을 확인 못 하고 화면
   캡처만으로 작성했다.** 처음 실행해보면 셀렉터 조정이 필요할 가능성이 높은데,
   실패해도 이제는 `run_log`에 "어느 단계(팝업/메뉴클릭/대기/파싱)에서 막혔는지"가
   정확히 남으므로, 그 로그를 보고 한 부분만 고치면 된다.
3. **침묵의 에러 제거**: `except: pass`를 없애고 `log_failure()` / `log_manual_required()`로
   통일했다. 실행 후 대시보드의 "🚨 수동 확인 필요" 메뉴에서 실패 원인을 바로 볼 수 있다.
4. **자격증명 하드코딩 제거**: 아이건설넷 계정, 조달청 API 키, 대시보드 비밀번호를
   전부 `config.get_secret()`으로 옮겼다 (환경변수 → Streamlit secrets 순으로 탐색).
   **기존에 코드에 평문으로 있던 값들은 git 히스토리에 이미 노출되어 있으니, 여유
   되실 때 실제 비밀번호/키 자체를 교체하시는 걸 권장한다.**
5. **GitHub Actions 워크플로우 수정**: `google_key.json`을 만드는 단계가 아예
   없어서 기존 워크플로우는 실행될 때마다 구글 시트 연결 단계에서 실패하고
   있었다. 이번에 시크릿에서 키 파일을 만드는 단계를 추가했고, 존재하지도 않는
   파일(`verified_sites.json`, `저장된_공고모음.xlsx`)을 커밋하려던 죽은 단계는 제거했다.
6. **실패 원인 시각화**: 신규 구글시트 탭 `run_log`(실패 로그), `manual_check`
   (자동화 포기 목록)를 만들고, 대시보드에 "🚨 수동 확인 필요" 메뉴로 노출했다.

## 배포 전 설정할 것 (필수)

### 1) 구글 시트
기존과 동일하게 `맞춤공고_DB`라는 이름의 구글 스프레드시트를 그대로 쓰면 된다.
아래 탭이 필요하다 (없으면 코드가 자동 생성하는 탭도 있지만, `notices`/`collected_orgs`는
최초 1회 직접 만들어두는 걸 권장):
- `notices` (헤더: 출처, 등록일, 공고제목, 상세링크, notice_key, 등록시각, 특이사항, 검토유무)
- `collected_orgs` (헤더: org_name)
- `url_overrides` (헤더: 발주기관명, 정확한_게시판_URL, 비고) — 없어도 동작함
- `settings`, `run_log`, `manual_check` — 없으면 코드가 자동 생성

### 2) 시크릿 등록
`.streamlit/secrets.toml.example`을 참고해서:
- **Streamlit Cloud**: 앱 Settings → Secrets에 붙여넣기
- **GitHub Actions**: 저장소 Settings → Secrets and variables → Actions에
  `GOOGLE_CREDENTIALS`, `G2B_API_KEY`, `IGUNSUL_ID`, `IGUNSUL_PW` 등록

### 3) 로컬 테스트
```bash
pip install -r requirements.txt --break-system-packages
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # 값 채우기
streamlit run app.py
```

## 알려진 한계 / 다음에 확인해야 할 것

- **KHNP 셀렉터 검증 필요**: `scrapers/custom/khnp.py`는 화면 캡처 기반 추정으로
  작성됨. 처음 실행 후 `run_log`를 보고 실제 버튼/메뉴 셀렉터를 맞춰야 한다.
- **등록명부 엑셀의 우측 블록**(19번째 열부터 발주처/모집공고일 등이 한 번 더
  반복되는 부분)은 URL 컬럼이 없어 현재 코드에서 수집 대상에 포함하지 않는다.
  이 블록의 기관들을 자동 수집 대상으로 삼아야 한다면 별도 URL 컬럼을 추가하거나
  `site_registry.py`의 로직을 확장해야 한다.
- **Selenium 동시 실행 수(`config.MAX_WORKERS_SELENIUM`)**: Streamlit Cloud
  무료 플랜은 메모리가 넉넉하지 않다. 자꾸 수집이 중간에 멈추면 이 값을 1로
  낮춰서 안정성을 우선하는 것을 고려.
- 이 코드는 대화형 환경(네트워크가 PyPI/GitHub 등으로 제한된 샌드박스)에서
  작성되어, 실제 대상 사이트에 접속해 파싱 결과를 직접 검증하지는 못했다.
  배포 후 몇 개 발주처로 소규모 테스트(특정 발주처만 선택해서 수집)를 먼저
  해보는 것을 권장한다.

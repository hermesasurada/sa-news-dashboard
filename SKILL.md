---
name: sa-news
description: Seeking Alpha Breaking News 이메일을 수집하고 본문을 한국어로 요약해 FastAPI 대시보드에 발행하는 2단계 파이프라인.
category: productivity
tags: [sa-news, seeking-alpha, fastapi, dashboard, monitor]
---

# SA News 운영 가이드

이 저장소의 현재 동작을 기준으로 한 운영 문서다. 일반 개발 안내는 `README.md`, 배포 복원은 `deploy/DEPLOY.md`, 남은 개선 순서는 `docs/REFACTOR_PRIORITIES.md`를 따른다.

## 아키텍처

```text
Stage 1 Collect
  himalaya envelope/message
  → scripts/extract_sa_urls.py (URL)
  → db.insert_pending_article()
  → 이메일 seen 처리

Stage 2 Publish
  db.get_pending_due()
  → sa_article_parser.parse_sa_article()
  → Claude CLI, 실패 시 Grok CLI
  → db.publish_article()
```

| 구성 요소 | 실제 경로 | 책임 |
|---|---|---|
| 수집기 | `scripts/sa_collect.py` | 이메일 envelope/URL을 pending 행으로 적재 |
| URL 추출 | `scripts/extract_sa_urls.py` | himalaya 출력과 SA click URL 해석 |
| 발행기 | `scripts/sa_summarize_claude.py` | 파싱·요약·검증·DB 발행 |
| LLM 어댑터 | `scripts/sa_claude_cli.py` | Claude stream-json 및 Grok plain 응답 처리 |
| 파서 | `sa_article_parser.py` | 로그인 쿠키 전문 → 비로그인 프리뷰 폴백 |
| DB | `db.py` | SQLite/FTS5와 기사 상태 전이 |
| 대시보드 | `app.py`, `static/` | FastAPI API와 카드/통계 UI |

## 운영 스케줄

실제 cron 정의의 단일 기준은 `deploy/DEPLOY.md`다.

| 작업 | 스케줄 | 진입점 |
|---|---|---|
| `sa-collect` | 매시 `00,30분` | `~/.hermes/scripts/sa_collect.sh` |
| `sa-publish` | 매시 `10,40분` | `~/.hermes/scripts/sa_publish.sh` |
| `sa-purge` | 매일 `03:30` | `~/.hermes/scripts/sa_purge.sh` |

각 작업은 `scripts/sa_lock.py`의 `fcntl` lock으로 중복 실행을 막는다. 활성 shim과 `deploy/hermes-scripts/` 사본은 항상 함께 갱신한다.

## Stage 1 규칙

- LLM과 SA 페이지에 접근하지 않는다.
- `himalaya envelope list`의 plain-text `*` 표시를 미읽음 기준으로 사용한다.
- 발신자에 `SA Breaking News`가 포함된 메일만 처리한다.
- 주간 헤드라인·Catalyst Watch 모음·Earnings Scorecard·Key deals this week·갭핑 라운드업은 수집하지 않는다.
- 한 번에 기본 10건, 안전 상한 20건이며 오래된 UID부터 처리한다.
- `email_id` UNIQUE로 중복 INSERT를 막는다.
- himalaya 명령의 non-zero return code는 실패로 처리한다. 실패를 “미읽음 없음”으로 간주하지 않는다.
- URL 추출 오류가 난 메일은 seen 처리하지 않아 다음 주기에 재시도한다.

## Stage 2 규칙

발행기는 기본 10건의 due 행을 처리한다. 기사와 기사 사이에 `SA_ARTICLE_GAP_SECONDS`(기본 20초)를 두어 Playwright 연속 요청을 줄인다. `--id` 단건은 대기하지 않는다.

1. `sa_publish.py parse <id>` subprocess로 본문과 `PARSE_METHOD`, `SA_TICKERS`를 받는다.
   본문은 `article_url`로 SA 사이트에서 가져오고 `source_text`에 저장한다.
   미리보기(700자 미만 또는 `isMpwLocked`)는 성공이 아니며 발행하지 않는다.
   `--reuse-source` 이면 저장된 본문만 재요약한다.
2. SA 공식 primary ticker는 확정값이 아닌 후보 whitelist로 LLM에 전달한다.
3. Claude 모델 기본값은 `opus`; 실제 stream-json model ID를 DB에 기록한다.
4. Claude 실패 또는 빈 응답이면 Grok CLI로 한 번 폴백한다.
5. JSON과 필수 필드를 검증한 뒤 발행한다.

현재 생성 필드는 다음뿐이다.

- `ticker`: 실질 관련 상장기업, `, ` 구분
- `company_name`: ticker 순서에 맞춘 영문 정식명, `·` 구분
- `headline`: 구체적인 한국어 제목
- `summary_details`: SA 수집 본문의 핵심만. 체언 종결 단문, 항목 수를 맞추지 않음 (짧으면 1~2개)
- `ticker_color`: `blue|green|red|orange|yellow|purple|gray`

저장 전 검증:

- ticker 형식 및 중복 제거
- Markdown link/emphasis 토큰 제거
- headline과 details의 한자(U+4E00–9FFF)·가나(U+3040–30FF) 거부
- headline/details 누락 거부
- ticker가 비었으면 Stage 1 envelope ticker 유지

## 재시도와 상태

`pub_status`:

- `pending`: 신규 또는 재시도 대기
- `published`: 화면 노출
- `failed`: 최대 재시도 도달
- `deleted`: 휴지통
- `purged`: 30일 경과 후 세부 텍스트 제거, 중복 방지 행만 유지

실패 백오프 기본값은 20·40·80·160·320분이고 5회째 실패하면 `failed`가 된다. 이미 published인 기사를 수동 재처리하다 실패해도 기존 published 데이터는 유지한다. deleted/purged 행은 늦게 끝난 worker가 되살릴 수 없다.

## SA 파서

`sa_cookies.json`에 로그인 쿠키(`user_id` / `user_remember_token` 등)가 있으면 그 세션으로 전문을 먼저 시도한다. 구독자가 볼 수 있는 본문만 가져오며 페이월을 우회하지 않는다.

순서:

1. 로그인 쿠키 + Playwright persistent profile (`playwright_auth`)
2. 같은 쿠키 + curl_cffi HTML
3. 같은 쿠키 + SA 내부 API. `isMpwLocked` 프리뷰면 성공으로 치지 않음
4. Jina Reader
5. 비로그인 경로는 `SA_ALLOW_ANON_FETCH=1` 일 때만. 미리보기는 발행 금지

내부 API가 주는 `primaryTickers`는 ETF/테마 기사에서 과다할 수 있으므로 본문 관련성 판단 없이 그대로 저장하지 않는다.

세션이 만료되면 프리뷰만 돌아온다. 갱신:

```bash
venv/bin/python3 scripts/sa_refresh_login.py
```

설치된 Google Chrome이 열린다(번들 Chromium은 SA가 봇으로 차단한다).
로그인한 뒤 터미널에서 Enter. 쿠키만 `sa_cookies.json`에 저장하고 비밀번호는 저장하지 않는다.
`To continue, please prove you are not a robot` 이 뜨면 그 창에서 확인을 통과한 다음 로그인한다.

차단 판단:

- HTML 길이 9,000자 미만
- `Access to this page has been denied`
- 본문 텍스트 800자 미만이면서 SVG `<path>` 20개 초과
- `px-captcha` 문자열만으로는 차단으로 판단하지 않는다.

## DB 불변 조건

- 운영 DB: `sa_news.db`; `SA_DB_PATH`로 테스트/이전 경로 override 가능
- `id`는 SQLite PK, `email_id`는 himalaya UID다. 메일 번호를 말할 때는 `email_id`인지 확인한다.
- 검색은 FTS5 prefix query를 사용하고 사용자 입력을 FTS 연산자로 직접 실행하지 않는다.
- `GOOGL→GOOG`, `FOXA→FOX`, `NWSA→NWS`, `UAA→UA` 등 클래스 별칭은 `db.TICKER_ALIASES`가 단일 기준이다.
- 기사 삭제는 soft delete이며 30일 후 purge에서도 `email_id`, ticker, 날짜는 중복 방지를 위해 남긴다.

## 수동 명령

```bash
# 상태
venv/bin/python3 scripts/sa_publish.py stats

# due 목록
venv/bin/python3 scripts/sa_publish.py list --batch 10

# 특정 DB id 파싱
venv/bin/python3 scripts/sa_publish.py parse 490

# 특정 DB id 강제 재요약 (SA 재접속)
venv/bin/python3 scripts/sa_summarize_claude.py --id 490

# 저장된 본문만 재요약
venv/bin/python3 scripts/sa_summarize_claude.py --id 490 --reuse-source

# pending 배치
venv/bin/python3 scripts/sa_summarize_claude.py --batch 5

# 30일 지난 deleted 정리
venv/bin/python3 scripts/sa_purge_deleted.py --days 30

# SA 로그인 세션 갱신 (headed 브라우저)
venv/bin/python3 scripts/sa_refresh_login.py
```

## 검증

```bash
venv/bin/python3 -m unittest discover -s tests -v
node tests/test_app_utils.js
node --check static/app.js
curl -fsS http://127.0.0.1:8181/api/health
```

## 운영 주의

- 웹 API에 인증이 없으므로 로컬 또는 신뢰된 Tailscale ACL 안에서만 노출한다.
- 웹서버는 launchd `com.user.sa-dashboard`, 기본 포트 8181이다.
- 시세 프록시는 기본 `http://127.0.0.1:8765`를 사용한다.
- 통계 페이지의 Chart.js는 현재 jsDelivr에 의존한다.
- Claude/Grok 호출은 순수 텍스트 작업이므로 임시 디렉터리 cwd에서 실행해 프로젝트 파일 자동 탐색을 막는다.
- `ticker_names.json`, DB, 쿠키, Playwright profile은 git에 올리지 않는다.

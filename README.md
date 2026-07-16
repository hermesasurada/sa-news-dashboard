# SA News Dashboard

Seeking Alpha Breaking News 이메일을 수집하고, 기사 본문을 한국어로 요약해 보여주는 개인용 대시보드입니다.

## 데이터 흐름

```text
SA 이메일
  → himalaya envelope/message
  → articles(pub_status=pending)
  → SA API / Jina / Playwright / curl_cffi
  → Claude CLI (실패 시 Grok CLI)
  → articles(pub_status=published)
  → FastAPI + 정적 JavaScript UI
```

수집과 발행을 분리해 이메일 수집은 SA 페이지나 LLM 장애의 영향을 받지 않습니다. 발행 실패는 기본 5회까지 20·40·80·160·320분 지수 백오프로 재시도합니다.

## 주요 파일

| 경로 | 역할 |
|---|---|
| `app.py` | FastAPI 엔드포인트와 정적 파일 제공 |
| `db.py` | SQLite 스키마, 검색, 상태 전이, 통계 |
| `settings.py` | 환경변수 기반 런타임 설정 |
| `quote_service.py` | portfolio API 시세 응답 정규화 |
| `scripts/sa_collect.py` | Stage 1: 미읽음 이메일을 pending으로 적재 |
| `scripts/sa_summarize_claude.py` | Stage 2: 파싱·요약·발행 |
| `scripts/sa_claude_cli.py` | Claude/Grok CLI 어댑터 |
| `sa_article_parser.py` | 4단계 SA 본문 파서 |
| `static/app.js` | 화면 상태와 사용자 동작 |
| `static/app-utils.js` | 테스트 가능한 HTML/URL/표시 유틸리티 |
| `static/stats.html` | Chart.js 통계 화면 |
| `deploy/DEPLOY.md` | Hermes cron 및 launchd 복원 절차 |

## 로컬 실행

Python 3.11 이상이 필요합니다. 현재 운영 venv는 Python 3.14를 사용합니다.

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/playwright install chromium
venv/bin/uvicorn app:app --host 127.0.0.1 --port 8181
```

브라우저에서 `http://127.0.0.1:8181`을 열고 상태 확인은 `GET /api/health`를 사용합니다.

## 테스트

```bash
venv/bin/python3 -m unittest discover -s tests -v
node tests/test_app_utils.js
node --check static/app.js
```

테스트는 임시 SQLite DB를 사용하며 운영 DB를 변경하지 않습니다.

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---:|---|
| `SA_DB_PATH` | `./sa_news.db` | SQLite 파일 경로 |
| `SA_DB_BUSY_TIMEOUT_MS` | `5000` | SQLite lock 대기 시간 |
| `PORTFOLIO_API_BASE` | `http://127.0.0.1:8765` | 시세 서비스 주소 |
| `PORTFOLIO_API_TIMEOUT_SECONDS` | `6` | 시세 요청 제한 시간 |
| `SA_PUBLISH_BATCH_SIZE` | `10` | 발행 배치 크기 |
| `SA_PARSE_TIMEOUT_SECONDS` | `200` | 기사 파서 subprocess 제한 시간 |
| `SA_SUMMARY_TIMEOUT_SECONDS` | `120` | Claude/Grok 호출 제한 시간 |
| `SA_SUMMARY_CONTENT_LIMIT` | `10000` | LLM에 전달할 최대 본문 문자 수 |
| `SA_MAX_RETRY` | `5` | 발행 최대 시도 횟수 |
| `SA_RETRY_BASE_MINUTES` | `20` | 지수 백오프 기준 시간 |
| `CLAUDE_BIN` / `CLAUDE_CODE_BIN` | 자동 탐색 | Claude CLI 경로 |
| `CLAUDE_MODEL` | `opus` | Claude 모델 별칭 |
| `GROK_BIN` | `~/.grok/bin/grok` | Grok CLI 경로 |
| `GROK_MODEL` | CLI 기본 모델 | Grok 모델 override |

## API 요약

- `GET /api/health`: DB 연결 상태
- `GET /api/articles`: 검색·티커·날짜·읽음·휴지통 필터
- `GET /api/article/{id}`: 단일 기사
- `GET /api/filters`: 티커와 별칭
- `GET /api/price-quote`: portfolio 시세 프록시
- `GET /api/stats`, `GET /api/queue_stats`: 대시보드 통계
- `PATCH /api/articles/{id}/read`: 읽음 상태 변경
- `DELETE /api/articles/{id}`: 소프트 삭제
- `POST /api/articles/{id}/restore`: 복원

## 데이터 상태

`pub_status`는 다음 상태를 사용합니다.

- `pending`: 발행 대기 또는 재시도 대기
- `published`: 화면에 노출
- `failed`: 최대 재시도 초과
- `deleted`: 휴지통, 복원 가능
- `purged`: 삭제 후 30일 경과. 중복 방지용 행만 보존

`summary_core`, `tag`, `tag_color`는 과거 데이터 호환용 컬럼입니다. 현재 발행기는 `headline`, `summary_details`, `ticker_color`만 생성합니다.

## 보안 경계

현재 인증 계층은 없습니다. 읽음·삭제·복원 API가 있으므로 웹서버는 로컬 또는 신뢰할 수 있는 Tailscale 네트워크에만 바인딩해야 합니다. 외부 공개가 필요하면 인증과 CSRF 방어를 먼저 추가해야 합니다.

남은 개선 순서는 [`docs/REFACTOR_PRIORITIES.md`](docs/REFACTOR_PRIORITIES.md)에 정리돼 있습니다.

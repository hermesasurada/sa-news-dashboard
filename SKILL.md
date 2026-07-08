---
name: sa-news
description: End-to-end Seeking Alpha news pipeline — Monitor (collect emails → parse articles → Korean summary via Claude CLI → publish to DB) and Dashboard (FastAPI viewer for SA News, Telegram feeds, Obsidian archives). Cron-driven, fully deterministic.
category: productivity
tags: [sa-news, seeking-alpha, fastapi, dashboard, monitor, telegram, obsidian]
---

# SA News — Full Pipeline

End-to-end Seeking Alpha news pipeline: 이메일 수집 → SA 기사 파싱 → Claude CLI 한국어 요약 → DB 발행 → FastAPI dashboard 노출.

## 구성 요소

| Component | 경로 | 책임 |
|-----------|------|------|
| **Stage 1 (Collect)** | `scripts/sa_collect.py` | 미읽음 SA 메일에서 envelope 정보 추출 → DB pending 행 INSERT + seen 플래그. **LLM 미사용, SA 페이지 미접속**. |
| **Stage 2 (Publish)** | `scripts/sa_summarize_claude.py` | pending due 행마다 SA 페이지 fetch → Claude CLI(subprocess)로 한국어 요약 → `db.publish_article()` 호출. |
| **Parser** | `scripts/sa_article_parser.py` | 3단계 fallback (Jina → Playwright → curl_cffi). dashboard 사본과 항상 byte-identical. |
| **Dashboard** | `~/Documents/sa-dashboard/` (FastAPI) | `pub_status='published'` 행을 카드로 노출, 검색/필터/Markdown modal. |

## 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 1 (cron: 0 * * * *, --no-agent --script sa_collect.sh)        │
│   himalaya envelope → extract_sa_urls.py → DB pending INSERT        │
│   ※ Stage 1은 LLM도 SA 페이지도 건드리지 않음. 차단·지연 위험 없음. │
└────────────────────────────┬────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 2 (cron: 10,30,50 * * * *, --no-agent --script sa_publish.sh) │
│   sa_publish.sh → sa_summarize_claude.py --batch 10                 │
│     1) db.get_pending_due(10)  — 지수 백오프 due 행만               │
│     2) parse_sa_article(url)   — Jina → Playwright → curl_cffi      │
│     3) Claude CLI subprocess   — sonnet 모델, 임베디드 한국어 프롬프트 │
│     4) JSON 추출·검증 + db.publish_article()                        │
│        실패 시 db.mark_attempt_failed(reason)                       │
└─────────────────────────────────────────────────────────────────────┘
```

## Stage 2 — Claude CLI 호출 상세

**스크립트**: `~/.hermes/skills/sa-news/scripts/sa_summarize_claude.py`

**바이너리**: 하드코딩 금지 — `resolve_claude_bin()`이 `~/Library/Application Support/Claude/claude-code/*/claude.app/Contents/MacOS/claude` 중 **최신 버전을 동적 탐지**. `CLAUDE_BIN` / `CLAUDE_CODE_BIN` 환경변수로 override 가능. (Claude Code 자동 업데이트로 버전 디렉토리가 바뀌므로 버전 pin 금지 — 과거 2.1.149 하드코딩이 2.1.156 업데이트 후 깨져서 sa-publish 전체 실패한 이력 있음. sa_summarize_claude.py에 동적 탐지 적용.)
**모델**: `opus` (별칭 → 현재 claude-opus-4-8, `CLAUDE_MODEL` 환경변수로 override 가능)
**폴백**: Claude CLI 응답이 없으면(`call_claude`→None) grok CLI(`call_grok`, `grok -p … --output-format plain`)로 자동 재시도. 응답 형식이 동일(요약 JSON 텍스트)해 `extract_json` 재사용. grok 경로는 `GROK_BIN`(기본 `~/.grok/bin/grok`, cron bare PATH 대비 절대경로), 모델은 `GROK_MODEL`(기본 grok 기본값)로 override 가능.

**프롬프트(스크립트 내부 `_PROMPT_TMPL`)에 포함된 규칙**:
- JSON 단일 라인 응답 강제 (key 순서 고정: ticker, company_name, headline, summary_core, summary_details, tag, ticker_color, tag_color)
- ticker = 기사에 명시된 거래소 심볼만, 쉼표+공백 구분 (`NVDA, AMD`). 가장 주요한 기업 첫 번째. 비상장 기관(연준 등) 제외. 없으면 빈 문자열
- company_name = ticker 순서대로 영문 정식명을 `·` 연결 (`Nvidia·AMD`). 음차·번역·티커 중복 금지
- headline = 티커 prefix 금지, 구체적 정보·수치·이벤트 포함
- summary_core = 2~3문장, 분석가/목표주가/수치/날짜 포함
- summary_details = 4~6개 완결 문장 배열
- tag = `#` 없이 1단어/구
- ticker_color/tag_color = blue/green/red/orange/yellow/purple/gray. 상승·긍정=green, 하락·부정=red, 중립=blue
- **외국 기업·인명·약품명 = 영문 원어**. 한국 기업만 한국어 (삼성전자/LG/SK/현대 등). 음차 금지: 앤티로픽→Anthropic, 파란티어→Palantir, 애플→Apple, 테슬라→Tesla, 엔비디아→Nvidia 등
- **한자·가나 절대 금지**. 売上→매출, 格上げ→상향, 中国→중국, メーカー→제조사 등

**스크립트 측 검증 단계** (Claude 응답 후):
1. `extract_json()` — Claude 출력에서 JSON 블록 추출 (markdown 코드블럭·여백 처리)
2. `validate()` — 필수 필드(`headline`, `summary_core`, `summary_details`) 누락 시 mark_attempt_failed
3. `db.publish_article(ticker=..., ...)` 호출 — **ticker가 비어 있지 않을 때만 ticker 덮어쓰기**, 비었으면 Stage 1 envelope 값 유지

**수동 호출**:
```bash
python3 ~/.hermes/skills/sa-news/scripts/sa_summarize_claude.py            # pending 최대 10건
python3 ~/.hermes/skills/sa-news/scripts/sa_summarize_claude.py --batch 5  # 5건
python3 ~/.hermes/skills/sa-news/scripts/sa_summarize_claude.py --id 490   # 특정 id 강제 (due 무시)
```

## DB 스키마 (요약)

`~/Documents/sa-dashboard/sa_news.db` — articles 테이블 주요 컬럼:

- `id` PK, `email_id` UNIQUE (himalaya UID), `ticker`, `original_title`(영문 SUBJECT)
- `company_name` / `headline` / `summary_core` / `summary_details` (JSON array) — **모두 한국어** (Stage 2 채움)
- `tag`, `ticker_color`, `tag_color`
- `article_url` (utm 제거됨), `email_time_et` (KST), `last_modified` (KST)
- `pub_status` ∈ {pending, published, failed, deleted}
- `retry_count`, `last_attempt`, `fail_reason`
- 지수 백오프: `next_due = last_attempt + 2^retry_count × 20분` (20→40→80→160→320 min, MAX_RETRY=5)
- Dashboard `/api/articles`는 **`pub_status='published'`만 반환**.

## 재작업 제외 규칙

**모든 보정/재처리에서 다음 제외:**
1. **휴지통(`[Gmail]/휴지통`) 메일** — DB에 행 있으면 **물리 DELETE**, 없으면 INSERT 금지.
2. **`pub_status != 'published'` 행** — `'deleted'`(사용자 삭제), `'pending'`/`'failed'`(미발행)은 일회성 UPDATE 대상 아님. 재처리 필요 시 `UPDATE articles SET pub_status='pending', retry_count=0, last_attempt=NULL, fail_reason=NULL` 으로 큐에 되돌리고 cron이 자동 처리.

## 파서 (sa_article_parser.py, v5)

**Fallback 순서 (Jina 우선)**:
1. **Jina Reader** (`https://r.jina.ai/{url}`) — 외부 IP pool, 로컬 평판 보전. 무료 ~20 RPM.
   - 응답 구조: `# {title} | Seeking Alpha` (페이지 헤더) → 사이트 네비게이션 ~14000자 → `# {title}` (article H1) → 본문
   - 본문 시작점 탐지: title(앞 60자) **두 번째 등장 위치**부터 10000자 윈도우. 단순 truncation은 nav만 잡혀서 본문 사라짐.
2. **Playwright stealth + persistent profile** — `~/Documents/sa-dashboard/pw_profile`에 브라우저 상태 누적.
3. **curl_cffi impersonate** — `chrome124` → `safari17_2` → `edge99`. TLS/JA3 fingerprint 다양화.

**차단 감지** (`_is_blocked`):
- HTML 길이 < 9000자
- `"Access to this page has been denied"`
- SVG-only: 본문 텍스트 < 800자 + `<path` > 20개
- ⚠️ `px-captcha`는 정상 페이지에도 있음 — 차단 기준으로 사용 금지

**파일 동기화**: `~/.hermes/skills/sa-news/scripts/sa_article_parser.py` ↔ `~/Documents/sa-dashboard/sa_article_parser.py` 항상 byte-identical 유지 (둘 다 같은 모듈로 import됨).

## 한국어 요약 규칙 (수동 편집·sa_summarize_claude.py 프롬프트 일관 기준)

- **headline / summary_core / summary_details — 모두 한국어**. 영어 원문 그대로 저장 금지.
- **headline**: 티커 prefix(`TSLA: `) 금지. 구체적·정보량 있게.
- **summary_core**: 2~3문장. 숫자·날짜·기업·분석가 이름·전망 방향 반드시.
- **summary_details**: 4~6개 완결 문장. "분석가 X는 Y라고 전망했다" 형식 선호. 본문 author/editor 메타 같은 무가치 항목 금지.
- **ticker**: 기사 본문에서 직접 추출. envelope prefix(Stage 1)는 부정확할 수 있음 (예: `ARKG` 하나로만 박혔지만 본문에는 ARKK·ARKG·ARKW·ARKF·ARKQ·ARKX 전체, 또는 `NONE`이지만 본문에 `(HOOD)`/`(WONDF)` 명시). `(NYSE: XXX)` / `(NASDAQ: XXX)` / `$XXX` / 회사명 옆 괄호 ticker 패턴으로 본문 재추출. 다중 ticker는 `·` 연결.
- **company_name**: **영문 원본 보존** (`Apple`, `Analog Devices`, `Google DeepMind`). 한국어 음차·번역 금지. ticker가 다중이면 company_name도 `·` 연결 (`Robinhood Markets·WonderFi Technologies`).
- **외국 기업·인명·약품명 = 영문**, 한국 기업만 한국어:
  - 영문: Apple, Microsoft, Google, Alphabet, Meta, Amazon, Intel, Nvidia, Tesla, Anthropic, OpenAI, Palantir, PepsiCo, Wedbush, SpaceX, Airbnb, Nebius, Cohen & Steers, Bank of America, JPMorgan, Goldman Sachs, Morgan Stanley, Citi, Novo Nordisk, Eli Lilly, Sony, Nintendo, Walmart, Costco, Starbucks, Boeing, Airbus, Ford, Stellantis, Visa, Mastercard, Disney, Netflix, Pfizer, Merck, AstraZeneca, Gilead, AbbVie, Lenovo, Huawei, Alibaba, Tencent, Xiaomi, Li Auto, Tata, Take-Two, Home Depot, Target, Deere, Caterpillar, Berkshire Hathaway, Wells Fargo, BlackRock, Blackstone, BlackBerry, Nokia, Snowflake, Palo Alto Networks, CrowdStrike, Cantor, Coinbase, Kalshi, Polymarket 등
  - 한국 기업·기관(한국어): 삼성전자, LG, 현대, SK, 포스코, 네이버, 카카오, 한국전력 등
  - 지명·정부기관·일반어: 미국, 중국, 일본, 대만, 유럽, 베이징, 도쿄, 워싱턴, 캘리포니아, 연준, 백악관, 의회, 트럼프, 시진핑, 월가
  - 금지 음차: 앤티로픽→Anthropic, 파란티어→Palantir, 애플→Apple, 엔비디아→Nvidia, 메타→Meta, 테슬라→Tesla, 에어비앤비→Airbnb, JP모건→JPMorgan, 머스크→Musk, 저커버그→Zuckerberg, 딥마인드→DeepMind
- **한자(U+4E00–9FFF) / 가나(U+3040–30FF) 절대 금지**. 売上→매출, 評級→평가, 衍生品→파생상품, 与此同时→한편, 格上げ→상향, 中国→중국, メーカー→제조사 등.
- **Markdown 잔재 제거**: 본문이 markdown이라 `_italic_`, `**bold**`, `[text](url)` 토큰이 요약에 흘러들 수 있음. 한국어 텍스트에 `_`, `*`, `[`/`]` 보이면 plain으로 정리 (`규모의_equity` → `규모`).
- **태그**: `#태그명` 형식, 이모지 금지. (sa_summarize_claude.py 프롬프트는 `#` 없이 받고 호출자가 붙임)

**저장 직전 자가검증 정규식**:
```python
import re
HAN  = re.compile(r'[一-鿿]')      # U+4E00–9FFF
KANA = re.compile(r'[぀-ヿ]')      # U+3040–30FF
blob = headline + summary_core + ''.join(summary_details)
assert not HAN.findall(blob),  f"한자 contamination: {HAN.findall(blob)}"
assert not KANA.findall(blob), f"가나 contamination: {KANA.findall(blob)}"
```

## 발행/실패 호출

```python
import sys; sys.path.insert(0, '/Users/yhandhs/Documents/sa-dashboard')
import db

# 성공:
db.publish_article(
    article_id,
    ticker="LI·NIO·BYDDY·TSLA·TM",            # 본문 재추출 결과. None 전달 시 Stage 1 ticker 유지
    company_name="Li Auto·NIO·BYD·Tesla·Toyota",
    headline="...",
    summary_core="...",
    summary_details=["...", "..."],
    tag="중국EV",                             # # 없이 (또는 #포함도 허용)
    ticker_color="blue", tag_color="blue",
)
# pub_status='published', last_modified=now, fail_reason=NULL 자동 설정

# 실패:
db.mark_attempt_failed(article_id, reason='parse_fail: PerimeterX block')
# retry_count++, last_attempt=now. retry_count > 5 도달 시 자동 pub_status='failed'
```

## Cron 설정

```bash
# Stage 1 (수집, LLM 미사용)
hermes cron list                   # 확인
# id: b706d2818127
# Schedule: 0 * * * *
# Script: sa_collect.sh (--no-agent)

# Stage 2 (발행, Claude CLI subprocess)
# id: ba4f399d5e5c
# Schedule: 10,30,50 * * * *
# Script: sa_publish.sh (--no-agent)
```

**왜 `--no-agent --script` 모드?**
- Path A(hermes default LLM이 cron prompt를 받아서 실행) 대비 다음 이점:
  - 결정적·재현 가능 (스크립트가 동일 입력으로 동일 호출)
  - prompt가 코드에 박혀 있어 git/diff로 변경 추적 가능
  - 검증 단계가 Python으로 명시적 (JSON 추출 실패·필수 필드 누락·한자 검증 등 자동)
  - SKILL.md context 의존도 0 → SKILL.md 누락/오타가 cron 결과에 영향 없음
- 2026-05-26 17:53 cron prompt 모드 → script 모드로 전환. 이전 prompt 모드에서는 LLM이 ticker 인자를 publish_article에 누락하던 버그(envelope prefix가 그대로 남음) 발생.

## Dashboard (Web Viewer)

FastAPI + 정적 HTML. `~/Documents/sa-dashboard/app.py` + `static/index.html`.

### 주요 엔드포인트
- `GET /` — index.html
- `GET /api/articles?q=&ticker=&date_from=&date_to=&sort_by=&unread_only=&limit=&offset=` — published 행만
- `GET /api/article/{id}` — 단일 행 (deleted 제외)
- `GET /api/filters` — ticker/company 후보
- `PATCH /api/articles/{id}/read` — is_read 토글
- `DELETE /api/articles/{id}` — `pub_status='deleted'` 처리
- `GET /api/queue_stats` — `{pending, failed}` 카운트
- `GET /telegram` — telegram.html

### 운영
- uvicorn은 launchd plist로 keep-alive (Tailscale IP `100.109.86.85:8181` binding). 죽이면 자동 재시작.
- DB 변경 후 schema 의존 prepared statement가 꼬일 수 있음 → 의심 시 `kill <uvicorn_pid>` → launchd가 재spawn.

### 이미지/Markdown
- Obsidian wiki link `![[attach/x.png]]` + 표준 `![alt](attach/x.png)` 모두 지원 — `marked.parse()` **전에** 변환
- YAML frontmatter → `·` 머리표 글머리, source URL은 도메인만 표시

## Pitfalls

**DB ID vs email_id 절대 혼동 금지**
- `id` = SQLite AUTOINCREMENT, `email_id` = himalaya UID. 사용자가 "N번"이라고 하면 **반드시 email_id**.

**Cron 스크립트 경로**
- `~/.hermes/scripts/sa_*.sh`에 skill 경로(`~/.hermes/skills/sa-news/...`)가 하드코딩. skill 디렉토리가 rename되면 **silently fail**. 자동 curator가 디렉토리 이름을 정리할 가능성 있으니 `hermes cron list`로 정기 점검.
- 과거 이력: 2026-05-26 02:01에 curator가 `sa-news-monitor` → `sa-news`로 rename. cron의 `--skill` 참조가 stale해진 적 있음.

**Cron 스크립트 타임아웃**
- 기본 타임아웃 120초. `sa_publish.sh` → `sa_summarize_claude.py --batch 10`은 Claude CLI 호출로 120초 초과 가능.
- 해결: `~/.hermes/config.yaml`의 `cron.script_timeout_seconds`를 600으로 설정.
- 확인: `grep script_timeout ~/.hermes/config.yaml`

**SA 파서**
- 기사당 fetch 간격 **최소 10초**.
- Jina 응답을 단순 `[:10000]` 자르면 nav만 잡혀서 본문 사라짐. title 두 번째 등장 위치부터 자르는 패치가 핵심.
- `wait_until='networkidle'`은 SA에서 timeout. `wait_until='load'` + `sleep(2)`.
- `px-captcha`는 정상 페이지에도 있음 — 차단 기준으로 사용 금지.
- HTML 길이 < 9000자 + `Access to this page has been denied` = 차단.
- SVG-only 오검지: 본문 텍스트 < 800자 + `<path` > 20개일 때.
- 네비게이션 전용 응답 감지: 250자 미만 또는 article 키워드(NYSE/NASDAQ/said/CEO/Q1 등) 0개.

**전체 파서 체인 동시 차단 (systemic block)**
- Jina + Playwright + curl_cffi 3개 모두 동시 실패. IP 기반 강화 차단. 즉시 재시도 금지, 지수 백오프에 맡김. Jina API 업그레이드 또는 전용 프록시 IP 검토. 상세: `references/systemic-parser-block-2026-05-23.md`

**Claude CLI 응답 이슈**
- JSON 외 텍스트·코드블럭(```json) 섞여 나올 수 있음 → `extract_json()`의 정규식이 첫 `{...}` 블록을 잡음. 응답이 비거나 JSON 파싱 실패 시 `mark_attempt_failed(reason="JSON 파싱 실패: ...")`.
- ticker가 빈 문자열로 오면 envelope 값 유지 (덮어쓰지 않음).

**Dashboard 500**
- `summary_details` JSON corruption (한글 quote): `db.py`의 `row_to_dict()`와 `app.py`의 `get_article()`에 `ast.literal_eval` 폴백 적용됨.
- 운영 중 db.py 변경 후 uvicorn이 stale connection 잡고 응답 truncate되는 경우: uvicorn kill → launchd 재spawn.

**번역**
- 한자(U+4E00–9FFF) / 가나(U+3040–30FF) 출력 전 정규식 검증 필수.
- 중간점(`・`)은 한국어에 안 씀 → `·` 또는 공백.

**Python 3.9 호환성**
- 시스템 Python 3.9.6에서 `X | Y` union 타입 힌트 금지. `Optional[X]` / `Union[X, Y]` 사용. import 에러 먼저 `python3 -c "import db"` 확인.

## 관련 파일

- `scripts/sa_collect.py` — Stage 1 (수집). LLM·SA 페이지 미사용.
- `scripts/sa_summarize_claude.py` — Stage 2 본체. Claude CLI subprocess 호출.
- `scripts/sa_publish.py` — 레거시 CLI(`list`/`parse`/`stats`). sa_summarize_claude가 내부적으로 일부 함수 사용. 직접 cron이 호출하지는 않음 (2026-05-26부터).
- `scripts/sa_article_parser.py` — 파서 본체 (dashboard 사본과 동기화).
- `scripts/extract_sa_urls.py` — Stage 1 envelope 파서.
- `references/systemic-parser-block-2026-05-23.md` — 파서 체인 동시 차단 대응
- `references/sa-parser-svg-false-positive-2026-05-21.md` — SVG 오검지
- `references/sa-parser-navigation-only-content-2026-05-24.md` — nav-only 오검지
- `references/summary-details-json-corruption-2026-05-21.md` — JSON corruption 복원
- `references/json-ld-content-extraction.md` — JSON-LD description 활용
- `references/image-syntax-handling.md` — Obsidian + 표준 markdown 이미지 처리
- `references/json-corruption-fix.md` — summary_details 한글 quote 복원
- `references/obsidian-web-rendering-notes.md` — 정적 자산·Tailwind 충돌

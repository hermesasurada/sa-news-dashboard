# sa-news 작업 규칙

Seeking Alpha 속보 메일을 수집해 한국어로 요약하고 대시보드(8181)에 올리는 서비스다.
이 문서에는 **지금 지켜야 할 규칙**만 둔다. 도입 계기·소급 건수·백업 이름은 `docs/HISTORY.md`, 운영 절차는 `SKILL.md`·`deploy/DEPLOY.md`를 본다.

## 코드 배치 (2026-11-16 리팩토링)

| 파일 | 맡은 일 |
|---|---|
| `scripts/sa_collect.py` | 수집 흐름: 메일 읽기 → pending 적재 → seen 처리 |
| `collect_filters.py` | 수집 제외 규칙 전부(`is_*`, `excluded_reason`) |
| `scripts/extract_sa_urls.py` | himalaya 출력에서 기사 주소 추출 |
| `scripts/sa_summarize_claude.py` | 발행 흐름: 원문 → 요약 → 검증 → DB 발행 |
| `summary_contract.py` | 요약 계약: 지시문(`_PROMPT_TMPL`)·응답 검증(`validate`)·제목 앞 티커 병합·`_checked_summary` |
| `sa_llm.py` | Claude·Codex·Grok CLI와 Gemini API 호출기(실행·시간 초과·실패 기록은 `_guarded`·`_rc_failed` 공통) |
| `scripts/sa_publish.py` | 원문 받기(`parse`)를 별도 프로세스로 실행 |
| `sa_article_parser.py`, `sa_login_state.py` | SA 사이트 원문 받기(site 모드) |
| `grok_bridge.py`, `gdrive.py` | Grok Bot 원문 통로(grok 모드) |
| `db.py` | 연결, 기사 조회·검색, 읽음·삭제, 발행 대기열 |
| `db_schema.py` | 테이블·검색 색인 정의와 나중에 더한 열 |
| `summary_config.py` | 요약 슬롯 설정 |
| `company_table.py`, `foreign_tickers.py`, `ticker_names.py` | 티커 표·제목 보정·회사명 |
| `sa_url.py` | 기사 주소 다듬기(`strip_utm`) |
| `app.py` | FastAPI 엔드포인트 |
| `tools/` | 일회성 도구: 옛 HTML 대시보드 들여오기(`migrate.py`), 메일 시각 KST 소급(`backfill_email_time_kst.py`) |
| `static/app*.js` | 화면(아래 순서) |

- **규칙·열·화면 코드를 넣는 자리**: 수집 제외 규칙은 `collect_filters.py`, DB 열 추가는 `db_schema.add_missing_columns`(다른 모듈에서 `ALTER TABLE` 하지 않는다), 화면 코드는 해당 `app-*.js`.
- **화면 스크립트 순서**: `app-utils.js` → `app.js`(상태·공용) → `app-cards.js`(티커 표·카드) → `app-quote.js`(시세 팝오버) → `app-actions.js`(스와이프·읽음·삭제·토스트) → `app-feed.js`(목록·검색·무한 스크롤) → `app-settings.js`(글꼴·크기·모델) → `app-boot.js`. 전역 범위를 함께 쓰는 일반 스크립트라 읽는 순서가 실행 순서다. **`init()`이 든 `app-boot.js`는 반드시 마지막**이고, 파일을 더하면 `index.html`과 `tests/test_static_layout.py`의 순서 목록에 넣는다.
- **정적 파일 버전**: `app.root()`가 `/static/*.js`·`*.css` 주소에 mtime 버전을 패턴으로 붙인다. 캐시가 1년 고정(immutable)이므로 버전 없는 주소를 만들지 않는다. 프런트는 새로고침만으로 반영되고, `.py`를 고치면 `launchctl kickstart -k gui/$(id -u)/com.user.sa-dashboard`.
- **원문 받기는 별도 프로세스로 둔다**(`sa_summarize_claude.parse_article` → `sa_publish.py parse`). 시간 초과 때 브라우저까지 확실히 끊기 위한 장치다.
- 옛 설계·디버깅 메모(2026-05~08)는 `docs/archive/`에 있다 — 현재 구조와 다른 내용이 섞여 있어 규칙의 근거로 쓰지 않는다. **진입 파일·`tools/` 스크립트를 `--help`로 확인하지 않는다**(`backfill_email_time_kst.py` 등은 인자를 무시하고 실제로 돈다).
- **테스트**: `venv/bin/python -m pytest -q`, `node tests/test_app_utils.js`. 테스트는 이름을 가진 모듈을 직접 부르거나 patch한다(규칙은 `collect_filters`, 흐름은 `sa_collect`). 운영 DB를 건드리지 않는다 — `main()`·`app`을 부르는 테스트는 `db.init_db`를 막거나 `db.DB_PATH`를 임시 DB로 돌린다.
- 크론 진입점은 `~/.hermes/scripts/sa_{collect,publish,purge}.sh`이고 `deploy/hermes-scripts/`에 사본을 둔다. 둘을 함께 고친다.

## 수집 제외 규칙

메일 제목만 보고 판정한다(`collect_filters.excluded_reason`). 제외한 메일은 DB에 넣지 않고 읽음 처리만 한다.

- **규칙을 넣거나 넓힐 때**: 게시 중인 기사 제목 전체에 먼저 돌려 새로 걸리는 제목을 눈으로 확인하고, 걸린 게시 기사는 DB 백업 뒤 휴지통으로 옮기는 것까지 한 번에 한다.
- 일반 낱말 목록(`_PM_GENERIC` 등)을 늘릴 때도 같은 확인을 한다.

| 사유 | 제외하는 것 | 남기는 것 |
|---|---|---|
| 우선주배당 | 우선주 시리즈 배당 공시(`.PR.` 티커, Preferred 표지) | 보통주 배당 |
| 라운드업 | 주간 모음·스코어카드·갭핑 라운드업 | 특정 기업 기사 |
| 실적프리뷰 | 실적 발표 예정·프리뷰 | 실적 결과, 꼬리 문구 'ahead of earnings' |
| 펀드공시 | 펀드·전략의 분기 보유 변경·수익률 | 사명이 Strategy인 MSTR |
| 커버리지개시 | 증권사 커버리지 개시 | 보험·통신망의 coverage |
| ETF배당 | ETF·펀드 분배 선언 | 기업·리츠 배당 |
| 주가연속 | 연속 상승·하락의 지속·종료만 전하는 기사 | 재료가 있는 기사 |
| 지표스크린 | 퀀트·지표 등급으로 종목을 나열한 목록(복수형 stocks·순위 표현, `lead list of …`, 앞머리가 '(형용사)(섹터) stocks with/that') | 단일 종목의 공매도·과매도 언급, 질문형 분석, 실적·섹터 뉴스에 곁들인 순위 |
| 추천목록 | 증권사 Buy 목록·best ideas·conviction·top picks 명단 | 등급 변경·커버리지 개시와 함께 나온 top picks, 단수 'top pick' |
| 등락목록 | 앞머리가 목록 이름인 자동 생성 등락 목록(Midday Pulse, `S&P 500 gainers:`) | 섹터·주간 시황의 'leads gainers' |
| 월간순위 | 월 이름·한 달 등락이 기준인 섹터별 상위 종목 순위 | 분기 섹터 리뷰, 주간 시황, 월간 지수 기사 |
| 주가등락 | 회사 고유 재료 없이 등락폭만 전하는 기사 | 재료 낱말이 하나라도 있는 기사(실적·가이던스·등급·자금조달·행사·제품·질문형) |
| 퀀트등급 | SA 퀀트 등급·순위가 주제(Quant Rating, top Quant list, Strong Buy streak) | quantum·Quanta·Quantinuum, 증권사 Strong Buy 상향 |
| 애널리스트 | 등급 상·하향, 목표가 변경, 등급 유지, 지수·자산배분 전략 | 아래 참고 |

- **주가등락은 화이트리스트 방식**이다: 등락 문구(동사+N%) 앞은 회사명과 일반 낱말, 뒤는 `_PM_GENERIC`뿐이어야 제외한다. 재료 낱말을 금지하는 블랙리스트 방식은 고유 재료를 계속 놓쳐서 버렸다.
- **애널리스트 판정**: 제목을 `;`로 나눠 절마다 등급 문구를 찾는다. 등급 문구 **앞**이나 등급 없는 다른 절에 회사 고유 재료(`_AR_MATERIAL_RE`: 실적·가이던스·계약·인수·임상·FDA·출시 등)가 있으면 남기고, 등급 문구 **뒤**의 이유('on Marvell deal')는 리포트 근거라 제외한다. `upgrade/downgrade`·`Buy rating`은 증권사 이름(`_AR_BROKER_RE`)이 함께 있을 때만 인정한다 — 상품 업그레이드와 신용·ESG 등급은 남는다. 새 증권사 이름이 안 걸리면 `_AR_BROKER_RE`에 더한다. 등급 없이 견해만 전하는 기사는 범위 밖이다.

## 티커

- 제목 주체가 빠졌으면 포트폴리오 티커 목록과 별칭으로 보충한다(`foreign_tickers.missing_from_title`). ADR·현지 상장은 하나로 묶는다.
- 리서치 출처와 비교 대상 언급은 주체 후보가 아니다. 모호한 짧은 별칭은 추론하지 않는다.
- 심볼·회사명 짝은 함께 다루고, DB·API의 문자열 형식은 그대로 둔다.
- 티커 소급은 요약·읽음·게시 상태·기사 시각을 보존하고 DB 백업부터 한다. `scripts/backfill_ticker_subjects.py --exclude id,…`로 사람이 뺀 건을 제외한다.
- **같은 회사 심볼 묶음과 칩 표시 표는 증류 기업 등록부가 정본이다**(`company_table.py`가 `~/.hermes/scripts/distill/company_registry.py`를 읽는다). 새 OTC·ADR 심볼은 등록부 그 회사의 `other_symbols`에 넣고 sa에 표를 다시 만들지 않는다. 등록부를 못 읽으면 `company_table.snapshot.json`, 그것도 없으면 빈 표로 돈다.
- 칩 이름은 그 상장의 `chip_label`, 없으면 회사 정규 이름이다. 아시아 상장(.KS·.T·.TW·.HK·.SS·.SZ)은 이름 배지로 보인다. 시세 조회 상장은 회사 `symbol`이 해외 상장이면 그것, 미국 심볼이면 첫 해외 상장이다.
- **sa에 남는 고유 규칙**: 바꿔 보일 OTC 목록 `company_table.FOREIGN_KEYS`, 칩을 더할 심볼 `EXTRA_KEYS`, 접미사 없는 코드 `BARE_CODES`, 제목 별칭 `foreign_tickers._COMPANIES`(대소문자 구분), 병합 방향 `db.TICKER_ALIASES`(GOOGL→GOOG, 한국 코드→OTC).
- **제목 앞 티커는 기본으로 티커칩에 넣는다**(`summary_contract.merge_title_prefix`). 모델이 고른 티커 순서를 유지한 채 뒤에 붙이고, ETF와 비상장 표기도 그대로 넣는다.
- **숫자 종목코드 칩은 기업명으로 표기한다**(2330.TW → TSMC). `/api/filters`의 `home_names`를 `app-cards.js`의 `codeLabel`이 쓴다. 영문 티커는 그대로이고, 시세 조회·검색은 계속 코드로 한다.
- 포트폴리오 이름이 전부 대문자라 별칭이 안 생기는 회사(CXMT)는 `foreign_tickers._COMPANIES`에 직접 넣는다.
- **`missing_from_title` 오탐 가드를 지우지 않는다**: Leonardo DRS, `X-class/-like` 복합어, `former`·`aboard` 앞말, ClearBridge 'OO Strategy', Mitsubishi 계열사, Eaton Fiber/Vance, Reliance Industries, Merck KGaA, 다른 Brookfield 상장사, 'for Airbus aircraft', BlackRock 발언·펀드 언급.

## 요약 모델

- 모델 목록·표시 이름·추론 단계는 공용 LLM 카탈로그(`~/projects/hermes-llm-log/llm_catalog.py`)에서 온다. 화면에 독립된 선택 목록을 만들지 않는다.
- **카탈로그는 부가 정보다 — 못 불러와도 요약이 멈추면 안 된다.** import는 `try/except Exception`으로 감싸고, 경로는 `sys.path.append`로 뒤에 붙인다. 모델 계열은 선택지 소속이 아니라 `llm_catalog.resolve()`의 provider → 모델 ID 접두어 순으로 판단한다(`summary_config.family`). 검증은 `tests/test_catalog_isolation.py`.
- 저장된 선택은 카탈로그 장애나 모델 비활성화 때도 보존한다. 과거 기사의 실제 모델 ID는 바꾸지 않는다.
- **슬롯 설정**: 칸마다 모델+추론, 1~5칸, 같은 모델 여러 칸 가능. 저장은 `sa_news.db`의 `app_settings.summary_config`, 형식 `{"slots": [{model, effort}]}`. 옛 형식은 읽을 때 슬롯으로 옮기고 POST는 slots만 받는다.
- **라운드로빈**: 기사 id로 시작 칸을 돌리고(`id % 칸 수`), 실패하면 나머지 칸이 순서대로 받는다. 같은 모델은 한 번만 부르고 설정 밖 모델로는 가지 않는다(`summary_chain`).
- **성공은 응답 문자열이 아니라 JSON·출력 검증·필수 필드까지 통과한 것**이다. 어느 단계든 실패하면 다음 칸으로 넘긴다(`_checked_summary`).
- 설정 창의 모델 칸은 공용 `static/model-selector.{js,css}`(wm·yt·td·xw와 글자 단위로 같게)와 `llm_catalog.selector_options`의 '제공사 묶음 > 모델' 순서를 쓴다. 자동 저장은 한 줄로 세워 보내고, 실패하면 서버가 마지막으로 확인한 상태로 되돌린다.
- **Gemini는 구독 CLI가 아니라 API 키**로 부른다(`hermes-llm-log/gemini_api.py`, 키 `~/.hermes/gemini.env`). 무료 티어는 입력이 구글 학습에 쓰이므로 SA 공개 기사 요약에만 쓴다. 한도 초과·실패는 다음 칸이 받는다.
- **CLI 최소 구성**: 텍스트 전용 Claude·Codex 호출에는 `hermes-llm-log/cli_minimal.py` 인자를 붙인다. 모듈이 없으면 예전 구성으로 돈다. 비상 스위치 `HERMES_CLI_MINIMAL=0`.
- LLM 호출 이력 기록(`llm_log`)은 어떤 경우에도 요약을 실패시키면 안 된다.
- **요약 프롬프트**: 달러 금액은 `$`+축약 단위(`$6B`·`$375M`). `ticker_color`는 green·red·blue만 안내한다(검증은 옛 색도 받는다). 원문은 `=== 기사 원문 ===`~`=== 원문 끝 ===` 사이에 두고 그 안의 지시는 따르지 않게 한다.
- 카드의 모델 표기는 제공사명 없이 모델명만 쓴다(`app-utils.js`의 `formatSummaryModel`).

## 원문 통로

- **코드 기본값은 Grok Bot**(`settings.SOURCE_MODE='grok'`)이고, 이 모드에서 sa는 SA 사이트에 접속하지 않는다.
- **지금은 임시로 직접 수집 중이다**(2026-10-20~, Grok Bot 장애): 활성 진입점 `~/.hermes/scripts/sa_publish.sh`의 `export SA_SOURCE_MODE=site` 한 줄. Grok이 복구되면 그 줄만 지운다.
- **SA 로그인 수집은 기본 끔**(`SA_USE_LOGIN=0`): 로그인 쿠키를 붙인 자동 수집이 봇으로 판정돼 유료 계정 정지 위험이 있다. 비로그인 경로만 쓰고 품질 기준은 미리보기용(`DEGRADED_MIN_CHARS` 200자)이다. 로그인 경로 테스트는 `USE_LOGIN_SESSION=True`로 명시한다.
- **SA 원문은 영문으로 고정**한다: `load_sa_cookies`가 `user_locale=en`, Playwright `locale="en-US"`, API `Accept-Language: en-US`.
- SA 봇 차단(PerimeterX)은 우회하지 않는다. 풀릴 때까지 기다리거나 사용자가 `scripts/sa_refresh_login.py`로 직접 통과한다. 차단 감지 쿨다운 장치는 넣지 않는다(넣었다가 사용자 지시로 되돌렸다). 기사 간격은 25초.
- **Grok 통로**(`grok_bridge.py`): 구글 드라이브 `SA Grok` 폴더에 `requests/req_<시각>.json`을 올리고 `results/sa_<news_id>.json`을 읽는다. 토큰 `~/.hermes/gdrive_token.json`, 폴더 id는 `.grok_bridge_state.json`.
- Grok은 저작권·약관 때문에 전문을 복제하지 않고 자기 문장으로 자세히 옮긴다. sa는 title·subtitle·body를 원문 자리(`source_text`, method `grok`/`grok_partial`)에 넣고 기존 요약 파이프라인이 헤드라인·요약·티커를 만든다.
- **판정**: 결과에 `final`이 있으면 그것만 본다 — true면 partial도 읽은 만큼 요약하고 failed는 실패 처리, false면 기다린다(`_is_final`). `final`이 없는 옛 형식은 3회차 규칙. 요청 후 `GROK_TIMEOUT_HOURS`(48) 무응답이면 failed. 같은 이름이 둘이면 최신 modifiedTime.
- 결과 JSON 원본은 `articles.grok_result_json`에 남긴다(Grok이 5일 뒤 드라이브에서 지운다). 요청 파일은 7일 뒤 sa가 지운다. 수동 `--id` 재처리도 grok 모드에서는 저장 원문만 쓴다.

## 화면

- **공용 파일은 다른 저장소와 글자 단위로 같게 유지한다**: `hermes-theme.{js,css}`(sa·td·wm), `model-selector.{js,css}`.
- 색상 모드: 선택값은 localStorage `hermes-theme`, 실제 색은 `<html data-theme>`로만 건다. 다크 보정은 `:root[data-theme="dark"]` 절에 둔다. 스크립트는 `<head>`에서 defer 없이 불러 깜빡임을 막는다.
- **상단은 2줄**: 1줄 = 타이틀 + [설정][색상 모드][휴지통], 2줄 = 검색어 + 검색·정렬 방향·초기화·미읽음(눈 아이콘 안에 건수). 정렬 기준은 이메일 시간 고정이다. 결과 건수 줄은 숨긴다(`#stats` hidden). 티커 선택 버튼·모달은 없다(검색어로 찾는다). 모바일(≤680px)은 아이콘만.
- 상단은 스크롤해도 고정된다(`.hermes-gnb`). 조상에 `overflow-x: hidden`을 두면 sticky가 깨지므로 `clip`을 쓴다. z-index(40)는 모달보다 낮게 둔다.
- 요약 글꼴·글자 크기는 설정 창 안에 있다. 글꼴 목록은 공용 `hermes-reader-fonts/fonts.js`가 정본이다. 글자 크기는 12~17(기본 13), localStorage `saReaderSize` → body `--reader-scale`, 요약 본문만 바뀐다.
- **안읽음 표시는 제목 앞 작은 점**이다(wm·sa·td 통일). 좌측 세로줄·캡슐 바·inset 줄 강조를 다시 넣지 않는다.
- **카드 번호는 DB 기사 ID(`articles.id`)**이고 클릭하면 `sa 1234` 형식으로 복사한다. 2026-10-08 이전에 사용자가 말한 번호는 메일 ID(`email_id`)일 수 있다.
- 안읽음만 보기에서 읽음 처리로 카드가 사라지면 '되돌리기' 토스트를 6초 띄운다(삭제 되돌리기와 같은 `showToast`).
- **팝업이 열려 있는 동안 뒤 화면 스크롤을 막되 화면 배치는 건드리지 않는다**: 스크롤 입력만 막는다. body를 고정하거나 `overflow: hidden`을 걸면 상단 고정 영역이 사라진다.
- **모바일 무한 스크롤**(≤640px): 목록 끝이 화면 아래 600px 안에 들어오면 다음 15건을 붙인다. 다음 시작 위치는 화면의 카드 수, 겹친 카드는 `data-id`로 거르고, 검색·필터가 바뀌면 `_feed.seq`로 늦은 응답을 버린다. PC는 페이지 버튼.
- **안드로이드 크롬**: `.swipe-row { touch-action: pan-y }`와 `touchcancel` 복귀를 유지한다. 모바일(≤480px) 토스트는 `left/right: 14px` 고정, 숨김은 아래로 내리기만 한다.
- **시세 팝오버**(wm·sa·td·xw 같은 함수 `renderQuoteStats`): `RSI 일·주·월`, `BB 일·주·월`을 각각 한 줄, 등락은 `1W`·`1M`만. 값은 포트폴리오 `/api/chart`의 `quote_stats`를 `quote_service.get_price_quote`가 그대로 옮긴다. BB 음수는 `−`(U+2212)로 쓴다. 값이 없으면 줄을 숨긴다.

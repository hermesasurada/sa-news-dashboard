# 리팩토링 우선순위

판단 기준은 `데이터 손실 가능성 → 외부 입력 안전성 → 장애 복구성 → 유지보수 비용 → 미관` 순입니다.

## P0 — 즉시 반영 완료

| 항목 | 이유 | 상태 |
|---|---|---|
| 삭제·발행 상태 전이 원자화 | 늦게 끝난 worker가 삭제 기사를 되살릴 수 있었음 | 완료 |
| Claude timeout·배치 예외 격리 | timeout 뒤 grok 폴백을 보장하고 한 기사의 예외가 후속 기사를 굶기지 않게 함 | 완료 |
| collect/publish 종료코드 구분 | 성공 `0`, 인프라 실패 `1`, 기록된 부분 실패 `2`를 운영자가 구분할 수 있게 함 | 완료 |
| 검색 Enter 단일 바인딩 | inline·JS 이중 바인딩으로 같은 검색이 두 번 실행되던 문제 제거 | 완료 |
| 모델 라벨 일반화 | 이동 별칭의 `claude-opus-5`와 날짜 suffix 모델도 버전이 보이게 함 | 완료 |
| 배포 경로 정합성 | repo 셔임·문서의 폐기된 `~/Documents` 경로를 실제 경로로 교정 | 완료 |
| FTS5 검색어 정규화 | 따옴표·연산자 입력이 API 500을 만들 수 있었음 | 완료 |
| 외부 기사/LLM 문자열 HTML escape | 저장형 XSS 가능성 차단 | 완료 |
| 기사 URL scheme 제한 | `javascript:` 등 비정상 링크 차단 | 완료 |
| himalaya return code 확인 | 메일 명령 실패를 “미읽음 없음”으로 오판하지 않게 함 | 완료 |
| 한자·가나·Markdown 출력 검증 | 프롬프트 규칙과 실제 저장 검증을 일치시킴 | 완료 |
| 임시 DB 회귀 테스트 | 운영 DB 없이 상태 전이와 검색을 검증 | 완료 |

## P0b — 본문 파이프라인 (2026-08-23)

| 항목 | 상태 |
|---|---|
| `source_text` 저장 + 700자/잠금 품질 게이트 | 완료 |
| Fetch 순서: Playwright → curl → 쿠키 API. 비로그인 미리보기는 기본 미사용 | 완료 |
| `processing_attempts` 단계 로그 | 완료 |
| `--reuse-source` 재요약 | 완료 |
| 주간 헤드라인/스코어카드/갭핑 라운드업 수집 제외 | 완료 |

## P1 — 다음 작업 권장

1. 접근 제어와 네트워크 경계
   - 현재 API에는 인증과 CSRF 방어가 없습니다.
   - Tailscale ACL로 사용자·기기를 제한하고, 외부 공개가 필요할 때만 애플리케이션 인증을 추가합니다.
   - 예상 효과: 오작동·무단 삭제 위험 감소. 난이도: 중간.

2. 명시적인 DB 마이그레이션 버전
   - 현재 `init_db()`가 컬럼 존재 여부를 보고 즉석 마이그레이션합니다.
   - `schema_version`과 순차 migration을 도입하고 시작 전 백업·rollback 절차를 만듭니다.
   - 예상 효과: 배포 중 스키마 실패 위험 감소. 난이도: 중간.

3. 운영 관측성
   - `/api/health`를 launchd health check에 연결합니다.
   - collect/publish의 배치 ID, 처리 시간, 실패 유형을 구조화 로그로 남기고 pending/failed 임계치 알림을 추가합니다.
   - 현재 cron 로그는 50회(30분 주기 기준 약 25시간)만 보존되므로, 공급자별 시도·결과를 append-only
     `processing_attempts` 테이블에도 남겨 성공 후 지워지는 실패 원인을 보존합니다.
   - 예상 효과: 조용한 cron 실패 탐지 시간 단축. 난이도: 낮음~중간.

## P2 — 구조 개선

1. 티커 규칙 단일화 — **완료(2026-11-11)**
   - 같은 회사 심볼 묶음·칩 표시 표는 증류 기업 등록부에서 만들고(`company_table.py`) `/api/filters`로 내려 준다.

2. `db.py` 분해 — **구조 정의만 분리(2026-11-16)**
   - 테이블·검색 색인 정의와 열 추가는 `db_schema.py`. 조회·발행 대기열은 `db.py`에 둔다 — 지금 규모(600줄)에서 더 나누면 얻는 것보다 import 경로 변경 비용이 크다.

3. 프런트 모듈화 — **파일 분할 완료(2026-11-16)**
   - `app.js`를 `app-*.js` 7개로 나눴다(전역 범위를 함께 쓰는 일반 스크립트).
   - HTML inline handler를 이벤트 위임으로 바꾸는 일은 보류: 강한 Content-Security-Policy를 적용할 계획이 생기면 한다.

4. 레거시 컬럼 정리 — 완료
   - `summary_core`, `tag`, `tag_color`, `email_body` 및 메일 본문 추출 경로는 제거됨.

5. Chart.js 로컬 고정 — 해당 없음
   - Chart.js를 쓰던 통계 화면이 없어져 외부 스크립트 의존이 남아 있지 않다.

6. 수집 제외 규칙 분리 — **완료(2026-11-16)**
   - `scripts/sa_collect.py`의 규칙 14종을 `collect_filters.py`로 옮겼다.

7. LLM 호출기 이름·자리 — **완료(2026-11-17)**
   - `scripts/sa_claude_cli.py` → 루트 `sa_llm.py`. Claude·Codex·Grok 호출기의 시간 초과·예외·종료 코드 처리를 `_guarded`·`_rc_failed`로 묶었다.

## P3 — 개발 경험

- Ruff 또는 동등한 formatter/linter와 정적 타입 검사를 CI에 추가
- 가짜 himalaya·SA parser·Claude CLI를 사용한 전체 pipeline 통합 테스트
- 의존성 업데이트 자동화와 Playwright 브라우저 버전 검증
- `SKILL.md`, `README.md`, `deploy/DEPLOY.md` 정합성을 확인하는 문서 테스트

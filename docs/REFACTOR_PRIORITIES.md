# 리팩토링 우선순위

판단 기준은 `데이터 손실 가능성 → 외부 입력 안전성 → 장애 복구성 → 유지보수 비용 → 미관` 순입니다.

## P0 — 즉시 반영 완료

| 항목 | 이유 | 상태 |
|---|---|---|
| 삭제·발행 상태 전이 원자화 | 늦게 끝난 worker가 삭제 기사를 되살릴 수 있었음 | 완료 |
| Claude subprocess 실제 timeout | stdout 대기 중에는 기존 timeout이 작동하지 않았음 | 완료 |
| FTS5 검색어 정규화 | 따옴표·연산자 입력이 API 500을 만들 수 있었음 | 완료 |
| 외부 기사/LLM 문자열 HTML escape | 저장형 XSS 가능성 차단 | 완료 |
| 기사 URL scheme 제한 | `javascript:` 등 비정상 링크 차단 | 완료 |
| himalaya return code 확인 | 메일 명령 실패를 “미읽음 없음”으로 오판하지 않게 함 | 완료 |
| 한자·가나·Markdown 출력 검증 | 프롬프트 규칙과 실제 저장 검증을 일치시킴 | 완료 |
| 임시 DB 회귀 테스트 | 운영 DB 없이 상태 전이와 검색을 검증 | 완료 |

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
   - 예상 효과: 조용한 cron 실패 탐지 시간 단축. 난이도: 낮음~중간.

## P2 — 구조 개선

1. `db.py` 분해
   - `schema`, `article_repository`, `publish_queue`, `statistics`로 나눕니다.
   - 외부 스크립트가 `db.py`를 직접 import하므로 기존 함수는 facade로 한 릴리스 유지합니다.

2. 프런트 이벤트 모듈화
   - 현재 HTML inline handler 때문에 강한 Content-Security-Policy 적용이 어렵습니다.
   - 이벤트 위임 방식으로 전환하고 검색·카드·시세·스와이프 모듈을 분리합니다.

3. 레거시 컬럼 정리
   - `summary_core`, `tag`, `tag_color` 사용량을 확인한 뒤 백업 DB에서 제거 migration을 검증합니다.
   - SQLite 테이블 재작성 작업이므로 P0/P1보다 뒤에 둡니다.

4. Chart.js 로컬 고정
   - 통계 화면이 jsDelivr 장애와 외부 네트워크에 의존하지 않도록 검증된 파일을 정적 자산으로 고정합니다.

## P3 — 개발 경험

- Ruff 또는 동등한 formatter/linter와 정적 타입 검사를 CI에 추가
- 가짜 himalaya·SA parser·Claude CLI를 사용한 전체 pipeline 통합 테스트
- 의존성 업데이트 자동화와 Playwright 브라우저 버전 검증
- `SKILL.md`, `README.md`, `deploy/DEPLOY.md` 정합성을 확인하는 문서 테스트

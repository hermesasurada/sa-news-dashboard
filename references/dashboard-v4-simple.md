# SA Dashboard v4 — 심플 단일 페이지 구조

2026-05-13 redesign. 기존 복잡한 사이드바/템플릿/JSON 기반 네비게이션 폐기.

## 구조
```
루트 index.html (정적 HTML, JavaScript 없음)
  헤더: "📊 SA 뉴스 대시보드"
  날짜별 섹션 (desc order):
    2026-05-13 (25 건)
      버튼 3 열 그리드 (모바일 2 열):
        17:19 — 카드 2 개 → detail 페이지 링크
        15:07 — 카드 2 개 → detail 페이지 링크
        ...
    2026-05-12 (49 건)
      ...
```

## detail 페이지
- 파일명: `sa_dashboard_YYYYMMDD_HHMM.html`
- 위치: `YYYY-MM-DD/sa_dashboard_YYYYMMDD_HHMM.html`
- 카드 구조: `<div class="card">` 중첩 div 포함, depth 카운팅으로 추출

## 생성 스크립트
- `~/.hermes/scripts/update_sa_dashboards.py`
- `generate_index_html()`: 날짜별 섹션 + 3 열 버튼 자동 생성
- `sync_date_dirs()`: REPORTS_DIR → DASH_DIR 날짜 디렉토리 복사
- `extract_card_info()`: depth 카운팅 기반 중첩 div 파싱

## CSS
- 데스크탑: `grid-template-columns: repeat(3, 1fr)`
- 모바일: `grid-template-columns: repeat(2, 1fr)` (max-width 600px)

## 파일명 규칙
- 파일명: `sa_dashboard_YYYYMMDD_HHMM.html`
- HHMM 은 **KST 기준** (`datetime.now(timezone(timedelta(hours=9)))`)
- 크론 세션에서 UTC 가 기본이면 +9 시간 명시 필요

## Pitfalls
- **broken dashboard cleanup**: 2026-05-13 22:18 대시보드가 카드 0개로 생성되어 git push까지 됨. 삭제 시 `git rm` + `index.html`에서 링크/건수 manual update 필요. `update_sa_dashboards.py`가 자동 갱신 안 되는 경우 수동 보정.
- **index.html stale**: dashboard HTML 파일 삭제 후 `index.html`이 오래된 링크를 유지할 수 있음. `update_sa_dashboards.py` 실행 시 regenerated 되지만, 수동 삭제 시 직접 grep/sed로 제거해야 함.
- **cron next_run_at stagnation**: SA News Generator + Dashboards Pusher 크론이 `next_run_at`을 과거로 고정하고 실행 안 되는 현상 확인됨. 수동 실행 필요 시 명시.
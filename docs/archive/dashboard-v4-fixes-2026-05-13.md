# SA Dashboard v4 — 2026-05-13 Final Fixes

## Filename Timezone Bug
**Problem:** Cron 세션에서 `datetime.now()`가 UTC 반환 → 파일명 9시간 앞섬 (예: 19:55 KST인데 파일명 2015)
**Fix:** 크론 프롬프트에 `datetime.now(timezone(timedelta(hours=9)))` 명시. 파일명은 KST 기준.

## himalaya JSON ANSI 코드
**Problem:** `envelope list --output json`이 ANSI 색상 코드를 stdout에 섞어 출력 → `json.loads()` 실패
**Fix:** `re.sub(r'\x1b\[[0-9;]*m', '', output)` 후 `output.find('[')`로 JSON 시작 위치 찾음. `startswith('202')` 필터는 무효.

## extract_card_info 중첩 div
**Problem:** `re.findall(r'<div class="card">(.*?)</div>')`는 중첩 div를 못 잡고 첫 내부 `</div>`에서 멈춤
**Fix:** `<div class="card">` 시작 위치 찾고, `pos = start + 1`부터 depth=0으로 시작해 matching `</div>` 찾을 때까지 열림/닫힘 세기.

## ticker 클래스 포맷 불일치
**Problem:** `class="ticker ticker-blue"` (하이픈)과 `class="ticker orange"` (공백) 양식 혼재
**Fix:** Regex `<span class="ticker\s+[^\"]+">`로 양쪽 지원.

## sync_date_dirs 누락
**Problem:** `update_sa_dashboards.py`가 REPORTS_DIR → DASH_DIR 날짜 디렉토리 복사 안 함 → GitHub Pages에 파일 안 올라감
**Fix:** `sync_date_dirs()` 함수 추가, `main()`에서 호출 필수.

## 크론 프롬프트 구조
크론 프롬프트는 단순하게 유지: 이메일 체크 → HTML 생성 → Telegram 전송 → 스크립트 호출. inline bash/python one-liner은 실패율이 높음.

## v4 레이아웃 구조
- 루트 index.html: 정적 HTML, JavaScript 없음
- 날짜별 섹션 (desc order): `2026-05-13 (25건)`
- 버튼 3열 그리드: `grid-template-columns: repeat(3, 1fr)`
- 모바일 2열: `@media (max-width: 600px) { grid-template-columns: repeat(2, 1fr); }`
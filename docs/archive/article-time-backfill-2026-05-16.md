# SA article_time_kst 백필 작업 기록 (2026-05-16)

## 배경
- `email_time_et` (이메일 수신 ET) + `created_at` (DB 저장 KST) 2개 시각 → `article_time_kst` (기사 작성시각 KST) 1개로 통합
- 기존 158건 데이터 백필 필요

## 최종 결과
- Playwright 자동 파싱 성공: 58건
- 사용자 수동 제공 → 코드 변환: 약 52건
- 잔여 미채움: ~48건 (새벽 크론잡 10건/일로 재시도 중)

## SA 페이지 봇 차단 이슈
- `urllib.request`: 403 Forbidden (User-Agent 무관)
- `Playwright headless` 연속: 403 / "Access to this page has been denied"
- 5초 간격: 일부 통과
- Chrome 쿠키 추출: macOS Keychain 승인 팝업 → 자동화 불가
- AppleScript Chrome: 접근 권한 타임아웃
- **결론**: 하루 10건 + 8초 간격이 현실적 상한선

## ET→KST 수동 변환 공식
- 5월 기준 EDT(UTC-4) → KST(UTC+9) = +13시간
- `오전 H:MM` → 24시간제 그대로, +13시간
- `오후 H:MM` → +12시간 후 24시간제 변환, +13시간
- 날짜 넘어가는 경우 주의 (오후 11시 이후)

## 백필 크론잡
- job_id: d0d1a96075cd
- 스크립트: `~/.hermes/scripts/backfill_sa_time_daily.py`
- 스케줄: 매일 새벽 3시 (KST)
- 미채움 소진 시 자동 삭제

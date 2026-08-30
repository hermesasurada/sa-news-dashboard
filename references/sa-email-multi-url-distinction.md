# SA 이메일 다중 URL 구분 패턴

## 배경
SA 이메일 본문에는 여러 seekingalpha.com/news/ URL이 포함될 수 있음:
- **메인 기사 URL**: 이메일 제목/본문 상단에 있는 실제 처리 대상 기사
- **"You may also like" 섹션**: 관련 기사 URL (처리 대상 아님)

## 구분 방법
1. **himalaya message read** 출력에서 `aHR0` base64 URL을 모두 추출
2. 디코딩 후 **가장 먼저 등장하는** `seekingalpha.com/news/` URL이 메인 기사
3. "You may also like" 섹션의 URL은 본문 하단에 위치 — 디코딩 순서상 뒤쪽

## 주의사항
- base64 URL 추출 시 `grep -o 'aHR0[sA-Za-z0-9+/=]*'`로 **모든** URL을 먼저 추출
- 디코딩 후 순서 유지 — 첫 번째가 메인 기사
- 이미 읽은 이메일 수동 처리 시 이 패턴 필수 (extract_sa_urls.py는 미읽음만 처리)

## 관련
- SKILL.md: "이미 읽은/누락된 SA 이메일 수동 처리" 섹션
- references/sa-email-b64-url-extraction-manual.md

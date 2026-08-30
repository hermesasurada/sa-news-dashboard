# article_time_kst 마이그레이션 (2026-05-16)

## 변경 내용
- `email_time_et` deprecated (DB 컬럼 보존, 사용 안 함)
- `article_time_kst` 컬럼 추가: SA 페이지에서 파싱한 기사 작성시각 KST
- `created_at` 은 DB에만 보존, 카드에 표기 안 함
- 카드에는 `article_time_kst` 만 표기 (없으면 시간 미표시)

## 마이그레이션 SQL
```sql
ALTER TABLE articles ADD COLUMN article_time_kst TEXT;
```

## db.py insert_article 시그니처 변경
```python
# 변경 전
def insert_article(..., email_time_et: str = "", email_id: str = None)

# 변경 후
def insert_article(..., email_time_et: str = "",  # deprecated
                   email_id: str = None,
                   article_time_kst: str = "")    # 기사 작성시각 KST
```

## index.html 카드 렌더링 변경
```javascript
// 변경 전
const timeStr = dt.toLocaleTimeString(...);  // created_at 기반
`<span class="card-time">${a.email_time_et || ''}</span>`
`<span class="card-date">🗓 ${dateStr} ${timeStr}</span>`

// 변경 후
const timeLabel = a.article_time_kst || '';
`${timeLabel ? `<span class="card-time">${timeLabel}</span>` : ''}`
// card-date 라인 제거됨
```

## SA 페이지 시간 파싱 — 검증된 사항

### 날짜 형식
- SA news 페이지는 `<time datetime>` 태그나 JSON-LD `datePublished` 없음
- JS 렌더링 후 텍스트로 삽입: `"May 14, 2026, 5:00 AM ET"`
- regex 패턴: `r'(\w+ \d{1,2},\s*\d{4}),\s*(\d{1,2}:\d{2}\s*[AP]M)\s*ET'`

### 파싱 방법 비교
| 방법 | 결과 |
|------|------|
| urllib (User-Agent 설정) | 403 Forbidden — 연속 요청 즉시 차단 |
| mcp_browser_navigate | CAPTCHA ("Access to this page has been denied") |
| Playwright `wait_until='networkidle'` | Timeout 25초 초과 |
| **Playwright `wait_until='load'` + `sleep(2)`** | **✅ 작동 확인** |

### 봇 차단 패턴
- 약 20~30건 연속 요청 후 Cloudflare 차단 시작
- 차단된 경우 "Access to this page has been denied" 타이틀, HTML 9KB 내외
- 차단은 일시적 (일정 시간 후 자동 해제)
- 해결책: `sleep(2)` 이상 유지, 실패한 건은 빈 문자열로 저장 후 나중에 재실행

## 백필 스크립트
`~/projects/sa-news/backfill_article_time_v2.py`
- 대상: `article_time_kst IS NULL OR article_time_kst = ''` 인 행
- Playwright 헤드리스 브라우저로 각 URL 방문
- 성공 즉시 `UPDATE articles SET article_time_kst = ?` 커밋
- 연속 실행 시 봇 차단으로 일부 실패 → 재실행으로 점진적 보완 가능

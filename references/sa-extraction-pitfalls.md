# SA Article Extraction Pitfalls & Solutions

## 1. web_extract Returns Wrong Content
`web_extract` on SA news URLs frequently returns **wrong content**. The URL may:
- Redirect to a completely different article
- Serve cached/stale content
- Trigger bot detection (CAPTCHA)

**Evidence (2026-05-13)**: NBIS URL returned George Weston earnings; SATL URL returned STERIS earnings.

**Solution**:
1. **Primary source**: Extract from email body (`himalaya message read <ID>`)
2. **Secondary source**: `web_extract` — but VERIFY title matches email subject
3. **Fallback**: Use headline + preview text from email if body is truncated
4. **Never trust** web_extract output without cross-checking against email subject

## 2. PerimeterX CAPTCHA Blocking

### Problem
SA uses PerimeterX (HUMAN Security) to block automated access. Symptoms:
- HTTP 403 Forbidden
- HTML length < 9000 chars
- "Access to this page has been denied" in response
- `px-captcha` title tag (FALSE POSITIVE — SA pages always contain this string)

### 3-Stage Fallback Architecture (v3.3.0, 2026-05-22 — 인증 없음)

**Script**: `scripts/sa_article_parser.py` — use this for ALL SA page parsing.

**Fallback order**:
1. **Playwright stealth + persistent profile** — `launch_persistent_context(user_data_dir=~/projects/sa-news/pw_profile)` + `add_init_script(STEALTH_INIT)` masking `navigator.webdriver`/`plugins`/`chrome.runtime`. 누적된 브라우저 상태 재사용.
2. **Jina Reader** (`https://r.jina.ai/{url}` + `Accept: application/json`) — 외부 reader proxy. PerimeterX를 Jina 측에서 처리. 무료 tier ~20 RPM.
3. **curl_cffi impersonate 로테이션** — `chrome124` → `safari17_2` → `edge99`, 각 시도 간 2s sleep. TLS/JA3 fingerprint 다양화.

### How It Works
```python
import sys
sys.path.insert(0, '/Users/yhandhs/.hermes/skills/sa-news-monitor/scripts')
from sa_article_parser import parse_sa_article

result = parse_sa_article(article_url)
# result['success'] == True → use result['content'] for summary
# result['published_time_kst'] → use as article_time_kst
# result['method'] → 'playwright_stealth' | 'jina_reader' | 'curl_cffi_<imp>'
# result['success'] == False → DO NOT save to DB, DO NOT mark read
```

### Removed in v3.3.0
- **세션 쿠키 (sa_cookies.json)**: Google OAuth 의존성 + 잦은 만료로 실효성 없음
- **sa_login.py**: 더 이상 불필요 (삭제됨)
- **requests + cookies fallback (구 4단계)**: 쿠키 의존이라 함께 제거

### Block Detection (accurate criteria)
- HTML length < 9000 chars
- "Access to this page has been denied" string
- HTTP 403
- **SVG-only false positive**: 텍스트 < 800자 + `<path` > 20개 (v3.3.0 추가)
- **NOT** `px-captcha` in HTML (SA pages always contain this string — it's a false positive)

## 3. Browser Access
SA blocks automated browsers with CAPTCHA. Do not attempt `browser_navigate` on SA article pages.

# SA 기사 시각 파싱 — curl 기반 방법 (Playwright 미설치 환경)

**작성일**: 2026-05-18
**확인**: 이 환경에서 Playwright가 미설치됨. `curl` + HTML 파싱이 주 방법.

## 방법

```bash
curl -s -L -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36" URL -o /tmp/sa.html
```

## 차단 판별

- 응답 크기 < 9000자 → 차단됨 (5KB 정도)
- `px-captcha` 문자열 포함 → CAPTCHA overlay

## 파싱 우선순위

### 1. JSON-LD datePublished (가장 신뢰도 높음)
```bash
grep -oE '"datePublished":"[^"]+"' /tmp/sa.html | head -1
```
- PerimeterX CAPTCHA가 있어도 HTML에 포함됨
- ISO 8601 형식: `2026-05-18T11:57:18.000Z`
- UTC → KST = +9시간

### 2. ET 텍스트 패턴
```bash
grep -oE '\w+ \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M ET' /tmp/sa.html | head -1
```
- 형식: `May 18, 2026, 7:57 AM ET`
- EDT (3~11월): UTC-4 → KST = +13시간
- EST (나머지): UTC-5 → KST = +14시간

### 3. time datetime 태그
```bash
grep -oE 'datetime="[^"]+"' /tmp/sa.html | head -1
```

## 폴백

curl 차단 시 (`web_extract`로 콘텐츠 확인 가능하나, 시간 정보는 없음):
- `web_extract`는 별도 경로라 CAPTCHA와 무관하게 동작
- 시간 정보는 email body의 SA timestamp로 대체 불가 (1줄 미리보기만 포함)
- 이 경우 article_time_kst = 빈 문자열 → DB 저장 금지

## 실제 확인 사례 (2026-05-18)

| Email ID | curl 결과 | datePublished | KST |
|----------|-----------|---------------|-----|
| 420 | CAPTCHA (539KB) | 2026-05-18T11:57:18Z | 20:57 |
| 419 | CAPTCHA (544KB) | 2026-05-17T13:42:15Z | 22:42 |
| 418 | CAPTCHA (552KB) | 2026-05-18T11:48:41Z | 20:48 |
| 417 | CAPTCHA (544KB) | 2026-05-18T11:47:37Z | 20:47 |
| 416 | 차단 (5KB) | 없음 | — |
| 415 | CAPTCHA (553KB) | 2026-05-18T11:29:19Z | 20:29 |
| 414 | CAPTCHA (557KB) | 2026-05-18T10:58:42Z | 19:58 |
| 412 | CAPTCHA (563KB) | 2026-05-18T10:50:37Z | 19:50 |
| 413 | CAPTCHA (563KB) | 2026-05-15T16:39:44Z | 01:39 (次日) |
| 408 | CAPTCHA (550KB) | 2026-05-15T10:41:56Z | 19:41 |
| 409 | 차단 (5KB) | 없음 | — |

**핵심 발견**: CAPTCHA 페이지(500KB+)에서도 JSON-LD datePublished가 추출 가능. 차단(5KB) 페이지에서는 추출 불가.

# Systemic Parser Block (2026-05-23)

## 증상
`sa_publish.py parse <id>` 가 **모든 3개 fallback 방법에서 동시에 실패**:
```
PARSE_FAIL: All 3 methods failed (strong block or transient failure)
```
- Playwright stealth + persistent profile → 차단
- Jina Reader (`r.jina.ai/{url}`) → 차단
- curl_cffi impersonate rotation (chrome124/safari17_2/edge99) → 차단

## 원인
SA(PerimeterX)가 IP 세션 기반의 강화된 방어로 모든 fingerprint를 동시에 차단. 단일 URL 문제가 아닌 **전체 파서 체인 차단**.

## 대응
1. **즉시 재시도 금지** — 환경/세션 기반 차단이라 같은 URL 계속 차단됨.
2. **지수 백오프에 맡기기** — `db.mark_attempt_failed()` 호출 → retry_count 증가 → 2^retry_count 시간 후 자동 재시도.
3. **수동 우회 필요 시**:
   - Jina Reader API 키 업그레이드 (무료 tier 20 RPM → 유료 tier 더 많은 동시 요청)
   - 전용 프록시 IP 사용 (PerimeterX가 IP 기반 차단하므로)
   - `sa_article_parser.py`에 새 fallback 단계 추가 (예: Cloudscraper, undetected-chromedriver)
4. **LLM 요약 대체**: 파싱이 장기 실패 시 이메일 제목(`original_title`)과 ticker만으로 요약 생성하는 fallback 고려.

## 관측 (2026-05-23)
- 10개 기사 모두 동시 실패 (SSNLF, WMT, GS, ABNB, STX, PH, COST, AMZN, NONE, F)
- 이전 사이클(18:32-18:37)에서도 동일 패턴 — 2시간 이상 지속
- pending 25건, published 254건 (stats)

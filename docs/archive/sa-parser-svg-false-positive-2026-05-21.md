# SA 파서 SVG 아이콘 오검지 (2026-05-21)

## 현상

`parse_sa_article()`가 `success=True`를 반환하지만 `content`가 실제 기사 본문이 아니라 SVG 아이콘 경로만 포함.

### 예시

```
<path d="M3.763 8.396c0 2.468 1.209 4.508 2.82 4.458 2.257-.065 2.918-2.007...
<path fill="#1a98ff" d="M22.562 16.845s-.159 4.545-2.544 2.987c0 0-2.545-1.591...
```

HTML 길이 ~3000자, 실제 기사 본문 없음.

## 원인

SA 페이지의 SVG 아이콘/로고 경로가 `_extract_content`의 폴백 경로에서 먼저 매칭되어 반환됨. `<article>` 태그가 없거나 `<p>` 추출 전에 SVG `<path>`가 먼저 발견된 경우.

## 식별 방법

```python
if '<path' in content and len(content) < 5000:
    # SVG 아이콘 오검지 — 실제 콘텐츠 아님
    print("SVG false positive detected")
```

## 대응

1. `parse_sa_article` 결과에서 `<path` 확인
2. SVG 아이콘만 포함되어 있으면 파싱 실패로 간주
3. Fallback 체인 자동 재시도 (playwright_stealth → jina_reader → curl_cffi_rotated)
4. DB 저장/읽음 처리 금지

## 관련
- `scripts/sa_article_parser.py` — `parse_sa_article()` 내 `_extract_content()`에서 SVG 오검지 감지
- PerimeterX 403 차단과 구별 필요 (SVG 오검지는 200 응답에서도 발생)

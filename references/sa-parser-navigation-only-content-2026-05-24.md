# 파서 네비게이션 전용 콘텐츠 오검지 (2026-05-24)

## 현상

`parse_sa_article()`가 `success=True`를 반환하지만 `content`가 실제 기사 본문이 아니라 **사이트 네비게이션 링크**만 포함.

## 원인

Jina Reader가 SA 페이지를 markdown으로 변환할 때, 페이지의 전역 네비게이션 구조(메뉴, 섹션, 하위 링크)가 본문보다 길게 마크업됨. `_extract_content()`는 `<h1>` 제목 + JSON-LD description + `<article><p>` 추출. `<article>` 태그가 없거나 `<p>`가 0개이면 제목 + 빈 본문만 반환.

## 감지 패턴

파싱 성공 후 `content` 검증:
- `<p>` 태그 0개
- `<h2>`, `<h3>`, `<li>` 태그 0개
- 전체 콘텐츠가 `[Link Name](url)` 형태의 마크다운 링크로 구성

## 대응

```
db.mark_attempt_failed(article_id, reason='parse returned navigation-only content, no article body')
```

다음 사이클에서 지수 백오프에 따라 재시도.

## 관련 사례

- 2026-05-24: article_id=471 (BA: Boeing found not guilty of $153M 737 MAX fraud case)
  - content 길이: ~10000자 (터미널 출력 제한)
  - 라인 수: 134
  - `<p>`/`<h2>`/`<h3>`/`<li>`: 모두 0개
  - 전체 134라인 중 130라인이 네비게이션 링크

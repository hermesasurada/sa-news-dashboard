"""SA 기사 주소 다듬기 — 수집(extract_sa_urls)과 원문 받기(sa_article_parser)가 함께 쓴다. 표준 라이브러리만."""


def strip_utm(url: str) -> str:
    """article_url에서 utm_content, position 파라미터 제거."""
    from urllib.parse import unquote
    decoded = unquote(url)
    if '?' not in decoded:
        return decoded
    base, query = decoded.split('?', 1)
    params = [p for p in query.split('&') if p and not p.startswith('utm_content') and not p.startswith('position')]
    return base + '?' + '&'.join(params) if params else base

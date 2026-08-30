# MkDocs Material HTML → Markdown 변환 (2026-05-21)

## 개요

MkDocs Material 기반 사이트의 HTML을 Markdown으로 변환할 때 BeautifulSoup 사용.

## 핵심 패턴

```python
from bs4 import BeautifulSoup

with open('page.html', 'r', encoding='utf-8') as f:
    html = f.read()

soup = BeautifulSoup(html, 'html.parser')
content = soup.find('div', class_='md-content__inner')
```

## 주의사항

- `r.encoding = 'utf-8'` — requests로 HTML 가져올 때 필수 (인코딩 안 설정하면 한글 mojibake)
- MkDocs 표 기반 코드블랙: 라인 넘버가 `<table>`로 표현된 경우 BeautifulSoup이 텍스트로 추출하면 줄 번호가 코드에 섞임. 이 경우 HTML 원본 유지 권장
- 상대 URL(`../asset/...`)은 절대 URL로 변환 필요: `https://siteadmin.ez-iok.com` + 경로
- 코드블랙 내 줄 번호 표기(Lines 1, 2, 3...)는 실제 코드가 아님 — `<td>` 셀로 표현됨

## 코드블랙 처리

```python
elif element.name == 'pre':
    code_tag = element.find('code')
    code_text = code_tag.get_text() if code_tag else element.get_text()
    return f'\n\n```\n{code_text}\n```\n\n'
```

## 테이블 처리

```python
def convert_table(table):
    rows, headers = [], []
    thead = table.find('thead')
    if thead:
        for th in thead.find('tr').find_all(['th', 'td']):
            headers.append(th.get_text().strip())
    for tr in table.find_all('tr'):
        cells = [td.get_text().strip() for td in tr.find_all(['td', 'th'])]
        if cells: rows.append(cells)
    if not headers and rows:
        headers, rows = rows[0], rows[1:]
```

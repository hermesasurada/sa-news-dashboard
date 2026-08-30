# SA Dashboard summary_details JSON Corruption (2026-05-21)

## 증상
`/api/articles` 엔드포인트가 500 Internal Server Error 반환.
브라우저에서 대시보드 로드 후 검색 클릭 시 기사 목록이 표시되지 않음.

## 원인
`summary_details` 컬럼에 `json.loads()`로 파싱 불가한 형식의 데이터가 저장됨.
주요 패턴:

### 패턴 1: Python list repr (Korean quotes)
```
"['오픈에이아이, 이르면 금요일 IPO 신청 가능성', '월스트리트저널, 정통 소식통 인용 보도']"
```
Korean left/right single quotes (`\u2018`, `\u2019`) 사용. `json.loads()` 실패.

### 패턴 2: Escaped ASCII single quotes
```
"[\\'SA 분석가들 인텔에 대해 비관론으로 전환\\', \\'조니 장 분석가...\\']"
```
Python repr에서 `\'`로 이스케이프된 단일 따옴표.

### 패턴 3: 일반 Python single-quote list
```
"['모건스탠리, 중국 내 모바일 기기 사용 정책 도입', '홍콩 근무...']"
```
ASCII `'` 사용. `json.loads()`는 double-quote만 허용하므로 실패.

## 데이터 복원
```python
import sqlite3, json, ast

conn = sqlite3.connect('/Users/yhandhs/projects/sa-news/sa_news.db')
conn.row_factory = sqlite3.Row

broken_ids = [bid for r in conn.execute('SELECT id, summary_details FROM articles').fetchall()
              if not _is_valid_json(r['summary_details'])]

for r in broken_ids:
    val = r['summary_details']
    try:
        parsed = ast.literal_eval(val)  # Python list repr 파싱
        if isinstance(parsed, list):
            cleaned = json.dumps(parsed, ensure_ascii=False)
            conn.execute('UPDATE articles SET summary_details = ? WHERE id = ?', (cleaned, r['id']))
    except (ValueError, SyntaxError):
        pass

conn.commit()
conn.close()
```

## 코드 수정 (db.py, app.py)
`json.loads()` 실패 시 `ast.literal_eval()`으로 폴백:

```python
def row_to_dict(r):
    d = dict(r)
    sd = d["summary_details"]
    try:
        d["summary_details"] = json.loads(sd)
    except (json.JSONDecodeError, TypeError):
        import ast
        try:
            parsed = ast.literal_eval(sd)
            if isinstance(parsed, list):
                d["summary_details"] = parsed
            else:
                d["summary_details"] = []
        except (ValueError, SyntaxError):
            d["summary_details"] = []
    return d
```

## 발생 경로
`db.insert_article()`에서 `json.dumps(summary_details, ensure_ascii=False)` 호출 시,
Python list의 string 요소에 Korean quotes가 포함된 경우 `json.dumps`가 Korean quotes를
인식하지 못하고 원본 문자열 그대로 저장 — 결과적으로 `json.loads()`로 복원 불가.

## 예방
`insert_article()` 호출 전 `summary_details` 요소가 ASCII double-quote로
인코딩된 JSON 배열인지 검증. Korean quotes가 포함된 문자열은 `replace('\u2018', '"')` 등으로
정제 후 `json.dumps()` 호출.
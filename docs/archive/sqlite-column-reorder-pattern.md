# SQLite 컬럼 순서 재배열 기법

SQLite는 `ALTER COLUMN` 순서 변경을 지원하지 않음. 컬럼 순서를 바꾸려면 테이블 재구성이 필요.

## 패턴

```sql
-- 1. 새 테이블을 원하는 순서로 CREATE
CREATE TABLE articles_new (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id         TEXT UNIQUE,
    ticker           TEXT NOT NULL,
    ticker_color     TEXT NOT NULL DEFAULT 'blue',
    original_title   TEXT,
    company_name     TEXT NOT NULL,
    headline         TEXT NOT NULL,
    summary_core     TEXT NOT NULL,
    summary_details  TEXT NOT NULL,
    tag              TEXT NOT NULL,
    tag_color        TEXT NOT NULL DEFAULT 'blue',
    article_url      TEXT NOT NULL,
    email_time_et    TEXT,
    last_modified    TEXT,
    del_yn           TEXT NOT NULL DEFAULT 'N'
);

-- 2. 기존 데이터 복사 (컬럼 순서 명시적 매핑)
INSERT INTO articles_new (id, email_id, ticker, ticker_color, original_title,
    company_name, headline, summary_core, summary_details, tag, tag_color,
    article_url, email_time_et, last_modified, del_yn)
SELECT id, email_id, ticker, ticker_color, original_title,
    company_name, headline, summary_core, summary_details, tag, tag_color,
    article_url, email_time_et, last_modified, del_yn
FROM articles;

-- 3. 기존 테이블 삭제
DROP TABLE articles;

-- 4. 새 테이블 이름 변경
ALTER TABLE articles_new RENAME TO articles;
```

## 주의사항

- **인덱스/트리거**: 재구성이 끝나면 인덱스와 FTS5 트리거를 다시 생성해야 함
- **대용량 테이블**: 전체 복사이므로 시간/디스크 공간 고려
- **중복 데이터**: INSERT 전에 기존 테이블 백업 권장

## 적용 사례 (2026-05-23)

`sa_news.db`에서 `email_id`를 `id` 직후로, `original_title`을 `headline` 전으로 이동.
기존: `id, ticker, ticker_color, company_name, original_title, headline, ...`
신규: `id, email_id, ticker, ticker_color, original_title, company_name, headline, ...`

동시에 `db.py`의 `CREATE_SQL`과 `INSERT` 문 컬럼 순서도 일치시켜야 함.
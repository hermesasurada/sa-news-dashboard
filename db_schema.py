"""SA 뉴스 DB 구조 — 테이블·검색 색인 정의와 나중에 더한 열을 한 곳에서 만든다.

`apply(conn)`가 유일한 진입점이고 `db.init_db()`가 부른다. 몇 번을 돌려도 같은 결과다.
열을 더할 때는 `add_missing_columns`에 한 줄을 넣는다 — 다른 모듈에서 ALTER TABLE을 하지 않는다
(Grok 연동 열도 여기서 만든다, 2026-11-16).
"""

from __future__ import annotations

import sqlite3

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id        TEXT UNIQUE,
    ticker          TEXT NOT NULL,
    original_title  TEXT,
    company_name    TEXT,
    headline        TEXT,
    summary_details TEXT,
    ticker_color    TEXT NOT NULL DEFAULT 'blue',
    article_url     TEXT NOT NULL,
    email_time_et   TEXT,
    last_modified   TEXT,
    is_read         INTEGER NOT NULL DEFAULT 0,
    pub_status      TEXT NOT NULL DEFAULT 'pending',
    retry_count     INTEGER NOT NULL DEFAULT 0,
    last_attempt    TEXT,
    fail_reason     TEXT,
    parse_method    TEXT,
    summary_model   TEXT,
    source_text     TEXT,
    source_method   TEXT,
    source_chars    INTEGER,
    source_locked   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_email_time  ON articles(email_time_et DESC);
CREATE INDEX IF NOT EXISTS idx_last_mod    ON articles(last_modified DESC);
CREATE INDEX IF NOT EXISTS idx_ticker      ON articles(ticker);
CREATE INDEX IF NOT EXISTS idx_company     ON articles(company_name);
CREATE INDEX IF NOT EXISTS idx_pub_status  ON articles(pub_status);

-- 목록 조회의 WHERE + ORDER BY를 한 인덱스에서 처리한다. email_id는 문자열
-- 컬럼이므로 실제 정렬식과 동일한 expression index를 사용한다.
CREATE INDEX IF NOT EXISTS idx_status_email_time ON articles(
    pub_status, email_time_et DESC, CAST(email_id AS INTEGER) DESC
);
CREATE INDEX IF NOT EXISTS idx_status_last_mod ON articles(
    pub_status, last_modified DESC, CAST(email_id AS INTEGER) DESC
);

CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    ticker,
    company_name,
    headline,
    summary_details,
    original_title,
    content='articles',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
    INSERT INTO articles_fts(rowid, ticker, company_name, headline, summary_details, original_title)
    VALUES (new.id, new.ticker, COALESCE(new.company_name,''), COALESCE(new.headline,''),
            COALESCE(new.summary_details,''), COALESCE(new.original_title,''));
END;

CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, ticker, company_name, headline, summary_details, original_title)
    VALUES ('delete', old.id, old.ticker, COALESCE(old.company_name,''), COALESCE(old.headline,''),
            COALESCE(old.summary_details,''), COALESCE(old.original_title,''));
END;

CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE OF
    ticker, company_name, headline, summary_details, original_title
ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, ticker, company_name, headline, summary_details, original_title)
    VALUES ('delete', old.id, old.ticker, COALESCE(old.company_name,''), COALESCE(old.headline,''),
            COALESCE(old.summary_details,''), COALESCE(old.original_title,''));
    INSERT INTO articles_fts(rowid, ticker, company_name, headline, summary_details, original_title)
    VALUES (new.id, new.ticker, COALESCE(new.company_name,''), COALESCE(new.headline,''),
            COALESCE(new.summary_details,''), COALESCE(new.original_title,''));
END;
"""


_FTS_REBUILD_SQL = """
DROP TRIGGER IF EXISTS articles_ai;
DROP TRIGGER IF EXISTS articles_ad;
DROP TRIGGER IF EXISTS articles_au;
DROP TABLE  IF EXISTS articles_fts;

CREATE VIRTUAL TABLE articles_fts USING fts5(
    ticker, company_name, headline, summary_details, original_title,
    content='articles', content_rowid='id'
);

CREATE TRIGGER articles_ai AFTER INSERT ON articles BEGIN
    INSERT INTO articles_fts(rowid, ticker, company_name, headline, summary_details, original_title)
    VALUES (new.id, new.ticker, COALESCE(new.company_name,''), COALESCE(new.headline,''),
            COALESCE(new.summary_details,''), COALESCE(new.original_title,''));
END;

CREATE TRIGGER articles_ad AFTER DELETE ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, ticker, company_name, headline, summary_details, original_title)
    VALUES ('delete', old.id, old.ticker, COALESCE(old.company_name,''), COALESCE(old.headline,''),
            COALESCE(old.summary_details,''), COALESCE(old.original_title,''));
END;

CREATE TRIGGER articles_au AFTER UPDATE OF
    ticker, company_name, headline, summary_details, original_title
ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, ticker, company_name, headline, summary_details, original_title)
    VALUES ('delete', old.id, old.ticker, COALESCE(old.company_name,''), COALESCE(old.headline,''),
            COALESCE(old.summary_details,''), COALESCE(old.original_title,''));
    INSERT INTO articles_fts(rowid, ticker, company_name, headline, summary_details, original_title)
    VALUES (new.id, new.ticker, COALESCE(new.company_name,''), COALESCE(new.headline,''),
            COALESCE(new.summary_details,''), COALESCE(new.original_title,''));
END;

INSERT INTO articles_fts(rowid, ticker, company_name, headline, summary_details, original_title)
SELECT id, ticker,
       COALESCE(company_name,''), COALESCE(headline,''),
       COALESCE(summary_details,''), COALESCE(original_title,'')
FROM articles WHERE pub_status != 'purged';
"""

_FTS_UPDATE_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS articles_au;
CREATE TRIGGER articles_au AFTER UPDATE OF
    ticker, company_name, headline, summary_details, original_title
ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, ticker, company_name, headline, summary_details, original_title)
    VALUES ('delete', old.id, old.ticker, COALESCE(old.company_name,''), COALESCE(old.headline,''),
            COALESCE(old.summary_details,''), COALESCE(old.original_title,''));
    INSERT INTO articles_fts(rowid, ticker, company_name, headline, summary_details, original_title)
    VALUES (new.id, new.ticker, COALESCE(new.company_name,''), COALESCE(new.headline,''),
            COALESCE(new.summary_details,''), COALESCE(new.original_title,''));
END;
"""

_LEGACY_ARTICLE_COLS = ("summary_core", "tag", "tag_color", "email_body")


def _drop_legacy_article_columns(conn: sqlite3.Connection) -> None:
    cols = _table_columns(conn, "articles")
    fts_cols = _table_columns(conn, "articles_fts") if "articles_fts" in {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    } else set()
    need_drop = any(name in cols for name in _LEGACY_ARTICLE_COLS)
    need_fts = "summary_core" in fts_cols or need_drop
    if not need_drop and not need_fts:
        return
    conn.executescript(
        """
        DROP TRIGGER IF EXISTS articles_ai;
        DROP TRIGGER IF EXISTS articles_ad;
        DROP TRIGGER IF EXISTS articles_au;
        DROP TABLE IF EXISTS articles_fts;
        """
    )
    for name in _LEGACY_ARTICLE_COLS:
        if name in _table_columns(conn, "articles"):
            conn.execute(f"ALTER TABLE articles DROP COLUMN {name}")
    conn.executescript(_FTS_REBUILD_SQL)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def add_missing_columns(conn: sqlite3.Connection) -> None:
    """CREATE_SQL 이후에 더한 열을 없을 때만 만든다(옛 DB 호환). 새 열은 여기에 더한다."""
    cols = _table_columns(conn, "articles")
    if "is_read" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            "UPDATE articles SET is_read = 1 WHERE CAST(email_id AS INTEGER) <= 723"
        )
    if "parse_method" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN parse_method TEXT")
    if "summary_model" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN summary_model TEXT")
    if "source_text" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN source_text TEXT")
    if "source_method" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN source_method TEXT")
    if "source_chars" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN source_chars INTEGER")
    if "source_locked" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN source_locked INTEGER NOT NULL DEFAULT 0")
    # Grok 연동 열(2026-10-11~). 예전엔 grok_bridge가 동기화 때 따로 더했다.
    for col, ddl in (("grok_requested_at", "TEXT"), ("grok_status", "TEXT"),
                     ("grok_attempt", "INTEGER"), ("grok_result_mtime", "TEXT"),
                     # 결과 JSON 원본(작성자·게시 시각·메모 포함) — Grok이 완료 5일 뒤 드라이브에서 지운다(2026-10-12)
                     ("grok_result_json", "TEXT")):
        if col not in cols:
            conn.execute(f"ALTER TABLE articles ADD COLUMN {col} {ddl}")


def apply(conn: sqlite3.Connection) -> None:
    """테이블·색인·트리거를 현재 구조로 맞춘다. 연결은 호출자(db.init_db)가 연다."""
    # journal mode 변경은 연결마다 파일 잠금을 수반할 수 있으므로 초기화 때만 수행한다.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(CREATE_SQL)
    # 기존 DB의 범용 UPDATE 트리거도 교체한다. 읽음·재시도 상태 변경은
    # 검색 문서를 바꾸지 않으므로 FTS 삭제/재삽입 대상이 아니다.
    conn.executescript(_FTS_UPDATE_TRIGGER_SQL)
    add_missing_columns(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processing_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER,
            stage TEXT,
            method TEXT,
            chars INTEGER,
            locked INTEGER,
            elapsed_ms INTEGER,
            error TEXT,
            accepted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_attempts_article "
        "ON processing_attempts(article_id, id)"
    )
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_status_unread_email_time ON articles(
            pub_status, is_read, email_time_et DESC, CAST(email_id AS INTEGER) DESC
        );
        CREATE INDEX IF NOT EXISTS idx_status_unread_last_mod ON articles(
            pub_status, is_read, last_modified DESC, CAST(email_id AS INTEGER) DESC
        );
        """
    )
    _drop_legacy_article_columns(conn)
    if "original_title" not in _table_columns(conn, "articles_fts"):
        conn.executescript(_FTS_REBUILD_SQL)

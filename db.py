"""
SA News Dashboard — SQLite DB layer
"""
import sqlite3
import json
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "sa_news.db"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id        TEXT UNIQUE,
    ticker          TEXT NOT NULL,
    original_title  TEXT,
    company_name    TEXT,            -- collect 단계 NULL, publish에서 채움
    headline        TEXT,            -- ↑
    summary_core    TEXT,            -- ↑
    summary_details TEXT,            -- ↑ JSON array of strings
    tag             TEXT,            -- ↑
    ticker_color    TEXT NOT NULL DEFAULT 'blue',
    tag_color       TEXT NOT NULL DEFAULT 'blue',
    article_url     TEXT NOT NULL,
    email_time_et   TEXT,
    last_modified   TEXT,
    pub_status      TEXT NOT NULL DEFAULT 'pending',  -- 'pending'|'published'|'failed'|'deleted'
    retry_count     INTEGER NOT NULL DEFAULT 0,
    last_attempt    TEXT,
    fail_reason     TEXT
);

CREATE INDEX IF NOT EXISTS idx_email_time  ON articles(email_time_et DESC);
CREATE INDEX IF NOT EXISTS idx_last_mod    ON articles(last_modified DESC);
CREATE INDEX IF NOT EXISTS idx_ticker      ON articles(ticker);
CREATE INDEX IF NOT EXISTS idx_company     ON articles(company_name);
CREATE INDEX IF NOT EXISTS idx_pub_status  ON articles(pub_status);

CREATE TABLE IF NOT EXISTS telegram_feeds (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_date      TEXT NOT NULL,           -- '2026-05-19'
    title          TEXT NOT NULL,
    summary        TEXT,
    tags           TEXT,                    -- JSON array
    original_path  TEXT,                    -- md 파일 전체 경로
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_telegram_feed_date ON telegram_feeds(feed_date DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    ticker,
    company_name,
    headline,
    summary_core,
    summary_details,
    original_title,
    content='articles',
    content_rowid='id'
);

-- FTS 트리거: pending 상태에서는 한국어 컬럼이 NULL일 수 있어 COALESCE로 보호
CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
    INSERT INTO articles_fts(rowid, ticker, company_name, headline, summary_core, summary_details, original_title)
    VALUES (new.id, new.ticker, COALESCE(new.company_name,''), COALESCE(new.headline,''),
            COALESCE(new.summary_core,''), COALESCE(new.summary_details,''), COALESCE(new.original_title,''));
END;

CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, ticker, company_name, headline, summary_core, summary_details, original_title)
    VALUES ('delete', old.id, old.ticker, COALESCE(old.company_name,''), COALESCE(old.headline,''),
            COALESCE(old.summary_core,''), COALESCE(old.summary_details,''), COALESCE(old.original_title,''));
END;

CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, ticker, company_name, headline, summary_core, summary_details, original_title)
    VALUES ('delete', old.id, old.ticker, COALESCE(old.company_name,''), COALESCE(old.headline,''),
            COALESCE(old.summary_core,''), COALESCE(old.summary_details,''), COALESCE(old.original_title,''));
    INSERT INTO articles_fts(rowid, ticker, company_name, headline, summary_core, summary_details, original_title)
    VALUES (new.id, new.ticker, COALESCE(new.company_name,''), COALESCE(new.headline,''),
            COALESCE(new.summary_core,''), COALESCE(new.summary_details,''), COALESCE(new.original_title,''));
END;
"""


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def get_conn():
    conn = sqlite3.connect(DB_PATH, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


_FTS_REBUILD_SQL = """
DROP TRIGGER IF EXISTS articles_ai;
DROP TRIGGER IF EXISTS articles_ad;
DROP TRIGGER IF EXISTS articles_au;
DROP TABLE  IF EXISTS articles_fts;

CREATE VIRTUAL TABLE articles_fts USING fts5(
    ticker, company_name, headline, summary_core, summary_details, original_title,
    content='articles', content_rowid='id'
);

CREATE TRIGGER articles_ai AFTER INSERT ON articles BEGIN
    INSERT INTO articles_fts(rowid, ticker, company_name, headline, summary_core, summary_details, original_title)
    VALUES (new.id, new.ticker, COALESCE(new.company_name,''), COALESCE(new.headline,''),
            COALESCE(new.summary_core,''), COALESCE(new.summary_details,''), COALESCE(new.original_title,''));
END;

CREATE TRIGGER articles_ad AFTER DELETE ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, ticker, company_name, headline, summary_core, summary_details, original_title)
    VALUES ('delete', old.id, old.ticker, COALESCE(old.company_name,''), COALESCE(old.headline,''),
            COALESCE(old.summary_core,''), COALESCE(old.summary_details,''), COALESCE(old.original_title,''));
END;

CREATE TRIGGER articles_au AFTER UPDATE ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, ticker, company_name, headline, summary_core, summary_details, original_title)
    VALUES ('delete', old.id, old.ticker, COALESCE(old.company_name,''), COALESCE(old.headline,''),
            COALESCE(old.summary_core,''), COALESCE(old.summary_details,''), COALESCE(old.original_title,''));
    INSERT INTO articles_fts(rowid, ticker, company_name, headline, summary_core, summary_details, original_title)
    VALUES (new.id, new.ticker, COALESCE(new.company_name,''), COALESCE(new.headline,''),
            COALESCE(new.summary_core,''), COALESCE(new.summary_details,''), COALESCE(new.original_title,''));
END;

INSERT INTO articles_fts(rowid, ticker, company_name, headline, summary_core, summary_details, original_title)
SELECT id, ticker,
       COALESCE(company_name,''), COALESCE(headline,''),
       COALESCE(summary_core,''), COALESCE(summary_details,''), COALESCE(original_title,'')
FROM articles WHERE pub_status != 'deleted';
"""


def init_db():
    with get_conn() as conn:
        conn.executescript(CREATE_SQL)
        # 마이그레이션: is_read 컬럼 (최초 1회)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(articles)").fetchall()]
        if "is_read" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                "UPDATE articles SET is_read = 1 WHERE CAST(email_id AS INTEGER) <= 723"
            )
        # 마이그레이션: FTS에 original_title 컬럼 추가 (최초 1회)
        fts_cols = [r[1] for r in conn.execute("PRAGMA table_info(articles_fts)").fetchall()]
        if "original_title" not in fts_cols:
            conn.executescript(_FTS_REBUILD_SQL)
    print(f"DB initialized: {DB_PATH}")


def insert_article(
    email_id: str = None,
    ticker: str = "",
    original_title: str = "",
    company_name: str = "",
    headline: str = "",
    summary_core: str = "",
    summary_details=None,
    tag: str = "",
    ticker_color: str = "blue",
    tag_color: str = "blue",
    article_url: str = "",
    email_time_et: str = "",
    last_modified: str = None,
):
    """기사 1건 삽입. email_id 중복이면 None 반환. pub_status는 'published' 고정 (legacy 단일-stage 호환용)."""
    import datetime
    if last_modified is None:
        last_modified = datetime.datetime.now().strftime("%Y-%m-%d %H:%M KST")
    with get_conn() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO articles
                  (email_id, ticker, original_title, company_name,
                   headline, summary_core, summary_details,
                   tag, ticker_color, tag_color, article_url,
                   email_time_et, last_modified, pub_status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    email_id,
                    ticker, original_title, company_name,
                    headline, summary_core,
                    json.dumps(summary_details, ensure_ascii=False),
                    tag, ticker_color, tag_color, article_url,
                    email_time_et, last_modified, 'published',
                ),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None  # 중복


def query_articles(
    q: str = "",
    ticker: str = "",
    date_from: str = "",
    date_to: str = "",
    sort_by: str = "email_time_et",  # email_time_et | last_modified
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """기사 목록 조회. pub_status='published'만 자동 노출 (pending/failed/deleted 제외).
    정렬 기본: email_time_et DESC → email_id DESC.
    날짜 필터는 email_time_et 기준 (YYYY-MM-DD)."""
    params = []
    joins = ""
    wheres = ["articles.pub_status = 'published'"]

    if q:
        joins = "JOIN articles_fts ON articles.id = articles_fts.rowid"
        wheres.append("articles_fts MATCH ?")
        params.append(q + "*")

    if ticker:
        # 다중 ticker 행("FCX, MP" 등) 대응 — 공백 제거 후 ',T,' 패턴으로 토큰 매칭
        # ticker = 'FCX' → 행 ticker가 'FCX'·'FCX, MP'·'MP, FCX' 모두 매치, 'MFCX'는 매치 안 됨
        t = ticker.upper().strip().replace(' ', '')
        wheres.append(
            "(',' || REPLACE(articles.ticker, ' ', '') || ',') LIKE ?"
        )
        params.append(f'%,{t},%')

    if date_from:
        wheres.append("articles.email_time_et >= ?")
        params.append(date_from)

    if date_to:
        wheres.append("articles.email_time_et <= ?")
        params.append(date_to + " 23:59 KST")

    if unread_only:
        wheres.append("articles.is_read = 0")

    where_sql = "WHERE " + " AND ".join(wheres)

    # 정렬 조건
    if sort_by == "last_modified":
        order = "articles.last_modified DESC, CAST(articles.email_id AS INTEGER) DESC"
    else:
        order = "articles.email_time_et DESC, CAST(articles.email_id AS INTEGER) DESC"

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM articles {joins} {where_sql}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""
            SELECT articles.* FROM articles {joins}
            {where_sql}
            ORDER BY {order}
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    def row_to_dict(r):
        d = dict(r)
        sd = d["summary_details"]
        try:
            d["summary_details"] = json.loads(sd)
        except (json.JSONDecodeError, TypeError):
            # Korean quotes / Python repr 형태로 저장된 경우 ast.literal_eval로 복원
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

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [row_to_dict(r) for r in rows],
    }


def get_filter_options() -> dict:
    """검색 UI용 티커 목록. 다중 ticker 행('FCX, MP')은 분리 + 중복 제거.
    placeholder('NONE')와 빈값은 제외. pub_status='published'만 집계."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT ticker FROM articles
               WHERE pub_status = 'published'
                 AND ticker IS NOT NULL AND ticker != ''"""
        ).fetchall()
    tickers: set[str] = set()
    for (raw,) in rows:
        for t in raw.split(','):
            t = t.strip()
            if not t or t.upper() == 'NONE':
                continue
            tickers.add(t)
    return {"tickers": sorted(tickers)}


if __name__ == "__main__":
    init_db()


def mark_article_read(article_id: int, is_read: bool = True) -> bool:
    """읽음/안읽음 토글. 소프트삭제된 레코드는 제외."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE articles SET is_read = ? WHERE id = ? AND pub_status != 'deleted'",
            (1 if is_read else 0, article_id),
        )
        return cur.rowcount > 0


def delete_article(article_id: int) -> bool:
    """기사 소프트 삭제 (pub_status='deleted'). 이미 삭제된 레코드면 False."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE articles SET pub_status = 'deleted' WHERE id = ? AND pub_status != 'deleted'",
            (article_id,),
        )
        return cur.rowcount > 0


# ==================== Collect / Publish (2-stage workflow) ====================

import datetime as _dt


def _now_kst() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M KST")


def insert_pending_article(
    *,
    email_id: str,
    ticker: str,
    article_url: str,
    original_title: str = "",
    email_time_et: str = "",
) -> Optional[int]:
    """작업 1 (collect) — envelope 정보만으로 pending 행 INSERT.
    필수: email_id, ticker, article_url.
    pub_status='pending', last_modified=now 자동 설정.
    한국어 컬럼(company_name 등)은 NULL로 비워두고 작업 2에서 채움.
    email_id 중복 시 None 반환 (이미 수집된 메일)."""
    last_modified = _now_kst()
    with get_conn() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO articles
                  (email_id, ticker, original_title, article_url,
                   email_time_et, last_modified, pub_status, retry_count)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', 0)
                """,
                (str(email_id), ticker, original_title, article_url,
                 email_time_et, last_modified),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def get_pending_due(batch_size: int = 10, max_retry: int = 5) -> list[dict]:
    """작업 2 대상 조회 — pub_status='pending' AND 지수 백오프 due.
    next_due = last_attempt + 2^retry_count * 20 분.
      retry=0 →  20 min,  retry=1 →  40 min,  retry=2 →  80 min,
      retry=3 → 160 min,  retry=4 → 320 min.
    retry_count < max_retry 행만 (도달 시 pub_status='failed' 전환은 mark_attempt_failed 책임).
    정렬: retry_count ASC (새 행 우선) → email_time_et ASC (오래된 것 먼저)."""
    sql = """
        SELECT id, email_id, ticker, original_title, article_url,
               email_time_et, retry_count, last_attempt
        FROM articles
        WHERE pub_status = 'pending'
          AND retry_count < ?
          AND (
              last_attempt IS NULL
              OR datetime(REPLACE(last_attempt, ' KST', ''), '-9 hours',
                          '+' || ((1 << retry_count) * 20) || ' minutes')
                 <= datetime('now')
          )
        ORDER BY retry_count ASC,
                 datetime(REPLACE(COALESCE(email_time_et, ''), ' KST', '')) ASC
        LIMIT ?
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (max_retry, batch_size)).fetchall()
    return [dict(r) for r in rows]


def publish_article(
    article_id: int,
    *,
    ticker: Optional[str] = None,
    company_name: str,
    headline: str,
    summary_core: str,
    summary_details,
    tag: str,
    ticker_color: str = "blue",
    tag_color: str = "blue",
) -> bool:
    """작업 2 성공 — 한국어 요약 등 UPDATE + pub_status='published'.
    ticker가 None이 아닌 경우 ticker 컬럼도 함께 업데이트.
    last_modified=now, fail_reason=NULL.
    이미 published 아닌 row만 영향 (실패 → 발행 전환 포함)."""
    last_modified = _now_kst()
    with get_conn() as conn:
        if ticker is not None:
            cur = conn.execute(
                """
                UPDATE articles SET
                  ticker = ?, company_name = ?, headline = ?, summary_core = ?,
                  summary_details = ?, tag = ?,
                  ticker_color = ?, tag_color = ?,
                  pub_status = 'published', last_modified = ?,
                  fail_reason = NULL
                WHERE id = ? AND pub_status != 'deleted'
                """,
                (
                    ticker, company_name, headline, summary_core,
                    json.dumps(summary_details, ensure_ascii=False),
                    tag, ticker_color, tag_color, last_modified, article_id,
                ),
            )
        else:
            cur = conn.execute(
                """
                UPDATE articles SET
                  company_name = ?, headline = ?, summary_core = ?,
                  summary_details = ?, tag = ?,
                  ticker_color = ?, tag_color = ?,
                  pub_status = 'published', last_modified = ?,
                  fail_reason = NULL
                WHERE id = ? AND pub_status != 'deleted'
                """,
                (
                    company_name, headline, summary_core,
                    json.dumps(summary_details, ensure_ascii=False),
                    tag, ticker_color, tag_color, last_modified, article_id,
                ),
            )
        return cur.rowcount > 0


def mark_attempt_failed(article_id: int, reason: str, max_retry: int = 5) -> dict:
    """작업 2 실패 — retry_count++, last_attempt=now, fail_reason 기록.
    retry_count > max_retry 이면 pub_status='failed' 전환 (영구 실패).
    반환: {'retry_count': int, 'pub_status': str}"""
    now = _now_kst()
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT retry_count FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
        if not cur:
            return {"retry_count": -1, "pub_status": "not_found"}
        new_count = (cur[0] or 0) + 1
        new_status = "failed" if new_count >= max_retry else "pending"
        conn.execute(
            """UPDATE articles SET
                 retry_count = ?, last_attempt = ?, fail_reason = ?,
                 pub_status = ?, last_modified = ?
               WHERE id = ?""",
            (new_count, now, reason[:200], new_status, now, article_id),
        )
        return {"retry_count": new_count, "pub_status": new_status}


def get_queue_stats() -> dict:
    """발행 큐 통계 (어드민용). pub_status별 카운트 (deleted 포함 모든 상태)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT pub_status, COUNT(*) FROM articles GROUP BY pub_status"
        ).fetchall()
    return {r[0]: r[1] for r in rows}


# ==================== Telegram Feed ====================

def query_telegram_feeds(
    q: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Telegram FEED 목록 조회"""
    import re
    params = []
    wheres = []

    if q:
        wheres.append("(title LIKE ? OR summary LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    if date_from:
        wheres.append("feed_date >= ?")
        params.append(date_from)

    if date_to:
        wheres.append("feed_date <= ?")
        params.append(date_to)

    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM telegram_feeds {where_sql}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""
            SELECT * FROM telegram_feeds
            {where_sql}
            ORDER BY feed_date DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [dict(r) for r in rows],
    }


def get_telegram_feed_original(feed_id: int) -> dict:
    """원본 Markdown + 이미지 경로 반환"""
    import re
    from pathlib import Path

    with get_conn() as conn:
        row = conn.execute(
            "SELECT original_path FROM telegram_feeds WHERE id = ?", (feed_id,)
        ).fetchone()

    if not row or not row[0]:
        return {"error": "Not found"}

    original_path = row[0]
    full_path = Path("/Users/yhandhs/Documents/Asurada") / original_path

    if not full_path.exists():
        # .md 확장자 자동 추가 시도
        if not str(full_path).endswith(".md"):
            full_path = Path(str(full_path) + ".md")
        if not full_path.exists():
            return {"error": "File not found", "path": str(full_path)}

    content = full_path.read_text(encoding="utf-8")

    # 이미지 추출 (Obsidian + 일반 Markdown 둘 다 지원)
    images = []
    # 1. Obsidian wiki link: ![[attach/xxx.png]] 또는 ![[attach/xxx.png|526]]
    images += re.findall(r"!\[\[attach/([^\]|]+)(?:\|[^\]]+)?\]\]", content)
    # 2. 일반 Markdown: ![alt](attach/xxx.png)
    images += re.findall(r"!\[[^\]]*\]\((?:/static/)?attach/([^)|]+)(?:\|[^)]+)?\)", content)

    # 중복 제거 + |숫자 제거
    seen = set()
    unique_images = []
    for img in images:
        # |숫자 같은 Obsidian 너비 지정 제거
        clean_img = img.split("|")[0]
        if clean_img and clean_img not in seen:
            seen.add(clean_img)
            unique_images.append(clean_img)

    return {
        "id": feed_id,
        "original_path": original_path,
        "content": content,
        "images": unique_images,
    }

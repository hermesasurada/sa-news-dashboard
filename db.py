"""
SA News Dashboard — SQLite DB layer
"""
import sqlite3
import json
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "sa_news.db"

# Telegram 피드 원본(Obsidian vault) 루트. 환경변수로 재정의 가능.
import os as _os
ASURADA_DIR = Path(_os.environ.get("ASURADA_DIR", str(Path.home() / "Documents" / "Asurada")))

# 사실상 같은 종목(주식 클래스 차이 등)을 하나의 대표 티커로 병합.
#   key(별칭, 대문자) → value(대표 티커). 필요 시 항목 추가.
TICKER_ALIASES = {
    "GOOGL": "GOOG",   # Alphabet Class A → Class C
    "FOXA": "FOX",     # Fox Class A → Class B
    "NWSA": "NWS",     # News Corp Class A → Class B
    "UAA": "UA",       # Under Armour Class A → Class C
    # 한국 거래소 코드 → OTC ADR 티커 (FOREIGN_LISTINGS가 OTC 키로 한글명 표시)
    "005930": "SSNLF", "005930.KS": "SSNLF",   # 삼성전자
    "000660": "HXSCL", "000660.KS": "HXSCL",   # SK하이닉스
    "066570": "LGEIY", "066570.KS": "LGEIY",   # LG전자
    "035420": "NHNCF", "035420.KS": "NHNCF",   # 네이버
}


def canonicalize_tickers(ticker_str: str, company_str: str = "") -> tuple:
    """다중 ticker 문자열에서 동일 종목(클래스 차이)을 대표 티커로 병합하고 중복 제거.
    'GOOGL, GOOG' → 'GOOG'. company_name도 ticker 순서에 맞춰 정렬·중복 제거.
    반환: (정규화 ticker_str, 정규화 company_str)."""
    tks = [t.strip() for t in str(ticker_str or "").split(",") if t.strip()]
    cos = [c.strip() for c in str(company_str or "").split("·")]
    out_t, out_c, seen = [], [], set()
    for i, t in enumerate(tks):
        canon = TICKER_ALIASES.get(t.upper(), t)
        if canon in seen:
            continue  # 이미 대표 티커로 들어온 중복(클래스 별칭) 제거
        seen.add(canon)
        out_t.append(canon)
        out_c.append(cos[i] if i < len(cos) else "")
    new_ticker = ", ".join(out_t)
    # company가 원래 비어있었으면 그대로 빈 값 유지
    new_company = "·".join(out_c) if any(out_c) else company_str
    return new_ticker, new_company

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
    pub_status      TEXT NOT NULL DEFAULT 'pending',  -- 'pending'|'published'|'failed'|'deleted'|'purged'(30일경과 영구삭제,행만유지)
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
        # 마이그레이션: parse_method 컬럼 (어떤 파서로 본문을 가져왔는지). 기존행은 NULL 유지.
        if "parse_method" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN parse_method TEXT")
        # 마이그레이션: FTS에 original_title 컬럼 추가 (최초 1회)
        fts_cols = [r[1] for r in conn.execute("PRAGMA table_info(articles_fts)").fetchall()]
        if "original_title" not in fts_cols:
            conn.executescript(_FTS_REBUILD_SQL)
    print(f"DB initialized: {DB_PATH}")


def query_articles(
    q: str = "",
    ticker: str = "",
    date_from: str = "",
    date_to: str = "",
    sort_by: str = "email_time_et",  # email_time_et | last_modified
    order: str = "desc",             # desc(최신순) | asc(과거순)
    unread_only: bool = False,
    deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """기사 목록 조회. 기본은 pub_status='published'만 노출.
    deleted=True 이면 휴지통(pub_status='deleted')만 노출.
    정렬 기본: email_time_et DESC → email_id DESC. order=asc면 오름차순(과거순).
    날짜 필터는 email_time_et 기준 (YYYY-MM-DD)."""
    params = []
    joins = ""
    wheres = ["articles.pub_status = 'deleted'"] if deleted \
        else ["articles.pub_status = 'published'"]

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

    # 정렬 조건 (방향: asc=과거순 / 그 외=desc 최신순)
    direction = "ASC" if str(order).lower() == "asc" else "DESC"
    field = "articles.last_modified" if sort_by == "last_modified" else "articles.email_time_et"
    order_clause = f"{field} {direction}, CAST(articles.email_id AS INTEGER) {direction}"

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM articles {joins} {where_sql}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""
            SELECT articles.* FROM articles {joins}
            {where_sql}
            ORDER BY {order_clause}
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
            tickers.add(TICKER_ALIASES.get(t.upper(), t))  # GOOGL=GOOG 병합
    # aliases도 함께 내려 프런트가 동일 병합 규칙을 공유 (단일 소스: db.TICKER_ALIASES)
    return {"tickers": sorted(tickers), "aliases": TICKER_ALIASES}


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
    """기사 소프트 삭제 (pub_status='deleted'). 이미 삭제된 레코드면 False.
    last_modified를 삭제 시각으로 갱신 → 30일 경과 영구삭제(purge) 기준이 됨."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE articles SET pub_status = 'deleted', last_modified = ? "
            "WHERE id = ? AND pub_status != 'deleted'",
            (_now_kst(), article_id),
        )
        return cur.rowcount > 0


def purge_old_deleted(days: int = 30) -> int:
    """삭제(deleted) 후 N일 경과한 행의 세부 텍스트를 영구삭제하여 저장공간 회수.
    - row 자체는 유지(email_id UNIQUE 보존 → 재수집/재처리 방지)
    - pub_status='purged'로 전환 → 휴지통(pub_status='deleted')에서도 조회되지 않음
    - 재처리는 pub_status='pending'만 대상이므로 'purged'는 안전
    삭제 시점(last_modified)의 날짜 기준으로 경과 여부 판단. DB 컬럼 추가 없음.
    반환: 영구삭제 처리된 행 수."""
    cutoff = (_dt.datetime.now() - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE articles
               SET original_title  = '',
                   company_name    = '',
                   headline        = '',
                   summary_core    = '',
                   summary_details = '[]',
                   tag             = '',
                   fail_reason     = NULL,
                   pub_status      = 'purged'
             WHERE pub_status = 'deleted'
               AND last_modified IS NOT NULL
               AND substr(last_modified, 1, 10) < ?
            """,
            (cutoff,),
        )
        return cur.rowcount


def restore_article(article_id: int) -> bool:
    """휴지통 기사 복원 (pub_status='deleted' → 'published'). 삭제 상태가 아니면 False."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE articles SET pub_status = 'published' WHERE id = ? AND pub_status = 'deleted'",
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
    summary_details,
    ticker_color: str = "blue",
    parse_method: Optional[str] = None,
) -> bool:
    """작업 2 성공 — 한국어 요약 UPDATE + pub_status='published'.
    ticker가 None이 아닌 경우 ticker 컬럼도 함께 업데이트.
    last_modified=now, fail_reason=NULL.
    (summary_core/tag/tag_color는 더 이상 생성하지 않아 건드리지 않음 — 기존 값 유지)
    이미 published 아닌 row만 영향 (실패 → 발행 전환 포함)."""
    last_modified = _now_kst()
    if ticker is not None:
        # 동일 종목(GOOGL=GOOG 등) 티커 병합
        ticker, company_name = canonicalize_tickers(ticker, company_name)
    with get_conn() as conn:
        # company_name 빈 슬롯을 티커 정식명으로 백필 (매크로/라운드업 기사 영구 해결).
        # ticker가 None이면(=Claude 빈 반환, Stage-1 프리픽스 유지) 현재 저장된 ticker 기준.
        try:
            import ticker_names
            eff_ticker = ticker
            if eff_ticker is None:
                _r = conn.execute("SELECT ticker FROM articles WHERE id = ?", (article_id,)).fetchone()
                eff_ticker = _r[0] if _r else ""
            company_name = ticker_names.fill_company(eff_ticker, company_name)
        except Exception:
            pass
        if ticker is not None:
            cur = conn.execute(
                """
                UPDATE articles SET
                  ticker = ?, company_name = ?, headline = ?,
                  summary_details = ?, ticker_color = ?, parse_method = ?,
                  pub_status = 'published', last_modified = ?, fail_reason = NULL
                WHERE id = ? AND pub_status != 'deleted'
                """,
                (
                    ticker, company_name, headline,
                    json.dumps(summary_details, ensure_ascii=False),
                    ticker_color, parse_method, last_modified, article_id,
                ),
            )
        else:
            cur = conn.execute(
                """
                UPDATE articles SET
                  company_name = ?, headline = ?,
                  summary_details = ?, ticker_color = ?, parse_method = ?,
                  pub_status = 'published', last_modified = ?, fail_reason = NULL
                WHERE id = ? AND pub_status != 'deleted'
                """,
                (
                    company_name, headline,
                    json.dumps(summary_details, ensure_ascii=False),
                    ticker_color, parse_method, last_modified, article_id,
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
    """발행 큐 통계 (어드민용). pub_status별 카운트 (deleted 포함 모든 상태).
    추가로 발행된 기사 중 미읽음 수를 'unread' 키로 포함."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT pub_status, COUNT(*) FROM articles GROUP BY pub_status"
        ).fetchall()
        stats = {r[0]: r[1] for r in rows}
        unread = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE pub_status = 'published' AND is_read = 0"
        ).fetchone()[0]
    stats["unread"] = unread
    return stats


def get_dashboard_stats() -> dict:
    """대시보드 통계 — pub_status='published'(삭제/대기/실패 제외)를 모수로 집계.
    기업별·일별·시간대별·감정(색상)·읽음 분포 반환."""
    from collections import Counter

    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE pub_status='published'"
        ).fetchone()[0]
        unread = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE pub_status='published' AND is_read=0"
        ).fetchone()[0]

        # 일별 (email_time_et = 'YYYY-MM-DD HH:MM KST' → 앞 10자 = 날짜)
        daily = conn.execute(
            """SELECT substr(email_time_et,1,10) AS d, COUNT(*)
               FROM articles
               WHERE pub_status='published' AND email_time_et IS NOT NULL AND email_time_et != ''
               GROUP BY d ORDER BY d"""
        ).fetchall()

        # 시간대별 (12~13번째 글자 = 시)
        hourly = conn.execute(
            """SELECT substr(email_time_et,12,2) AS h, COUNT(*)
               FROM articles
               WHERE pub_status='published' AND length(email_time_et) >= 16
               GROUP BY h ORDER BY h"""
        ).fetchall()

        # 기업별 — 다중 ticker 행 분리 위해 원본 fetch
        rows = conn.execute(
            "SELECT ticker, company_name FROM articles WHERE pub_status='published'"
        ).fetchall()

    counts, names = _split_ticker_counts(rows)
    companies = [
        {"ticker": t, "name": names.get(t, ""), "count": c}
        for t, c in counts.most_common(30)
    ]

    return {
        "total": total,
        "read": total - unread,
        "unread": unread,
        "company_count": len(counts),
        "first_date": daily[0][0] if daily else None,
        "last_date": daily[-1][0] if daily else None,
        "daily": [{"date": d, "count": c} for d, c in daily],
        "hourly": [{"hour": h, "count": c} for h, c in hourly],
        "companies": companies,
        "weekly": get_weekly_rankings(weeks=6, top_n=50),
    }


def _split_ticker_counts(rows) -> tuple:
    """(ticker, company_name) 행 목록 → (Counter, {ticker:name}). 다중 ticker 분리."""
    from collections import Counter
    counts: Counter = Counter()
    names: dict[str, str] = {}
    for ticker, company in rows:
        if not ticker:
            continue
        # 동일 종목(GOOGL=GOOG 등) 병합 후 집계 — 과거 데이터도 합산
        ticker, company = canonicalize_tickers(ticker, company)
        tks = [t.strip() for t in str(ticker).split(",")]
        cos = [c.strip() for c in str(company or "").split("·")]
        seen_row = set()
        for i, t in enumerate(tks):
            if not t or t.upper() == "NONE" or t in seen_row:
                continue
            seen_row.add(t)  # 한 기사에서 같은 티커 중복 카운트 방지
            counts[t] += 1
            if t not in names:
                names[t] = cos[i] if i < len(cos) else (cos[0] if cos else "")
    return counts, names


def get_weekly_rankings(weeks: int = 4, top_n: int = 8) -> dict:
    """최근 N주 주차별 기업 기사수 랭킹. 순위 변동(bump chart)용.
    삭제(deleted)·영구삭제(purged) 기사도 포함해 실제 수집 볼륨을 반영.
    주 구간은 일요일~토요일 고정 달력주(오늘이 포함된 주가 최신, 진행 중일 수 있음).
    각 주의 top_n 합집합을 series로 반환,
    ranks[i]는 i번째 주 순위(top_n 밖이면 null), counts[i]는 해당 주 기사수."""
    import datetime as dt

    today = dt.date.today()
    # 이번 주 일요일 찾기 (weekday: Mon=0..Sun=6 → 일요일까지 지난 일수)
    days_since_sunday = (today.weekday() + 1) % 7
    this_sunday = today - dt.timedelta(days=days_since_sunday)
    buckets = []  # 오래된→최신, 각 (일요일, 토요일)
    for k in range(weeks - 1, -1, -1):
        start = this_sunday - dt.timedelta(days=7 * k)
        end = start + dt.timedelta(days=6)
        buckets.append((start, end))

    week_counts = []
    names: dict[str, str] = {}
    with get_conn() as conn:
        for start, end in buckets:
            # 주차별 랭킹은 삭제된 기사도 포함 (수집된 뉴스 볼륨 반영).
            # purged(30일 경과 영구삭제)도 ticker는 보존되므로 포함.
            rows = conn.execute(
                """SELECT ticker, company_name FROM articles
                   WHERE pub_status IN ('published','deleted','purged')
                     AND substr(email_time_et,1,10) BETWEEN ? AND ?""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
            c, nm = _split_ticker_counts(rows)
            week_counts.append(c)
            for t, n in nm.items():
                names.setdefault(t, n)

    # 주차별 순위(1-based, 기사수 desc → 동수는 ticker abc)
    week_rank = []
    for c in week_counts:
        ordered = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
        week_rank.append({t: i + 1 for i, (t, _) in enumerate(ordered)})

    # 표시 대상: 4주 합계 상위 top_n 기업 (라인 수를 top_n개로 고정 → 가독성)
    from collections import Counter
    total_counts: Counter = Counter()
    for c in week_counts:
        total_counts.update(c)
    selected = [t for t, _ in total_counts.most_common(top_n)]

    series = []
    for t in selected:
        ranks, cnts = [], []
        for i in range(len(buckets)):
            r = week_rank[i].get(t)
            ranks.append(r if (r is not None and r <= top_n) else None)
            cnts.append(week_counts[i].get(t, 0))
        best = min([r for r in ranks if r is not None], default=999)
        series.append({
            "ticker": t, "name": names.get(t, ""),
            "ranks": ranks, "counts": cnts, "best": best,
        })
    series.sort(key=lambda s: (s["best"], s["ticker"]))

    week_labels = [f"{s.month}/{s.day}~{e.month}/{e.day}" for s, e in buckets]
    return {"top_n": top_n, "weeks": week_labels, "series": series}


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
    full_path = ASURADA_DIR / original_path

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

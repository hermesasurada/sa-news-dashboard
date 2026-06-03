"""
SA News Dashboard — FastAPI 앱
"""
from fastapi import FastAPI, Query, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import db
import os
import sys

BASE_DIR = Path(__file__).parent

app = FastAPI(title="SA News Dashboard")

# DB 초기화
db.init_db()

# Static files (index.html, app.js, etc.)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
def root():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/articles")
def get_articles(
    q: str = Query("", description="검색어 (제목/회사명/티커/요약)"),
    ticker: str = Query("", description="티커 필터"),
    date_from: str = Query("", description="시작 날짜 YYYY-MM-DD (email_time_et 기준)"),
    date_to: str = Query("", description="종료 날짜 YYYY-MM-DD (email_time_et 기준)"),
    sort_by: str = Query("email_time_et", description="정렬 기준: email_time_et | last_modified"),
    unread_only: bool = Query(False, description="미읽음만 보기"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return db.query_articles(
        q=q, ticker=ticker,
        date_from=date_from, date_to=date_to,
        sort_by=sort_by,
        unread_only=unread_only,
        limit=limit, offset=offset,
    )


@app.get("/api/filters")
def get_filters():
    return db.get_filter_options()


@app.get("/api/queue_stats")
def get_queue_stats():
    stats = db.get_queue_stats()
    return {
        "pending": stats.get("pending", 0),
        "failed": stats.get("failed", 0),
        "unread": stats.get("unread", 0),
    }


@app.get("/api/article/{article_id}")
def get_article(article_id: int):
    import sqlite3, json
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM articles WHERE id = ? AND pub_status != 'deleted'", (article_id,)
        ).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    d = dict(row)
    sd = d["summary_details"]
    try:
        d["summary_details"] = json.loads(sd)
    except (json.JSONDecodeError, TypeError):
        import ast
        try:
            parsed = ast.literal_eval(sd)
            d["summary_details"] = parsed if isinstance(parsed, list) else []
        except (ValueError, SyntaxError):
            d["summary_details"] = []
    return d


@app.patch("/api/articles/{article_id}/read")
def mark_article_read_endpoint(
    article_id: int,
    is_read: bool = Body(True, embed=True),
):
    """읽음/안읽음 토글."""
    success = db.mark_article_read(article_id, is_read)
    if not success:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Article not found")
    return {"id": article_id, "is_read": is_read}


@app.delete("/api/articles/{article_id}")
def delete_article_endpoint(article_id: int):
    import db
    success = db.delete_article(article_id)
    if not success:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Article not found")
    return {"status": "deleted", "id": article_id}


# ==================== Telegram Feed API ====================

@app.get("/api/telegram_feeds")
def get_telegram_feeds(
    q: str = Query("", description="검색어"),
    date_from: str = Query("", description="시작 날짜 YYYY-MM-DD"),
    date_to: str = Query("", description="종료 날짜 YYYY-MM-DD"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return db.query_telegram_feeds(
        q=q, date_from=date_from, date_to=date_to,
        limit=limit, offset=offset
    )


@app.get("/api/telegram_feed/{feed_id}/original")
def get_telegram_feed_original(feed_id: int):
    result = db.get_telegram_feed_original(feed_id)
    if "error" in result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/telegram")
def telegram_page():
    return FileResponse(BASE_DIR / "static" / "telegram.html")

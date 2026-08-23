"""
SA News Dashboard — FastAPI 앱
"""
from fastapi import FastAPI, Query, Body, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path
import db
from quote_service import InvalidTickerError, get_price_quote

BASE_DIR = Path(__file__).parent

app = FastAPI(title="SA News Dashboard")
app.add_middleware(GZipMiddleware, minimum_size=500)

# DB 초기화
db.init_db()

# Static files (index.html, app.js, etc.)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.middleware("http")
async def cache_versioned_static_assets(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        # root()가 파일 mtime을 쿼리 버전으로 붙이므로 변경 시 URL 자체가 바뀐다.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.url.path == "/api/filters":
        response.headers["Cache-Control"] = "private, max-age=60"
    return response


@app.get("/", response_class=HTMLResponse)
def root():
    # app.css/app.js에 mtime 기반 ?v= 를 주입 → 파일 변경 시 새로고침만으로 즉시 반영
    html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    for asset in ("app.css", "app-utils.js", "app.js"):
        try:
            v = int((BASE_DIR / "static" / asset).stat().st_mtime)
        except OSError:
            v = 0
        html = html.replace(f'/static/{asset}"', f'/static/{asset}?v={v}"')
    return HTMLResponse(html)


@app.get("/api/articles")
def get_articles(
    q: str = Query("", description="검색어 (제목/회사명/티커/요약)"),
    ticker: str = Query("", description="티커 필터"),
    date_from: str = Query("", description="시작 날짜 YYYY-MM-DD (email_time_et 기준)"),
    date_to: str = Query("", description="종료 날짜 YYYY-MM-DD (email_time_et 기준)"),
    sort_by: str = Query("email_time_et", description="정렬 기준: email_time_et | last_modified"),
    order: str = Query("desc", description="정렬 방향: desc(최신순) | asc(과거순)"),
    unread_only: bool = Query(False, description="미읽음만 보기"),
    deleted: bool = Query(False, description="휴지통(삭제됨)만 보기"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_total: bool = Query(True, description="정확한 검색 결과 건수 포함"),
    include_queue: bool = Query(True, description="대기·실패·미읽음 통계 포함"),
):
    return db.query_articles(
        q=q, ticker=ticker,
        date_from=date_from, date_to=date_to,
        sort_by=sort_by, order=order,
        unread_only=unread_only,
        deleted=deleted,
        limit=limit, offset=offset,
        include_total=include_total,
        include_queue=include_queue,
    )


@app.get("/api/articles/state")
def get_articles_state():
    """새 기사 폴링용 경량 상태. 기사 본문과 큐 통계는 반환하지 않는다."""
    return {"total": db.get_published_article_count()}


@app.get("/api/filters")
def get_filters():
    return db.get_filter_options()


@app.get("/api/price-quote")
def price_quote(ticker: str = Query(..., min_length=1, max_length=32, description="Portfolio-form ticker e.g. AAPL, 005930.KS")):
    """Same-origin proxy for the portfolio service's normalized quote."""
    try:
        return get_price_quote(ticker)
    except InvalidTickerError:
        raise HTTPException(status_code=400, detail="invalid ticker")


@app.get("/api/stats")
def get_stats():
    return db.get_dashboard_stats()


@app.get("/api/health")
def get_health():
    return db.health_check()


@app.get("/stats")
def stats_page():
    return FileResponse(BASE_DIR / "static" / "stats.html")


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
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM articles WHERE id = ? AND pub_status != 'deleted'", (article_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    d = dict(row)
    d["summary_details"] = db.decode_summary_details(d.get("summary_details"))
    return d


@app.patch("/api/articles/{article_id}/read")
def mark_article_read_endpoint(
    article_id: int,
    is_read: bool = Body(True, embed=True),
):
    """읽음/안읽음 토글."""
    success = db.mark_article_read(article_id, is_read)
    if not success:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"id": article_id, "is_read": is_read}


@app.delete("/api/articles/{article_id}")
def delete_article_endpoint(article_id: int):
    success = db.delete_article(article_id)
    if not success:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"status": "deleted", "id": article_id}


@app.post("/api/articles/{article_id}/restore")
def restore_article_endpoint(article_id: int):
    """휴지통 기사 복원."""
    success = db.restore_article(article_id)
    if not success:
        raise HTTPException(status_code=404, detail="Article not found or not deleted")
    return {"status": "restored", "id": article_id}

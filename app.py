"""
SA News Dashboard — FastAPI 앱
"""
from fastapi import FastAPI, Query, Body, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
import ast
import json
import os
import sqlite3
import db

BASE_DIR = Path(__file__).parent

# Portfolio v2 (hermes-portfolio) — live change % for ticker badges
PORTFOLIO_BASE = os.environ.get("PORTFOLIO_API_BASE", "http://127.0.0.1:8765").rstrip("/")

# 시세 조회 전용 리다이렉션 — 대시보드 표기는 왼쪽(대표 티커)이지만
# 포트폴리오가 다른 클래스로 시세를 제공하는 종목. (표기/검색/DB에는 영향 없음)
QUOTE_REDIRECTS = {
    "GOOG": "GOOGL",   # Alphabet: 표기는 Class C, 시세는 Class A
}

app = FastAPI(title="SA News Dashboard")

# DB 초기화
db.init_db()

# Static files (index.html, app.js, etc.)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
def root():
    # app.css/app.js에 mtime 기반 ?v= 를 주입 → 파일 변경 시 새로고침만으로 즉시 반영
    html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    for asset in ("app.css", "app.js"):
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
):
    return db.query_articles(
        q=q, ticker=ticker,
        date_from=date_from, date_to=date_to,
        sort_by=sort_by, order=order,
        unread_only=unread_only,
        deleted=deleted,
        limit=limit, offset=offset,
    )


@app.get("/api/filters")
def get_filters():
    return db.get_filter_options()


@app.get("/api/price-quote")
def price_quote(ticker: str = Query(..., min_length=1, max_length=32, description="Portfolio-form ticker e.g. AAPL, 005930.KS")):
    """Proxy portfolio v2 /api/chart for current price + day change (viewer-only).

    Same-origin so the browser never talks to :8765 directly (CORS/Tailscale).
    """
    clean = (ticker or "").strip().upper()
    if not clean or any(ch in clean for ch in " \t\n\r/\\"):
        raise HTTPException(status_code=400, detail="invalid ticker")
    clean = QUOTE_REDIRECTS.get(clean, clean)

    def _fallback_name() -> str:
        """포트폴리오 미보유/미도달 시 NASDAQ 심볼 파일(ticker_names, 7일 캐시)로 종목명 조회."""
        try:
            import ticker_names
            return ticker_names.name_for(clean) or ""
        except Exception:
            return ""

    url = f"{PORTFOLIO_BASE}/api/chart?ticker={quote(clean, safe='.-:')}"
    raw = None
    try:
        req = Request(url, headers={"User-Agent": "sa-dashboard/1.0"})
        with urlopen(req, timeout=6) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception:
        raw = None

    current = (raw or {}).get("current_price") if isinstance(raw, dict) else None
    # 미도달/미보유(시세 없음) — 종목명만이라도 반환 (found=false)
    if not isinstance(raw, dict) or not raw.get("ticker") or current is None:
        return {
            "ticker": clean,
            "name": _fallback_name(),
            "found": False,
            "currency": "",
            "current_price": None,
            "previous_price": None,
            "change": None,
            "change_pct": None,
            "extended_change_pct": None,
            "market_label": "",
            "market_status": "",
            "is_regular": None,
        }

    previous = raw.get("previous_price")
    change = raw.get("change")
    market = raw.get("market") or {}

    # change_pct = 항상 전일대비
    change_pct = raw.get("change_pct")
    if change is not None and previous not in (None, 0):
        try:
            change_pct = float(change) / float(previous) * 100.0
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    # 애프터/프리장 프린트면 장외 등락률을 별도 필드로 병기
    ext_out = None
    ext_pct = raw.get("extended_change_pct")
    ext_price = raw.get("extended_price")
    if (
        ext_pct is not None
        and ext_price is not None
        and not market.get("is_regular", True)
        and abs(float(current) - float(ext_price)) < 1e-9
    ):
        ext_out = ext_pct

    # 포트폴리오가 이름 대신 티커를 에코하면 NASDAQ 정식명으로 보강
    name = raw.get("name") or ""
    if not name or name.upper() == clean:
        name = _fallback_name() or name or clean

    return {
        "ticker": raw.get("ticker") or clean,
        "name": name,
        "found": True,
        "currency": raw.get("currency") or "",
        "current_price": current,
        "previous_price": previous,
        "change": change,
        "change_pct": change_pct,
        "extended_change_pct": ext_out,
        "market_label": market.get("label") or "",
        "market_status": market.get("status") or "",
        "is_regular": bool(market.get("is_regular")) if market else None,
    }


@app.get("/api/stats")
def get_stats():
    return db.get_dashboard_stats()


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
    sd = d["summary_details"]
    try:
        d["summary_details"] = json.loads(sd)
    except (json.JSONDecodeError, TypeError):
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

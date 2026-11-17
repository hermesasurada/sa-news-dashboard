"""
SA News Dashboard — FastAPI 앱
"""
import re

from fastapi import FastAPI, Query, Body, HTTPException
import lan_guard  # 로컬·Tailscale 외 접속 차단(2026-10-30)
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path
import db
import summary_config
from quote_service import InvalidTickerError, get_price_quote

BASE_DIR = Path(__file__).parent
READER_FONT_DIR = Path.home() / "projects" / "hermes-reader-fonts"

app = FastAPI(title="SA News Dashboard")
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(lan_guard.ASGIGuard)

# DB 초기화
db.init_db()

# Static files (index.html, app.js, etc.)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/reader-fonts", StaticFiles(directory=READER_FONT_DIR), name="reader-fonts")


@app.middleware("http")
async def cache_versioned_static_assets(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        # root()가 파일 mtime을 쿼리 버전으로 붙이므로 변경 시 URL 자체가 바뀐다.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.url.path.startswith("/reader-fonts/"):
        response.headers["Cache-Control"] = "public, max-age=86400"
    elif request.url.path == "/api/filters":
        response.headers["Cache-Control"] = "private, max-age=60"
    return response


_ASSET_RE = re.compile(r'/static/([A-Za-z0-9._-]+\.(?:js|css))"')


def _stamp_asset(match) -> str:
    """정적 파일 주소에 mtime 버전을 붙인다(없는 파일은 v=0)."""
    name = match.group(1)
    try:
        v = int((BASE_DIR / "static" / name).stat().st_mtime)
    except OSError:
        v = 0
    return f'/static/{name}?v={v}"'


@app.get("/", response_class=HTMLResponse)
def root():
    # 정적 파일 주소에 mtime 기반 ?v= 를 주입 → 파일 변경 시 새로고침만으로 즉시 반영
    html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    # 이 저장소의 정적 파일(/static/*.js·*.css)은 이름을 나열하지 않고 패턴으로 잡는다 — 캐시가 1년
    # 고정(immutable)이라 새 파일을 목록에서 빠뜨리면 고쳐도 브라우저가 옛 파일을 계속 쓴다.
    html = _ASSET_RE.sub(_stamp_asset, html)
    try:   # 공용 글꼴 목록(fonts.js)도 고치면 바로 보이게
        v = int((READER_FONT_DIR / "fonts.js").stat().st_mtime)
    except OSError:
        v = 0
    html = html.replace('/reader-fonts/fonts.js"', f'/reader-fonts/fonts.js?v={v}"')
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
    data = db.get_filter_options()
    # 숫자 종목코드(2330.TW·688825.SS·005930.KS) 칩은 기업명으로 표기한다(2026-10-12 사용자 지시) —
    # 포트폴리오 카탈로그의 표시명칭을 내려 준다. 카탈로그를 못 읽으면 빈 맵(칩은 기사 회사명으로 폴백).
    try:
        import foreign_tickers
        data["home_names"] = foreign_tickers.numeric_code_names()
    except Exception:  # noqa: BLE001
        data["home_names"] = {}
    # 칩 표(OTC·ADR → 자국 상장, 복수 상장 추가 칩)는 증류 기업 등록부에서 만든다(2026-11-11, company_table).
    try:
        import company_table
        data["listings"] = company_table.listings()
    except Exception:  # noqa: BLE001
        data["listings"] = {"foreign": {}, "extra": {}}
    return data


@app.get("/api/price-quote")
def price_quote(ticker: str = Query(..., min_length=1, max_length=32, description="Portfolio-form ticker e.g. AAPL, 005930.KS")):
    """Same-origin proxy for the portfolio service's normalized quote."""
    try:
        return get_price_quote(ticker)
    except InvalidTickerError:
        raise HTTPException(status_code=400, detail="invalid ticker")


# ── 요약 모델 설정(wm 설정 팝업 이식, 2026-09-26) ─────────────────────────────
def _summary_config_payload() -> dict:
    cfg = summary_config.load()
    return {
        "config": cfg,
        "model_options": summary_config.selector_options(summary_config.model_options(cfg)),   # 화면용 공용 순서
        "reasoning_options": summary_config.reasoning_options(),
    }


@app.get("/api/summary-config")
def summary_config_get():
    return _summary_config_payload()


@app.post("/api/summary-config")
def summary_config_post(payload: dict = Body(...)):
    error = summary_config.validate(payload, summary_config.load())
    if error:
        raise HTTPException(status_code=400, detail=error)
    summary_config.save(payload)
    return {"ok": True, **_summary_config_payload()}


@app.get("/api/health")
def get_health():
    return db.health_check()


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


# ── 용어 툴팁(2026-11-18 사용자 지시) ─────────────────────────────────────
# 카드 요약 속 용어에 점선 밑줄 + 뜻풀이 창(인명 소개 방식). 뜻풀이는 공용 용어집
# (hermes-llm-log/term_glossary — yt·wm 요약 각주에서 모은다). td와 같은 DB·같은 화면 파일(term-tips.js).
def _term_glossary():
    import sys as _sys
    lib = str(Path.home() / "projects/hermes-llm-log")
    if lib not in _sys.path:
        _sys.path.append(lib)
    import term_glossary
    return term_glossary


@app.get("/api/terms")
def get_terms(ids: str = Query("")):
    """ids=1,2,3 → {article_id: [{key, term, full_name, korean, definition, forms, sources}]}. 실패하면 빈 응답."""
    wanted = [int(x) for x in ids.split(",") if x.strip().isdigit()][:200]
    if not wanted:
        return {}
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                f"SELECT id, summary_details FROM articles WHERE id IN ({','.join('?' * len(wanted))})", wanted
            ).fetchall()
        texts = {str(r["id"]): "\n".join(db.decode_summary_details(r["summary_details"])) for r in rows}
        return _term_glossary().terms_for_texts(texts, source="sa")
    except Exception:
        return {}


@app.post("/api/terms/excluded")
def set_term_excluded(payload: dict = Body(...)):
    """용어 툴팁에서 빼기/되돌리기 {key, excluded}. 공용 용어집이라 td에도 같이 빠진다."""
    key = str(payload.get("key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="key required")
    try:
        tg = _term_glossary()
        sense = tg.sense_of(payload.get("full_name"), payload["definition"]) if payload.get("definition") else None
        ok = tg.set_excluded(key, bool(payload.get("excluded", True)), sense=sense)
    except Exception:
        ok = False
    return {"ok": ok}

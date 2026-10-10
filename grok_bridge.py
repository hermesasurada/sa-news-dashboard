"""Grok Bot 원문 연동(2026-10-11 사용자 결정) — sa는 SA 사이트에 접속하지 않는다.

  1. sa가 메일로 받은 새 기사(pending)의 news_id·url을 드라이브 'SA Grok/requests/req_*.json'에 올린다
  2. Grok Bot이 그 기사를 열어 자세한 핵심 사실(key_facts)을 'SA Grok/results/sa_<news_id>.json'으로 올린다
     (전문 복제는 저작권·약관 때문에 Grok이 하지 않는다 — 2026-10-11)
  3. sa가 주기적으로 결과를 확인해, 요청한 기사의 결과가 들어와 있으면 원문으로 저장한다
     → 요약·헤드라인·티커는 지금까지와 같은 요약 파이프라인(sa_summarize_claude, 저장 본문 재사용)이 만든다

결과 판정
  - status=full                → 그 원문으로 요약
  - status=partial, attempt<3  → Grok이 다시 시도하도록 기다린다
  - status=partial, attempt>=3 → 읽은 만큼으로 요약(source_method='grok_partial')
  - status=failed,  attempt>=3 → 실패 처리(pub_status='failed')
  - 요청 후 GROK_TIMEOUT_HOURS가 지나도 결과가 없으면 실패 처리

드라이브 접근은 gdrive.py(ses1430 계정, drive.file + drive.readonly). 여기서 나는 예외는 요약 배치를
멈추지 않는다 — 호출부가 잡고 다음 주기에 다시 한다.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import db
import gdrive
import settings

ROOT_NAME = "SA Grok"
STATE_PATH = settings.BASE_DIR / ".grok_bridge_state.json"
KST = timezone(timedelta(hours=9))
_ID_RE = re.compile(r"seekingalpha\.com/(?:news|article)/(\d+)")
MAX_ATTEMPTS = 3


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def news_id(url: str | None) -> str | None:
    m = _ID_RE.search(url or "")
    return m.group(1) if m else None


def ensure_columns() -> None:
    with db.get_conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(articles)")}
        for col, ddl in (("grok_requested_at", "TEXT"), ("grok_status", "TEXT"),
                         ("grok_attempt", "INTEGER"), ("grok_result_mtime", "TEXT")):
            if col not in cols:
                conn.execute(f"ALTER TABLE articles ADD COLUMN {col} {ddl}")


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def folders() -> dict:
    """'SA Grok'·requests·results 폴더 id(없으면 만든다). 상태 파일에 기억한다."""
    state = _load_state()
    if state.get("root") and state.get("requests") and state.get("results"):
        return state
    root = gdrive.ensure_folder(ROOT_NAME)
    state = {"root": root,
             "requests": gdrive.ensure_folder("requests", root),
             "results": gdrive.ensure_folder("results", root)}
    STATE_PATH.write_text(json.dumps(state), encoding="utf-8")
    return state


def send_requests(fold: dict) -> int:
    """아직 요청하지 않은 pending 기사를 요청 파일 하나로 올린다. URL이 SA 기사가 아니면 실패 처리."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, article_url FROM articles WHERE pub_status = 'pending' "
            "AND grok_requested_at IS NULL ORDER BY id").fetchall()
    items, bad = [], []
    for r in rows:
        nid = news_id(r["article_url"])
        (items.append({"news_id": nid, "url": r["article_url"]}) if nid else bad.append(r["id"]))
    now = _now()
    with db.get_conn() as conn:
        for aid in bad:
            conn.execute("UPDATE articles SET pub_status = 'failed', fail_reason = ?, last_modified = ? "
                         "WHERE id = ? AND pub_status = 'pending'", ("SA 기사 링크 없음(Grok 요청 불가)", now, aid))
    if not items:
        return 0
    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    gdrive.upload_json(f"req_{stamp}.json", fold["requests"],
                       {"schema": 1, "created_at": now, "items": items})
    with db.get_conn() as conn:
        conn.executemany("UPDATE articles SET grok_requested_at = ?, grok_status = 'requested' WHERE id = ?",
                         [(now, r["id"]) for r in rows if news_id(r["article_url"])])
    print(f"  Grok 요청 {len(items)}건 업로드 (req_{stamp}.json)")
    return len(items)


def _source_text(res: dict) -> str:
    """요약 입력 텍스트. Grok은 저작권 때문에 전문 대신 자세한 핵심 사실 목록(key_facts)을 준다
    (2026-10-11 Grok 회신, 사용자 수용). 예전 형식(body)도 받는다."""
    parts = [str(res.get(k) or "").strip() for k in ("title", "subtitle", "summary")]
    facts = res.get("key_facts")
    if isinstance(facts, str):
        facts = [facts]
    if isinstance(facts, list):
        parts.append("\n".join(f"- {str(x).strip()}" for x in facts if str(x).strip()))
    quotes = res.get("quotes")
    if isinstance(quotes, list) and quotes:
        parts.append("\n".join(f'"{str(q).strip()}"' for q in quotes if str(q).strip()))
    parts.append(str(res.get("body") or "").strip())
    return "\n\n".join(p for p in parts if p)


def collect_results(fold: dict) -> dict:
    """결과 폴더를 읽어 요청한 pending 기사에 원문을 저장한다. 처리 건수 요약을 돌려준다."""
    stats = {"ready": 0, "waiting": 0, "failed": 0, "timeout": 0}
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, article_url, grok_requested_at, grok_result_mtime FROM articles "
            "WHERE pub_status = 'pending' AND grok_requested_at IS NOT NULL").fetchall()
    if not rows:
        return stats
    # 다시 시도하면 Grok은 새 파일을 올리고 이전 것을 휴지통으로 보낸다(파일 id가 바뀜) —
    # 잠깐 같은 이름이 둘이면 가장 최근 것을 쓴다.
    files: dict = {}
    for f in gdrive.list_children(fold["results"], "sa_"):
        if f["name"] not in files or f.get("modifiedTime", "") > files[f["name"]].get("modifiedTime", ""):
            files[f["name"]] = f
    now = _now()
    timeout = datetime.now(KST) - timedelta(hours=settings.GROK_TIMEOUT_HOURS)
    for r in rows:
        nid = news_id(r["article_url"])
        f = files.get(f"sa_{nid}.json")
        if not f:
            try:
                requested = datetime.fromisoformat(r["grok_requested_at"])
            except ValueError:
                requested = datetime.now(KST)
            if requested < timeout:
                _fail(r["id"], f"Grok 결과 없음({settings.GROK_TIMEOUT_HOURS}시간 초과)", now)
                stats["timeout"] += 1
            else:
                stats["waiting"] += 1
            continue
        if f.get("modifiedTime") == r["grok_result_mtime"]:
            stats["waiting"] += 1              # 이미 본 결과(다시 시도를 기다리는 중)
            continue
        try:
            res = json.loads(gdrive.download_text(f["id"]))
        except (ValueError, gdrive.DriveError) as exc:
            print(f"  [{r['id']}] Grok 결과 읽기 실패: {exc}")
            stats["waiting"] += 1
            continue
        status = str(res.get("status") or "").lower()
        attempt = int(res.get("attempt") or 1)
        text = _source_text(res)
        final = attempt >= MAX_ATTEMPTS
        with db.get_conn() as conn:
            conn.execute("UPDATE articles SET grok_status = ?, grok_attempt = ?, grok_result_mtime = ? "
                         "WHERE id = ?", (status or "unknown", attempt, f.get("modifiedTime"), r["id"]))
        if status == "full" and text:
            db.save_source(r["id"], text=text, method="grok", locked=False)
            stats["ready"] += 1
        elif status == "partial" and text and final:
            db.save_source(r["id"], text=text, method="grok_partial", locked=False)
            stats["ready"] += 1
        elif final:
            _fail(r["id"], f"Grok 원문 실패: {str(res.get('note') or status)[:120]}", now)
            stats["failed"] += 1
        else:
            stats["waiting"] += 1              # partial/failed 1~2회차 — Grok이 다시 시도한다
    return stats


def _fail(article_id: int, reason: str, now: str) -> None:
    with db.get_conn() as conn:
        conn.execute("UPDATE articles SET pub_status = 'failed', fail_reason = ?, last_modified = ?, "
                     "grok_status = COALESCE(grok_status, 'timeout') WHERE id = ? AND pub_status = 'pending'",
                     (reason[:200], now, article_id))


def cleanup_requests(fold: dict, keep_days: int = 7) -> int:
    """오래된 요청 파일 정리(sa가 만든 파일만 지운다)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    n = 0
    for f in gdrive.list_children(fold["requests"], "req_"):
        try:
            mt = datetime.fromisoformat(f["modifiedTime"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if mt < cutoff:
            try:
                gdrive.delete_file(f["id"])
                n += 1
            except gdrive.DriveError:
                pass
    return n


def ready_rows(limit: int) -> list[dict]:
    """Grok 원문이 저장돼 요약할 수 있는 pending 기사."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, email_id, ticker, original_title, article_url, email_time_et, retry_count, last_attempt "
            "FROM articles WHERE pub_status = 'pending' AND source_method IN ('grok', 'grok_partial') "
            "AND COALESCE(source_text, '') <> '' AND retry_count < ? ORDER BY id LIMIT ?",
            (settings.MAX_RETRY, limit)).fetchall()
    return [dict(r) for r in rows]


def sync() -> dict:
    """요청 올리기 + 결과 가져오기. 드라이브 오류는 올려 보낸다(호출부가 잡는다)."""
    ensure_columns()
    fold = folders()
    sent = send_requests(fold)
    stats = collect_results(fold)
    stats["sent"] = sent
    try:
        stats["cleaned"] = cleanup_requests(fold)
    except gdrive.DriveError:
        stats["cleaned"] = 0
    return stats


if __name__ == "__main__":
    try:
        print(json.dumps(sync(), ensure_ascii=False))
        print(json.dumps(folders(), ensure_ascii=False))
    except (gdrive.DriveError, sqlite3.Error) as exc:
        print("오류:", exc)
        raise SystemExit(1)

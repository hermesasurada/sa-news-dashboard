"""Grok Bot 원문 연동(2026-10-11 사용자 결정) — sa는 SA 사이트에 접속하지 않는다.

  1. sa가 메일로 받은 새 기사(pending)의 news_id·url을 드라이브 'SA Grok/requests/req_*.json'에 올린다
  2. Grok Bot이 그 기사를 열어 자세한 핵심 사실(key_facts)을 'SA Grok/results/sa_<news_id>.json'으로 올린다
     (전문 복제는 저작권·약관 때문에 Grok이 하지 않는다 — 2026-10-11)
  3. sa가 주기적으로 결과를 확인해, 요청한 기사의 결과가 들어와 있으면 원문으로 저장한다
     → 요약·헤드라인·티커는 지금까지와 같은 요약 파이프라인(sa_summarize_claude, 저장 본문 재사용)이 만든다

결과 판정
  - status=full                → 그 원문으로 요약
  - 결과 파일에 final(true/false)이 있으면 그것을 따른다(2026-10-13 Grok Bot 제안·사용자 승인):
    final=true면 Grok이 더 시도하지 않는다는 뜻 — partial은 읽은 만큼으로 요약, failed는 실패 처리.
    final=false면 Grok이 다시 시도하므로 기다린다. reason(premium·truncated·retries_exhausted 등)은 기록용.
  - final이 없는 예전 형식은 attempt로 판단한다:
    status=partial, attempt<3  → Grok이 다시 시도하도록 기다린다
    status=partial, attempt>=3 → 읽은 만큼으로 요약(source_method='grok_partial')
    status=failed,  attempt>=3 → 실패 처리(pub_status='failed')
  - 요청 후 GROK_TIMEOUT_HOURS가 지나도 결과가 없으면 실패 처리

병행 모드(hybrid, 2026-11-26 사용자 지시 — 기본값): sa는 지금처럼 Jina로 원문을 받아 곧바로 요약·게시하고,
같은 기사를 Grok에도 요청해 둔다. Grok 결과가 GROK_HYBRID_WAIT_HOURS 안에 들어오면 Jina가 못 준 경우만 갈아 끼운다
(collect_updates) — Jina가 실패했거나 유료벽에서 문장 중간에 끊긴 기사(jina_cut), Jina 아닌 짧은 경로로 받은 기사.
Jina가 전문을 받은 기사는 Grok의 바꿔 쓴 본문보다 원문이 낫기 때문에 그대로 둔다. Grok 쪽 실패·시간 초과는
기사를 실패 처리하지 않는다(게시 여부는 Jina 쪽이 정한다).

드라이브 접근은 gdrive.py(ses1430 계정, drive.file + drive.readonly). 여기서 나는 예외는 요약 배치를
멈추지 않는다 — 호출부가 잡고 다음 주기에 다시 한다.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import db
import db_schema
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
    """Grok 연동 열이 없으면 만든다 — 정의는 db_schema 한 곳(init_db도 같은 함수를 부른다)."""
    with db.get_conn() as conn:
        db_schema.add_missing_columns(conn)


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


def send_requests(fold: dict, fail_bad: bool = True) -> int:
    """아직 요청하지 않은 pending 기사를 요청 파일 하나로 올린다. URL이 SA 기사가 아니면 실패 처리
    (병행 모드는 fail_bad=False — 게시 여부는 Jina 쪽이 정한다)."""
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
        for aid in (bad if fail_bad else []):
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
    files = _result_files(fold)
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
        final = _is_final(res, attempt)
        # 끝나지 않은 결과(끊김·차단 1~2회차)는 waiting으로 둔다 — failed·partial로 적으면 병행 모드로 바꾼 뒤
        # collect_updates가 닫힌 기사로 보고 다시 읽지 않는다(2026-11-26 sa 12623·12624, 뒤에 온 전문을 놓침).
        stored = (status or "unknown") if final or status == "full" else "waiting"
        with db.get_conn() as conn:
            conn.execute("UPDATE articles SET grok_status = ?, grok_attempt = ?, grok_result_mtime = ?, "
                         "grok_result_json = ? WHERE id = ?",
                         (stored, attempt, f.get("modifiedTime"),
                          json.dumps(res, ensure_ascii=False), r["id"]))
        method = "grok" if status == "full" and text else ("grok_partial" if status == "partial" and text and final else None)
        if method and not db.source_quality_ok(len(text), False, method):
            # 요약 단계가 같은 원문을 길이 미달로 거절하며 5번 재시도하던 것을 받을 때 바로 끝낸다(2026-11-25, sa 12601 —
            # 유료 기사라 Grok이 앞부분 164자만 주고 final=true). 원문은 남겨 둔다.
            db.save_source(r["id"], text=text, method=method, locked=False)
            if method == "grok":
                label = "원문이 너무 짧음"
            elif "premium" in str(res.get("reason") or "").lower():
                label = "유료 기사 앞부분만"
            else:
                label = "본문 일부만"               # 3번 시도해도 끊긴 경우(retries_exhausted·truncated)
            _fail(r["id"], f"Grok {label}({len(text)}자, 요약 기준 미달)", now)
            stats["failed"] += 1
        elif method:
            db.save_source(r["id"], text=text, method=method, locked=False)
            stats["ready"] += 1
        elif final:
            why = " · ".join(str(x) for x in (res.get("reason"), res.get("note") or status) if x)
            _fail(r["id"], f"Grok 원문 실패: {why[:120]}", now)
            stats["failed"] += 1
        else:
            stats["waiting"] += 1              # partial/failed 1~2회차 — Grok이 다시 시도한다
    return stats


def _result_files(fold: dict) -> dict:
    """결과 폴더의 {파일 이름: 파일}. 다시 시도하면 Grok은 새 파일을 올리고 이전 것을 휴지통으로 보낸다(파일 id가
    바뀜) — 잠깐 같은 이름이 둘이면 가장 최근 것을 쓴다."""
    files: dict = {}
    for f in gdrive.list_children(fold["results"], "sa_"):
        if f["name"] not in files or f.get("modifiedTime", "") > files[f["name"]].get("modifiedTime", ""):
            files[f["name"]] = f
    return files


_END_RE = re.compile(r"[.!?…\"'”’)\]]$")
_BODY_STOP_RE = re.compile(r"^(?:## Recommended For You|## Quick Insights|\*\s+Share)\s*$", re.M)


def jina_cut(text: str | None) -> bool:
    """Jina 원문이 유료벽에서 문장 중간에 끊겼는가 — 본문 마지막 줄이 문장부호로 끝나지 않으면 끊긴 것으로 본다
    (sa 12666 '…(quadriplegia), the', 12667 '*   The'). 본문 끝은 공유 버튼('*   Share')이나 '## Recommended For You'
    앞이고(2026-11-26: 'Quick Insights' 문답 블록도 — sa 12624는 끊긴 본문 뒤 문답이 마침표로 끝나 전문으로 오판),
    그 바로 앞의 뉴스레터 홍보 블록(머리글·설명·'Subscribe to …'·'Sign Up')과 AI 기사 면책 문구는 뺀다. 2026-11-17~25 Jina
    753건 중 537건(71%)이 끊긴 것으로 나온다 — 대부분의 SA 뉴스는 비로그인에 첫 불릿 한두 개만 보인다."""
    m = _BODY_STOP_RE.search(text or "")
    seg = (text or "")[:m.start()] if m else (text or "")
    lines = [ln.strip() for ln in seg.splitlines() if ln.strip()]
    if len(lines) >= 4 and lines[-1] == "Sign Up" and lines[-2].startswith("Subscribe"):
        lines = lines[:-4]
    while lines and lines[-1].startswith("**Seeking Alpha's Disclaimer"):
        lines.pop()                                   # AI 생성 기사 끝의 면책 문구
    return not lines or not _END_RE.search(lines[-1])


def _grok_worth(row) -> bool:
    """병행 모드에서 Grok 원문으로 갈아 끼울 기사인가."""
    if row["pub_status"] != "published" or not row["source_text"]:
        return True                                   # Jina가 아직 못 받았거나 실패했다
    if row["source_method"] != "jina_reader":
        return True                                   # SA API 미리보기·curl 같은 짧은 경로
    return jina_cut(row["source_text"])


def collect_updates(fold: dict) -> dict:
    """병행 모드: 기다리는 Grok 결과를 읽어, Jina가 못 준 기사만 Grok 원문으로 바꿔 둔다(요약은 update_rows가 넘긴다).
    grok_status: requested(요청)·waiting(Grok이 다시 시도 중) → full·partial·failed(결과 받음)·timeout(대기 초과)."""
    stats = {"adopted": 0, "kept": 0, "waiting": 0, "failed": 0, "timeout": 0}
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, article_url, grok_requested_at, grok_result_mtime, pub_status, source_method, source_text "
            "FROM articles WHERE grok_requested_at IS NOT NULL AND grok_status IN ('requested', 'waiting') "
            "AND pub_status IN ('pending', 'published', 'failed')").fetchall()
    if not rows:
        return stats
    files = _result_files(fold)
    deadline = datetime.now(KST) - timedelta(hours=settings.GROK_HYBRID_WAIT_HOURS)
    for r in rows:
        try:
            requested = datetime.fromisoformat(r["grok_requested_at"])
        except ValueError:
            requested = datetime.now(KST)
        if requested < deadline:                      # 늦게 온 결과로 이미 읽은 요약을 바꾸지 않는다
            _set_grok(r["id"], status="timeout")
            stats["timeout"] += 1
            continue
        f = files.get(f"sa_{news_id(r['article_url'])}.json")
        if not f or f.get("modifiedTime") == r["grok_result_mtime"]:
            stats["waiting"] += 1
            continue
        try:
            res = json.loads(gdrive.download_text(f["id"]))
        except (ValueError, gdrive.DriveError) as exc:
            print(f"  [{r['id']}] Grok 결과 읽기 실패: {exc}")
            stats["waiting"] += 1
            continue
        status = str(res.get("status") or "unknown").lower()
        attempt = int(res.get("attempt") or 1)
        final = status == "full" or _is_final(res, attempt)
        text = _source_text(res)
        _set_grok(r["id"], status=status if final else "waiting", attempt=attempt,
                  mtime=f.get("modifiedTime"), raw=res)
        if not final:
            stats["waiting"] += 1
            continue
        method = "grok" if status == "full" and text else ("grok_partial" if status == "partial" and text else None)
        if not method or not db.source_quality_ok(len(text), False, method):
            stats["failed"] += 1
            continue
        if not _grok_worth(r):
            stats["kept"] += 1                        # Jina가 전문을 받았다
            continue
        db.save_source(r["id"], text=text, method=method, locked=False)
        with db.get_conn() as conn:                   # 요약 재시도 횟수는 Grok 원문 기준으로 새로 센다
            conn.execute("UPDATE articles SET retry_count = 0, last_attempt = NULL WHERE id = ?", (r["id"],))
        stats["adopted"] += 1
    return stats


def _set_grok(article_id: int, *, status: str, attempt: int | None = None, mtime: str | None = None,
              raw: dict | None = None) -> None:
    with db.get_conn() as conn:
        conn.execute("UPDATE articles SET grok_status = ?, grok_attempt = COALESCE(?, grok_attempt), "
                     "grok_result_mtime = COALESCE(?, grok_result_mtime), "
                     "grok_result_json = COALESCE(?, grok_result_json) WHERE id = ?",
                     (status, attempt, mtime, json.dumps(raw, ensure_ascii=False) if raw is not None else None,
                      article_id))


def update_rows(limit: int) -> list[dict]:
    """병행 모드: Grok 원문으로 바꿔 두었고 아직 그 원문으로 요약하지 않은 기사(게시된 기사 갱신 포함)."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, email_id, ticker, original_title, article_url, email_time_et, retry_count, last_attempt, "
            "source_chars, source_method FROM articles WHERE pub_status IN ('pending', 'published', 'failed') "
            "AND source_method IN ('grok', 'grok_partial') AND COALESCE(source_text, '') <> '' "
            "AND COALESCE(parse_method, '') NOT IN ('grok', 'grok_partial') AND retry_count < ? "
            "AND grok_requested_at IS NOT NULL ORDER BY id",
            (settings.MAX_RETRY,)).fetchall()
    # 요약 기준에 못 미친 원문은 뺀다(grok 모드 때 받자마자 실패 처리한 짧은 partial — sa 12601·12605)
    ok = [dict(r) for r in rows if db.source_quality_ok(r["source_chars"], False, r["source_method"])]
    return ok[:limit]


def _is_final(res: dict, attempt: int) -> bool:
    """Grok이 이 기사를 더 시도하지 않는가. final 필드가 있으면 그것, 없으면 attempt>=3(예전 형식)."""
    flag = res.get("final")
    if isinstance(flag, bool):
        return flag
    if isinstance(flag, str) and flag.strip().lower() in ("true", "false"):
        return flag.strip().lower() == "true"
    return attempt >= MAX_ATTEMPTS


def _fail(article_id: int, reason: str, now: str) -> None:
    with db.get_conn() as conn:
        conn.execute("UPDATE articles SET pub_status = 'failed', fail_reason = ?, last_modified = ?, "
                     "grok_status = COALESCE(grok_status, 'timeout') WHERE id = ? AND pub_status = 'pending'",
                     (reason[:200], now, article_id))


def backfill_result_json(fold: dict) -> int:
    """이미 처리했지만 원본 JSON을 아직 안 남긴 기사의 결과 파일을 내려받아 저장한다(드라이브에서 지워지기 전에)."""
    with db.get_conn() as conn:
        rows = conn.execute("SELECT id, article_url FROM articles WHERE grok_status IS NOT NULL "
                            "AND grok_status <> 'requested' AND grok_result_json IS NULL").fetchall()
    if not rows:
        return 0
    files = _result_files(fold)
    n = 0
    for r in rows:
        f = files.get(f"sa_{news_id(r['article_url'])}.json")
        if not f:
            continue
        try:
            res = json.loads(gdrive.download_text(f["id"]))
        except (ValueError, gdrive.DriveError):
            continue
        with db.get_conn() as conn:
            conn.execute("UPDATE articles SET grok_result_json = ? WHERE id = ?",
                          (json.dumps(res, ensure_ascii=False), r["id"]))
        n += 1
    return n


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


def sync(hybrid: bool = False) -> dict:
    """요청 올리기 + 결과 가져오기(hybrid면 병행 모드 갱신). 드라이브 오류는 올려 보낸다(호출부가 잡는다)."""
    ensure_columns()
    fold = folders()
    sent = send_requests(fold, fail_bad=not hybrid)
    stats = collect_updates(fold) if hybrid else collect_results(fold)
    stats["sent"] = sent
    try:
        stats["json_saved"] = backfill_result_json(fold)
    except gdrive.DriveError:
        stats["json_saved"] = 0
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

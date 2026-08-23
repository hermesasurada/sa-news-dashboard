#!/usr/bin/env python3
"""Low-level Stage 2 CLI used by the summarizer and manual diagnostics.

The active cron entrypoint is ``sa_summarize_claude.py``.  It invokes this
module's ``parse`` command to isolate page parsing and capture parser metadata.
``list`` and ``stats`` remain useful read-only operator commands.
"""
import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT))

import db  # noqa: E402
import settings  # noqa: E402


def cmd_list(batch_size: int):
    """pending due 행 JSON 출력 (LLM 입력용)."""
    rows = db.get_pending_due(batch_size=batch_size)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def cmd_parse(article_id: int):
    """article_url로 SA 사이트를 파싱한 뒤 본문을 stdout에 출력. 실패 시 exit code 1.

    품질을 통과한 본문만 DB source_text 에 저장한다. 미리보기는 성공이 아니다.
    """
    from sa_article_parser import parse_sa_article
    db.init_db()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT article_url FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
    if not row:
        print(f'ERROR: article_id {article_id} not found', file=sys.stderr)
        sys.exit(2)
    url = row[0] if not hasattr(row, "keys") else row["article_url"]
    r = parse_sa_article(url)
    db.log_fetch_attempts(article_id, r.get("attempts") or [])
    content = (r.get("content") or "").strip()
    locked = bool(r.get("locked"))
    method = r.get("method") or ""
    if r.get("success") and db.source_quality_ok(len(content), locked):
        db.save_source(article_id, text=content, method=method, locked=False)
        print(f"PARSE_METHOD: {method}", file=sys.stderr)
        print(f"PARSE_CHARS: {len(content)}", file=sys.stderr)
        print("PARSE_LOCKED: 0", file=sys.stderr)
        tickers = r.get("tickers") or []
        if tickers:
            print("SA_TICKERS: " + json.dumps(tickers, ensure_ascii=False), file=sys.stderr)
        print(content)
        return
    db.save_source(article_id, text=content, method=method or None, locked=True)
    print(f"PARSE_FAIL: {r.get('error') or 'preview-only'}", file=sys.stderr)
    print(f"PARSE_CHARS: {len(content)}", file=sys.stderr)
    print("PARSE_LOCKED: 1", file=sys.stderr)
    sys.exit(1)


def cmd_stats():
    print(json.dumps(db.get_queue_stats(), ensure_ascii=False))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd')
    pl = sub.add_parser('list', help='pending due 행 JSON 출력')
    pl.add_argument('--batch', type=int, default=settings.PUBLISH_BATCH_SIZE)
    pp = sub.add_parser('parse', help='article_id의 article_url 파싱')
    pp.add_argument('article_id', type=int)
    sub.add_parser('stats', help='큐 통계')
    args = p.parse_args()
    if args.cmd == 'list':
        cmd_list(args.batch)
    elif args.cmd == 'parse':
        cmd_parse(args.article_id)
    elif args.cmd == 'stats':
        cmd_stats()
    else:
        p.print_help()


if __name__ == '__main__':
    main()

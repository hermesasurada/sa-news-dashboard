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
    """단일 article_url 파싱 후 본문 stdout 출력. 실패 시 exit code 1."""
    from sa_article_parser import parse_sa_article
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT article_url FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
    if not row:
        print(f'ERROR: article_id {article_id} not found', file=sys.stderr)
        sys.exit(2)
    url = row[0]
    r = parse_sa_article(url)
    if not r.get('success'):
        # 실패 사유 stderr, mark_attempt_failed는 LLM이 호출
        print(f'PARSE_FAIL: {r.get("error", "unknown")}', file=sys.stderr)
        sys.exit(1)
    content = r.get('content', '')
    # 어떤 파서가 쓰였는지 stderr로 전달 (호출측이 DB 기록)
    print(f'PARSE_METHOD: {r.get("method", "")}', file=sys.stderr)
    # SA 공식 태깅 티커(후보) stderr로 전달 (API 파서만 채움; 요약기가 화이트리스트로 사용)
    tickers = r.get('tickers') or []
    if tickers:
        print('SA_TICKERS: ' + json.dumps(tickers, ensure_ascii=False), file=sys.stderr)
    print(content)


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

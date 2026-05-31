#!/usr/bin/env python3
"""SA news monitor — Stage 2 (Publish): batch 후보 출력 + parse_sa_article 호출.

이 스크립트는 LLM이 cron prompt를 통해 호출한다. 흐름:
  1. `python3 sa_publish.py --list` → pending 행 (10건) JSON 출력
  2. LLM이 각 행에 대해 sa_publish.py 본 모듈 import 또는 직접 처리
  3. 본문 추출 성공 → 한국어 요약 작성 → publish_article(article_id, ...)
  4. 본문 추출 실패 → mark_attempt_failed(article_id, reason='...')

대안 `--parse <article_id>`: 해당 행의 article_url을 파싱해 본문 반환 (LLM이 직접 import 안 하고 CLI로 쓸 때).
"""
import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, '/Users/yhandhs/Documents/sa-dashboard')

import db  # noqa: E402


def cmd_list(batch_size: int):
    """pending due 행 JSON 출력 (LLM 입력용)."""
    rows = db.get_pending_due(batch_size=batch_size)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def cmd_parse(article_id: int):
    """단일 article_url 파싱 후 본문 stdout 출력. 실패 시 exit code 1."""
    from sa_article_parser import parse_sa_article
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    row = conn.execute(
        "SELECT article_url FROM articles WHERE id = ?", (article_id,)
    ).fetchone()
    conn.close()
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
    print(content)


def cmd_stats():
    print(json.dumps(db.get_queue_stats(), ensure_ascii=False))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd')
    pl = sub.add_parser('list', help='pending due 행 JSON 출력')
    pl.add_argument('--batch', type=int, default=10)
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

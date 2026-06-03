#!/usr/bin/env python3
"""SA news monitor — 휴지통 영구삭제(purge) 정리 작업.

삭제(pub_status='deleted')된 지 N일(기본 30일) 경과한 행의 세부 텍스트를
영구삭제하여 저장공간을 회수한다. row 자체는 유지(email_id UNIQUE 보존 →
재수집/재처리 방지)하고 pub_status='purged'로 전환하여 휴지통에서도 제외한다.

요약(sa_summarize_claude.py)과는 별개의 독립 유지보수 작업이므로 분리 운영한다.

사용법:
  python3 sa_purge_deleted.py            # 30일 경과분 영구삭제
  python3 sa_purge_deleted.py --days 60  # 60일 경과분
  python3 sa_purge_deleted.py --dry-run  # 대상 건수만 출력(변경 없음)
"""
import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT))

import db  # noqa: E402


def count_due(days: int) -> int:
    import datetime as dt
    cutoff = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM articles "
            "WHERE pub_status = 'deleted' AND last_modified IS NOT NULL "
            "AND substr(last_modified, 1, 10) < ?",
            (cutoff,),
        ).fetchone()[0]


def main() -> None:
    p = argparse.ArgumentParser(description="SA 휴지통 영구삭제 정리")
    p.add_argument("--days", type=int, default=30, help="삭제 후 경과 일수 기준 (기본 30)")
    p.add_argument("--dry-run", action="store_true", help="대상 건수만 출력, 변경 없음")
    args = p.parse_args()

    if args.dry_run:
        n = count_due(args.days)
        print(f"SA purge (dry-run): {args.days}일 경과 영구삭제 대상 {n}건")
        return

    purged = db.purge_old_deleted(days=args.days)
    if purged:
        print(f"SA purge: {args.days}일 경과 영구삭제 {purged}건 (행 유지)")
    else:
        print(f"SA purge: {args.days}일 경과 영구삭제 대상 없음")


if __name__ == "__main__":
    main()

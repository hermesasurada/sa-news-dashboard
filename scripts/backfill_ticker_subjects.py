"""Repair ticker metadata only; dry run by default."""
import argparse
import datetime as dt
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings
from foreign_tickers import supplement_pairs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--days", type=int, default=31)
    args = parser.parse_args()
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)).isoformat()[:10]
    with sqlite3.connect(settings.DB_PATH) as conn:
        rows = conn.execute("SELECT id, original_title, ticker, company_name FROM articles WHERE email_time_et >= ? AND pub_status = 'published'", (cutoff,)).fetchall()
        changes = []
        for ident, title, ticker, company in rows:
            updated = supplement_pairs(title or "", ticker or "", company or "")
            if updated != (ticker or "", company or ""):
                changes.append((ident, title, ticker, company, *updated))
        print(json.dumps({"scanned": len(rows), "changes": changes}, ensure_ascii=False, indent=2))
        if args.apply and changes:
            backup = settings.DB_PATH.with_suffix(".ticker-backup-" + dt.datetime.now().strftime("%Y%m%d%H%M%S") + ".db")
            with sqlite3.connect(backup) as target:
                conn.backup(target)
            count = 0
            for ident, _, old_ticker, old_name, ticker, company in changes:
                count += conn.execute("UPDATE articles SET ticker=?, company_name=? WHERE id=? AND ticker IS ? AND company_name IS ?", (ticker, company, ident, old_ticker, old_name)).rowcount
            print(json.dumps({"applied": count, "backup": str(backup)}))


if __name__ == "__main__":
    main()

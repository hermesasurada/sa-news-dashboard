#!/usr/bin/env python3
"""Backfill `email_time_et` column with correctly KST-converted email receipt time.

Targets:
  - NULL / empty email_time_et (missing on insert)
  - pub_status='published' 행만 (재작업 제외 규칙: pending/failed/deleted 행은 갱신 대상 아님)
  - INBOX envelope에만 의존 (휴지통 메일은 자동 제외 — 재작업 제외 규칙)

Strategy:
  - `himalaya envelope list -s 1000`으로 INBOX envelope DATE 필드 수집
  - 같은 폴더의 `extract_sa_urls.parse_email_date_to_kst()`로 KST 변환
  - email_id로 매칭 후 UPDATE (last_modified도 함께 갱신 — 수정시간순 정렬 누락 방지)
"""
import datetime
import shutil
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(REPO_ROOT))
from extract_sa_urls import parse_email_date_to_kst  # noqa: E402
import db  # noqa: E402


def fetch_email_times():
    """email_id (str) -> KST string"""
    result = subprocess.run(
        [shutil.which('himalaya') or '/opt/homebrew/bin/himalaya',
         'envelope', 'list', '-s', '1000'],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()[-500:]
        raise RuntimeError(f"himalaya envelope list failed (rc={result.returncode}): {detail}")
    out = {}
    for line in result.stdout.split('\n'):
        if not line.startswith('|'):
            continue
        parts = line.split('|')
        if len(parts) < 7:
            continue
        id_str = parts[1].strip()
        from_field = parts[4].strip()
        date_field = parts[5].strip() if len(parts) > 5 else ''
        if not id_str.isdigit():
            continue
        if 'SA Breaking News' not in from_field:
            continue
        kst = parse_email_date_to_kst(date_field)
        if kst:
            out[id_str] = kst
    return out


def main():
    print('himalaya envelope 수집 중...')
    email_times = fetch_email_times()
    print(f'  SA 메일 envelope: {len(email_times)}건')
    if email_times:
        ids = sorted(int(i) for i in email_times.keys())
        print(f'  email_id 범위: {ids[0]} ~ {ids[-1]}')

    with db.get_conn() as conn:
        rows = conn.execute("""
            SELECT id, email_id, email_time_et
            FROM articles
            WHERE (email_time_et IS NULL OR email_time_et = '')
              AND pub_status = 'published'
            ORDER BY id
        """).fetchall()
        print(f'\n백필 대상: {len(rows)}건')

        now_kst = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime(
            "%Y-%m-%d %H:%M KST"
        )
        fixed = 0
        missing = []
        for rid, email_id, old_email_time in rows:
            if email_id in email_times:
                new_kst = email_times[email_id]
                conn.execute(
                    'UPDATE articles SET email_time_et = ?, last_modified = ? '
                    'WHERE id = ? AND pub_status = ?',
                    (new_kst, now_kst, rid, db.STATUS_PUBLISHED),
                )
                fixed += 1
                if fixed <= 5:
                    old_disp = old_email_time if old_email_time else '(empty)'
                    print(f'  id={rid} email_id={email_id}: "{old_disp}" → "{new_kst}"')
            else:
                missing.append((rid, email_id))

        print(f'\n수정 완료: {fixed}건')
        if missing:
            print(f'envelope 못 찾음 (INBOX 밖/휴지통 등): {len(missing)}건')
            miss_ids = [item[1] for item in missing[:10]]
            print(f'  샘플 email_id: {miss_ids}')

        remaining_null = conn.execute("""
            SELECT COUNT(*) FROM articles
            WHERE (email_time_et IS NULL OR email_time_et = '')
              AND pub_status = 'published'
        """).fetchone()[0]
        print(f'\n잔여 NULL/empty (published): {remaining_null}')


if __name__ == '__main__':
    main()

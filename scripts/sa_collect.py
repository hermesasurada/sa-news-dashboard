#!/usr/bin/env python3
"""SA news monitor — Stage 1 (Collect).

수집(가벼움): 미읽음 SA 메일에서 envelope 정보만으로 DB에 pending 행을 만든다.
LLM·SA page 접속 없이 동작 → 차단·지연 위험 없음.

흐름:
  1. extract_sa_urls.py 실행 (배치 = 10건)
  2. 출력 줄 파싱: EMAIL_ID<TAB>EMAIL_TIME_KST<TAB>ORIGINAL_TITLE<TAB>ARTICLE_URL
  3. ticker prefix 추출 (없으면 'NONE')
  4. db.insert_pending_article() — 중복(이미 수집)이면 skip
  5. 처리한 email_id 전부 himalaya flag add seen

출력: 마지막 한 줄 "SA collect: N건 / HH:MM" (cron 모니터링용).
"""
import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# extract_sa_urls는 동일 디렉토리, db 모듈은 repo 루트(scripts의 상위)
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT))
import db  # noqa: E402
from sa_lock import single_instance  # noqa: E402

TICKER_PREFIX = re.compile(r'^([A-Z0-9][A-Z0-9.,\s]{0,40}[A-Z0-9])\s*:\s')


def ticker_from_subject(subject: str) -> str:
    """envelope subject prefix에서 ticker 추출. 없으면 'NONE'.
    다중 ticker는 공백 제거 후 'A,B' 형태로 보존."""
    if not subject:
        return 'NONE'
    m = TICKER_PREFIX.match(subject)
    if not m:
        return 'NONE'
    return re.sub(r'\s+', '', m.group(1))


def run_extract():
    """extract_sa_urls.py 실행 → stdout 줄 리스트.
    himalaya/IMAP 간헐 실패 대비: rc!=0 또는 빈 출력이면 최대 2회 시도.
    최종 실패 시 None 반환(호출측이 '0건'으로 오인하지 않도록 구분)."""
    last_err = ""
    for attempt in (1, 2):
        try:
            result = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / 'extract_sa_urls.py')],
                capture_output=True, text=True, timeout=180,
            )
        except subprocess.TimeoutExpired:
            last_err = "timeout(180s)"
            print(f'SA collect: extract 타임아웃 (attempt {attempt})', file=sys.stderr)
            _forensic_log(attempt, "TIMEOUT(180s)", "", "")
            continue
        # 성공: rc==0 이고 stdout이 비어있지 않음 (NO_UNREAD_SA_EMAILS 도 비어있지 않음)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.splitlines()
        last_err = f"rc={result.returncode} stderr={(result.stderr or '').strip()[-300:]}"
        print(f'SA collect: extract 실패 (attempt {attempt}) {last_err}', file=sys.stderr)
        # 포렌식: 실제 cron 실패의 rc/stderr/stdout 전체를 파일로 보존
        _forensic_log(attempt, f"rc={result.returncode}", result.stderr or "", result.stdout or "")
    print(f'SA collect: extract 최종 실패 — {last_err}', file=sys.stderr)
    return None


def _forensic_log(attempt, summary, stderr_text, stdout_text):
    """extract 실패 시 환경(PATH/LANG)과 rc/stderr/stdout 전체를 로그파일로 보존."""
    try:
        log = Path.home() / '.hermes' / 'logs' / 'sa_collect_extract_fail.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(log, 'a') as f:
            f.write(f"\n===== {ts} attempt={attempt} {summary} =====\n")
            f.write(f"PATH={os.environ.get('PATH','')}\n")
            f.write(f"LANG={os.environ.get('LANG','')} LC_ALL={os.environ.get('LC_ALL','')} HOME={os.environ.get('HOME','')}\n")
            f.write(f"--- which himalaya ---\n{shutil.which('himalaya')}\n")
            f.write(f"--- extract STDERR ---\n{stderr_text[-3000:]}\n")
            f.write(f"--- extract STDOUT ---\n{stdout_text[-1000:]}\n")
    except Exception:
        pass


def mark_seen(email_ids: list[str]) -> None:
    if not email_ids:
        return
    cmd = ['himalaya', 'flag', 'add']
    for eid in email_ids:
        cmd.extend([str(eid), 'seen'])
    subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def main():
    lines = run_extract()
    if lines is None:
        # 진짜 실패(himalaya/IMAP 오류 등) — '미읽음 없음'과 구분해 명확히 표면화
        print(f'SA collect: ⚠️ extract 실패 — 수집 건너뜀 / {datetime.datetime.now().strftime("%H:%M")}')
        return
    if not lines:
        print('SA collect: 0건 (no output)')
        return
    # 헤더가 있으면 첫 줄에 'NO_UNREAD_SA_EMAILS' 또는 'FOUND_UNREAD'
    if any('NO_UNREAD_SA_EMAILS' in ln for ln in lines):
        print(f'SA collect: 0건 / {datetime.datetime.now().strftime("%H:%M")}')
        return

    processed_ids: list[str] = []
    inserted = 0
    duplicated = 0
    skipped = 0

    for line in lines:
        parts = line.split('\t')
        if len(parts) != 4:
            continue  # 헤더/빈줄
        eid_str, email_time_kst, original_title, article_url = parts
        if article_url.startswith('NO_MAIN_ARTICLE'):
            # 메인 기사 없는 메일 → DB INSERT 없이 seen 처리 (정상 케이스)
            processed_ids.append(eid_str.strip())
            skipped += 1
            continue
        if article_url.startswith('ERROR'):
            # extract_sa_urls 일시 오류 → seen 처리 하지 않고 다음 사이클에 재시도
            print(f'SA collect: skip seen (일시 오류) eid={eid_str.strip()} reason={article_url[:120]}', file=sys.stderr)
            skipped += 1
            continue
        ticker = ticker_from_subject(original_title)
        aid = db.insert_pending_article(
            email_id=eid_str.strip(),
            ticker=ticker,
            article_url=article_url,
            original_title=original_title,
            email_time_et=email_time_kst,
        )
        if aid is None:
            duplicated += 1
        else:
            inserted += 1
        processed_ids.append(eid_str.strip())

    # seen 처리 (실패해도 다음 사이클에 중복 INSERT는 email_id UNIQUE로 차단됨)
    mark_seen(processed_ids)

    now = datetime.datetime.now().strftime('%H:%M')
    total = inserted + duplicated + skipped
    print(f'SA collect: {total}건 (신규 {inserted}/중복 {duplicated}/스킵 {skipped}) / {now}')


if __name__ == '__main__':
    # cron 틱 겹침 방지 (extract 지연 시 다음 사이클과 겹침 방지)
    with single_instance("sa-collect") as ok:
        if not ok:
            print("SA collect: 이전 수집 실행 중 — skip", file=sys.stderr)
        else:
            main()

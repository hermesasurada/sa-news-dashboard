#!/usr/bin/env python3
"""SA news monitor — Stage 1 (Collect).

수집(가벼움): 미읽음 SA 메일에서 envelope 정보만으로 DB에 pending 행을 만든다.
LLM·SA page 접속 없이 동작 → 차단·지연 위험 없음.

흐름:
  1. extract_sa_urls.py 실행 (배치 = 10건)
  2. 출력 줄 파싱: EMAIL_ID<TAB>EMAIL_TIME_KST<TAB>ORIGINAL_TITLE<TAB>ARTICLE_URL
  3. ticker prefix 추출 (없으면 'NONE'), 수집 제외 규칙(collect_filters.excluded_reason) 적용
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
from collect_filters import TICKER_PREFIX, excluded_reason  # noqa: E402
from sa_lock import single_instance  # noqa: E402

EXIT_OK = 0
EXIT_INFRA_FAILURE = 1
EXIT_PARTIAL_FAILURE = 2


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
    """미읽음 SA 메일에서 URL·본문을 읽는다.
    himalaya/IMAP 간헐 실패 대비 최대 2회. 최종 실패 시 None.
    테스트는 TSV 문자열 리스트를 그대로 주입할 수 있다."""
    import extract_sa_urls as extract
    last_err = ""
    for attempt in (1, 2):
        try:
            return extract.collect_unread_items()
        except subprocess.TimeoutExpired:
            last_err = "timeout(180s)"
            print(f'SA collect: extract 타임아웃 (attempt {attempt})', file=sys.stderr)
            _forensic_log(attempt, "TIMEOUT(180s)", "", "")
            continue
        except Exception as exc:
            last_err = str(exc)[-300:]
            print(f'SA collect: extract 실패 (attempt {attempt}) {last_err}', file=sys.stderr)
            _forensic_log(attempt, f"exc={type(exc).__name__}", str(exc), "")
    print(f'SA collect: extract 최종 실패 — {last_err}', file=sys.stderr)
    return None


def _iter_extracted(payload):
    """run_extract 결과: dict 리스트(운영) 또는 TSV 줄(테스트)."""
    if not payload:
        return
    first = payload[0]
    if isinstance(first, dict):
        for item in payload:
            yield item
        return
    for line in payload:
        if 'NO_UNREAD_SA_EMAILS' in line or line.startswith('FOUND_UNREAD'):
            continue
        parts = line.split('\t')
        if len(parts) != 4:
            continue
        eid_str, email_time_kst, original_title, article_url = parts
        yield {
            "email_id": eid_str.strip(),
            "email_time_kst": email_time_kst,
            "title": original_title,
            "article_url": article_url,
        }


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


def mark_seen(email_ids: list[str]) -> bool:
    if not email_ids:
        return True
    # 절대경로 — Desktop 앱이 cron 틱을 잡으면 PATH에 /opt/homebrew/bin이 없음
    himalaya = shutil.which('himalaya') or '/opt/homebrew/bin/himalaya'
    cmd = [himalaya, 'flag', 'add']
    for eid in email_ids:
        cmd.extend([str(eid), 'seen'])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"SA collect: seen 처리 실패 — {exc}", file=sys.stderr)
        return False
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()[-300:]
        print(f"SA collect: seen 처리 실패 (rc={result.returncode}) {detail}", file=sys.stderr)
        return False
    return True


def main() -> int:
    db.init_db()
    lines = run_extract()
    if lines is None:
        # 진짜 실패(himalaya/IMAP 오류 등) — '미읽음 없음'과 구분해 명확히 표면화
        print(f'SA collect: ⚠️ extract 실패 — 수집 건너뜀 / {datetime.datetime.now().strftime("%H:%M")}')
        return EXIT_INFRA_FAILURE
    if not lines:
        print(f'SA collect: 0건 / {datetime.datetime.now().strftime("%H:%M")}')
        return EXIT_OK
    if isinstance(lines[0], str) and any('NO_UNREAD_SA_EMAILS' in ln for ln in lines if isinstance(ln, str)):
        print(f'SA collect: 0건 / {datetime.datetime.now().strftime("%H:%M")}')
        return EXIT_OK

    processed_ids: list[str] = []
    inserted = 0
    duplicated = 0
    skipped = 0
    filtered = 0
    filtered_by: dict[str, int] = {}
    had_item_failure = False

    for item in _iter_extracted(lines):
        eid_str = item["email_id"]
        email_time_kst = item.get("email_time_kst") or ""
        original_title = item.get("title") or ""
        article_url = item.get("article_url") or ""
        if article_url.startswith('NO_MAIN_ARTICLE'):
            # 메인 기사 없는 메일 → DB INSERT 없이 seen 처리 (정상 케이스)
            processed_ids.append(eid_str.strip())
            skipped += 1
            continue
        if article_url.startswith('ERROR'):
            # extract_sa_urls 일시 오류 → seen 처리 하지 않고 다음 사이클에 재시도
            print(f'SA collect: skip seen (일시 오류) eid={eid_str.strip()} reason={article_url[:120]}', file=sys.stderr)
            skipped += 1
            had_item_failure = True
            continue
        ticker = ticker_from_subject(original_title)
        # 저가치 뉴스(우선주 배당·실적 프리뷰·펀드 공시) → 수집 제외
        # (INSERT 없이 seen 처리해 재수집 방지)
        reason = excluded_reason(original_title, ticker)
        if reason:
            processed_ids.append(eid_str.strip())
            filtered += 1
            filtered_by[reason] = filtered_by.get(reason, 0) + 1
            continue
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
    seen_ok = mark_seen(processed_ids)

    now = datetime.datetime.now().strftime('%H:%M')
    total = inserted + duplicated + skipped + filtered
    seen_label = "" if seen_ok else "/seen실패"
    filtered_label = ""
    if filtered:
        detail = '·'.join(f'{k} {v}' for k, v in sorted(filtered_by.items()))
        filtered_label = f"/제외 {filtered}({detail})"
    print(
        f'SA collect: {total}건 '
        f'(신규 {inserted}/중복 {duplicated}/스킵 {skipped}{filtered_label}{seen_label}) / {now}'
    )
    return EXIT_PARTIAL_FAILURE if had_item_failure or not seen_ok else EXIT_OK


if __name__ == '__main__':
    # cron 틱 겹침 방지 (extract 지연 시 다음 사이클과 겹침 방지)
    with single_instance("sa-collect") as ok:
        if not ok:
            print("SA collect: 이전 수집 실행 중 — skip", file=sys.stderr)
            exit_code = EXIT_OK
        else:
            exit_code = main()
    raise SystemExit(exit_code)

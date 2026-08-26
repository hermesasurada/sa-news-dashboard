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

EXIT_OK = 0
EXIT_INFRA_FAILURE = 1
EXIT_PARTIAL_FAILURE = 2

TICKER_PREFIX = re.compile(r'^([A-Z0-9][A-Z0-9.,\s]{0,40}[A-Z0-9])\s*:\s')

# 우선주 배당 공시 필터 — 시리즈별로 쏟아지는 저가치 뉴스(예: BAC.PR.S declares $0.29 dividend) 제외.
_DIVIDEND_RE = re.compile(r'\bdeclares?\b.*\bdividend\b', re.I)
_PREFERRED_TICKER_RE = re.compile(r'\.PR[.A-Z]')  # BAC.PR.S / BML.PR.G (RMS.PA 등 .PA는 불매치)
_PREFERRED_SUBJECT_RE = re.compile(
    r'\bPFD\b|\bPfd\b|Preferred|Perp\.?\s*Pfd|Depositary|Deposit\s+Sh|'
    r'Non[-\s]?Cum|\bNCUM\b|Cum\s+Pfd|Repr\s+1/',
    re.I,
)


def is_preferred_dividend(subject: str, ticker: str) -> bool:
    """우선주(preferred stock) 배당 공시 뉴스인가 → 수집 제외 대상.
    조건: 배당 선언 문구 + (우선주 티커 접미사 .PR. 또는 제목의 우선주 표지).
    일반주 배당 뉴스(예: 'AAPL declares $0.25 dividend')는 제외하지 않음."""
    s = subject or ''
    if not _DIVIDEND_RE.search(s):
        return False
    return bool(_PREFERRED_TICKER_RE.search(ticker or '') or _PREFERRED_SUBJECT_RE.search(s))


# 실적발표 '예정/프리뷰' 필터 — 실적 이벤트 자체가 주제인 기사만 제외.
# ⚠️ 'ahead of earnings'는 넣지 않는다: 실제 뉴스의 꼬리 문구인 경우가 대부분
#    (예: 'Tesla adds robotaxi cities ahead of earnings', 'Wedbush ups PT ahead of earnings').
_EARNINGS_PREVIEW_RE = re.compile(
    r'earnings\s+preview'
    r'|earnings\s+setup'
    r'|here\s+are\s+the\s+major\s+earnings'
    r'|earnings\s+(?:are\s+|is\s+)?estimated\s+to'
    r'|upcoming\s+earnings'
    r'|next\s+earnings\s+call'
    r'|heads?\s+into\s+(?:\S+\s+){0,3}earnings'
    r'|enters\s+earnings'
    r'|all\s+eyes\s+on\b[^;]{0,60}\bearnings'
    r'|earnings\s+to\s+shed\s+light'
    r'|may\s+move\s+[\d.]+%\s+on\s+earnings'
    r'|post-earnings\s+swing'
    r'|what\s+will\b[^?]{0,60}\bearnings\s+call'
    r'|what\s+to\s+expect\b[^?]{0,60}\bearnings'
    r'|earnings\s+approach',
    re.I,
)


def is_earnings_preview(subject: str) -> bool:
    """실적발표 예정/프리뷰 뉴스인가 → 수집 제외 대상.
    실제 실적 발표 결과(‘Q2 earnings beat’, ‘after earnings’ 등)는 제외하지 않음."""
    return bool(_EARNINGS_PREVIEW_RE.search(subject or ''))


# 펀드·전략의 분기 보유종목 변경/수익률 공시 필터.
# 펀드명은 항상 고유명사가 앞에 붙는다는 점을 이용 — 사명이 'Strategy'인 MSTR
# ('Strategy didn't buy or sell any bitcoin') 같은 실제 기업 뉴스 오탐 방지.
_FUND_ENTITY = (
    r"(?:(?:[A-Z][\w.&'-]*\s+){1,5}"
    r"(?:Fund|Strategy|Composite|Portfolio|Partners|Capital|Trust|Advisers?|Management)"
    r"|Fundsmith)"
)
_FUND_HOLDINGS_RE = re.compile(
    rf'{_FUND_ENTITY}\b[^:]{{0,80}}?\b(?:adds?|buys?|initiates?|boosts?|exits?|sells?|trims?)\b'
    rf'.{{0,120}}\b(?:exits?|adds?|buys?|sells?|trims?|positions?|holdings?|stakes?)\b'
    rf'|{_FUND_ENTITY}\b.{{0,80}}\b(?:returned|gained|posts?|returns?)\b.{{0,40}}\d+(?:\.\d+)?%'
    rf'|{_FUND_ENTITY}\b.{{0,60}}\bQ[1-4]\s+(?:moves|commentary|letter|update)\b'
)


def is_fund_holdings_news(subject: str) -> bool:
    """펀드·전략의 분기 보유종목 변경·수익률 공시인가 → 수집 제외 대상.
    (예: 'Polaris Global Equity Composite adds new holdings, exits positions in Q2')
    티커가 펀드 자체(PGVFX)이거나 편입 종목 나열이라 개별 종목 뉴스 가치가 낮음."""
    return bool(_FUND_HOLDINGS_RE.search(subject or ''))


# 애널리스트 커버리지 개시 필터.
# ⚠️ 'coverage'는 보험·의약품 급여, 통신망 커버리지로도 쓰이므로 반드시 애널리스트
#    동사(starts/initiates/launches/resumes/assumes)와 함께일 때만 매치시킨다.
#    'initiates'도 기업 행위(구조조정·감원 착수)에 쓰이므로 coverage 없이는
#    'initiated at/with/by' 또는 'initiated <등급>' 형태만 인정.
_COVERAGE_INIT_RE = re.compile(
    r'\b(?:starts?|initiat(?:es?|ed|ing)|launch(?:es|ed)|resum(?:es|ed)|assum(?:es|ed))\b'
    r'[^.;]{0,45}\bcoverage\b'
    r'|\bnew\s+coverage\b'
    r'|\bcoverage\s+(?:initiated|launched|assumed|resumed)\b'
    r'|\binitiated\s+(?:at|with|by)\b'
    r'|\binitiated\s+(?:Overweight|Underweight|Buy|Sell|Hold|Neutral|Outperform'
    r'|Underperform|Equal[-\s]?Weight|Market\s+Perform)\b'
    r'|\banalyst\s+initiations?\b',
    re.I,
)


def is_coverage_initiation(subject: str) -> bool:
    """증권사·기관의 커버리지 개시 뉴스인가 → 수집 제외 대상.
    등급 상·하향(upgrade/downgrade)과 목표주가 변경은 견해 '변화'라 제외하지 않음."""
    return bool(_COVERAGE_INIT_RE.search(subject or ''))


# ETF·펀드의 배당/분배 선언 필터 (커버드콜 ETF 등).
# ⚠️ 리츠(Digital Realty Trust)·일반주 배당, 그리고 'equity distribution pact'(유상증자)는
#    실제 기업 뉴스이므로 '배당/분배 선언' + 'ETF·운용사' 표지가 함께 있을 때만 매치한다.
#    금액에 마침표가 들어가므로($0.50) 사이 구간에서 '.'을 배제하면 안 된다.
_ETF_PAYOUT_RE = re.compile(r'\bdeclares?\b.{0,80}?\b(?:dividend|distribution)\b', re.I)
_ETF_VEHICLE_RE = re.compile(
    r'\bETF\b|\bYield\s+Shares\b|\bCovered\s+Call\b'
    r'|\biShares\b|\bProShares\b|\bSPDR\b|\bInvesco\b|\bVanguard\b|\bDirexion\b|\bGlobal\s+X\b'
    r'|\bIncome\s+Fund\b|\bClosed[-\s]?End\s+Fund\b',
    re.I,
)


def is_etf_distribution(subject: str) -> bool:
    """ETF·펀드의 배당/분배 선언인가 → 수집 제외 대상.
    (예: 'Palantir (PLTR) Yield Shares Purpose ETF declares $0.50 dividend')
    개별 기업 배당(NOC·Realty Income)과 리츠(Digital Realty Trust)는 제외하지 않음."""
    s = subject or ''
    return bool(_ETF_PAYOUT_RE.search(s) and _ETF_VEHICLE_RE.search(s))


_ROUNDUP_BODY_RE = re.compile(
    r"^Notable\s+\w+\s+headlines\s+for\s+the\s+week\b"
    r"|^Catalyst\s+[Ww]atch\s*:",
    re.I,
)
_ROUNDUP_ANY_RE = re.compile(
    r"\bEarnings\s+Scorecard\b"
    r"|\bKey deals this week\b"
    r"|At a glance:\s*stocks gapping"
    r"|Big movers after the closing bell"
    r"|Midday Need to Know",
    re.I,
)


def _subject_body(subject: str) -> str:
    """티커 prefix를 뺀 제목 본문."""
    if not subject:
        return ""
    m = TICKER_PREFIX.match(subject)
    return subject[m.end():].strip() if m else subject.strip()


def is_roundup_news(subject: str) -> bool:
    """특정 기업 뉴스가 아닌 주간 모음·스코어카드·갭핑 라운드업인가."""
    s = subject or ""
    body = _subject_body(s)
    if _ROUNDUP_BODY_RE.search(body):
        return True
    return bool(_ROUNDUP_ANY_RE.search(s) or _ROUNDUP_ANY_RE.search(body))


_STREAK_NAMED_RE = re.compile(r'\b(?:losing|winning)\s+streak\b', re.I)
_STREAK_SPAN_RE = re.compile(
    r'\b(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|multi)'
    r'[\s-](?:session|day|week)s?\b',
    re.I,
)
_STREAK_MOVE_RE = re.compile(
    r'\b(?:streak|rally|advance|slide|skid|slump|winning|losing|retreat|selloff|sell-off)\b',
    re.I,
)


def is_price_streak_news(subject: str) -> bool:
    """연속 상승·하락의 지속/종료만 전하는 단순 주가 흐름 기사인가 → 수집 제외.
    (예: 'Honeywell Technologies snaps eight-session losing streak')

    두 경로로 잡는다.
      1) 'losing/winning streak' 명시 — 기간 표현이 없어도 매치
         ('breaking recent losing streak')
      2) 'N-session/day/week' + 움직임 명사 — streak 없이 쓰는 형태
         ('slips after seven-session advance', 'ending six-session rally')

    기간 단위를 session/day/week으로 한정해 배당성장('57-year growth streak')과
    등급·흥행 관련('Strong Buy streak', 'box office hot streak')은 걸리지 않는다."""
    s = subject or ''
    if _STREAK_NAMED_RE.search(s):
        return True
    return bool(_STREAK_SPAN_RE.search(s) and _STREAK_MOVE_RE.search(s))


def excluded_reason(subject: str, ticker: str) -> str | None:
    """수집 제외 대상이면 사유 라벨, 아니면 None."""
    if is_preferred_dividend(subject, ticker):
        return '우선주배당'
    if is_roundup_news(subject):
        return '라운드업'
    if is_earnings_preview(subject):
        return '실적프리뷰'
    if is_fund_holdings_news(subject):
        return '펀드공시'
    if is_coverage_initiation(subject):
        return '커버리지개시'
    if is_etf_distribution(subject):
        return 'ETF배당'
    if is_price_streak_news(subject):
        return '주가연속'
    return None


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

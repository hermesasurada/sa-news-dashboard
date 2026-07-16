#!/usr/bin/env python3
"""Extract article URLs from Seeking Alpha emails using himalaya CLI.

SA emails contain base64-encoded click-tracker URLs. This script:
1. Lists all emails via plain text output and finds unread SA Breaking News ones
2. Parses email received date (DATE column) → email_time_kst (KST 변환)
3. Captures envelope subject → original_title
4. Extracts article URLs from each unread SA email
5. Identifies the main article URL (utm_content/position 파라미터 제거)

Usage: python3 extract_sa_urls.py

Output (tab-separated; subjects contain ':' so '|' / ': ' delimiters are unsafe):
  NO_UNREAD_SA_EMAILS                                            — 미읽은 이메일 없음
  FOUND_UNREAD: N emails: [id1, id2, ...]                        — 요약 헤더
  EMAIL_ID<TAB>EMAIL_TIME_KST<TAB>ORIGINAL_TITLE<TAB>ARTICLE_URL — 이메일당 한 줄
  EMAIL_ID<TAB>EMAIL_TIME_KST<TAB>ORIGINAL_TITLE<TAB>NO_MAIN_ARTICLE
  EMAIL_ID<TAB>EMAIL_TIME_KST<TAB>ORIGINAL_TITLE<TAB>ERROR - <msg>

NOTE: himalaya plain text 'flag unread' and '*' flag display are buggy.
Always use plain text output for reliable flag detection (JSON flags bug).
"""

import base64
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

# himalaya 절대경로 resolve — hermes Desktop 앱이 cron 틱을 잡으면 PATH가
# launchd 기본값(/usr/bin:/bin:...)이라 /opt/homebrew/bin을 못 봐 FileNotFoundError.
# (2026-06-10 수집 장애 근본원인. 게이트웨이/데스크톱 어느 쪽이 돌려도 동작하도록 고정)
HIMALAYA = shutil.which("himalaya") or "/opt/homebrew/bin/himalaya"


def decode_b64(s: str) -> str:
    """Decode base64 with robust padding handling."""
    for pad in range(4):
        try:
            return base64.b64decode(s + '=' * pad).decode('utf-8', errors='ignore')
        except Exception:
            continue
    return None


def strip_utm(url: str) -> str:
    """article_url에서 utm_content, position 파라미터 제거."""
    from urllib.parse import unquote
    decoded = unquote(url)
    if '?' not in decoded:
        return decoded
    base, query = decoded.split('?', 1)
    params = [p for p in query.split('&') if p and not p.startswith('utm_content') and not p.startswith('position')]
    return base + '?' + '&'.join(params) if params else base


def extract_b64_from_click_url(url: str) -> str:
    """Extract b64 string from SA email click URL.
    
    URL format: https://email-st.seekingalpha.com/click/ID/BASE64/HASH
    The b64 is the second-to-last path segment.
    """
    parts = url.split('/')
    if len(parts) >= 6:
        return parts[5]
    return None


def parse_email_date_to_kst(date_str: str) -> str:
    """himalaya DATE 컬럼 값을 KST 문자열로 변환.

    입력 형식: '2026-05-20 13:28-04:00'  (UTC offset 포함)
    출력 형식: '2026-05-20 02:28 KST'
    실패 시 빈 문자열 반환.
    """
    KST = datetime.timezone(datetime.timedelta(hours=9))
    date_str = date_str.strip()
    # '-04:00' 같은 UTC offset을 파이썬이 인식하도록 'T' 삽입
    # 형식: '2026-05-20 13:28-04:00' → '2026-05-20T13:28-04:00'
    normalized = re.sub(r'(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})', r'\1T\2', date_str)
    # 초(seconds) 없는 경우 추가
    if re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[+-]', normalized):
        normalized = re.sub(r'T(\d{2}:\d{2})([+-])', r'T\1:00\2', normalized)
    try:
        dt = datetime.datetime.fromisoformat(normalized)
        return dt.astimezone(KST).strftime('%Y-%m-%d %H:%M KST')
    except Exception:
        return ''


SAFETY_CAP = 20  # 처리 큐 안전상한 (BATCH_SIZE보다 큼, 메모리/시간 폭주 방지)


def get_unread_sa_emails():
    """Get list of unread SA Breaking News email IDs using plain text output.

    NOTE: himalaya JSON output has a bug where all flags show as ['Seen']
    regardless of actual read status. Must use plain text output and check
    if FLAGS column contains '*' (unread marker).

    Returns tuple (emails, true_total):
      - emails: list capped at SAFETY_CAP, sorted oldest first
      - true_total: actual count of unread SA emails (before cap)
    """
    # -w 500: prevent SUBJECT column truncation (default 140-char width clips long SA titles)
    result = subprocess.run(
        [HIMALAYA, 'envelope', 'list', '-s', '200', '-w', '500'],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()[-500:]
        raise RuntimeError(f"himalaya envelope list failed (rc={result.returncode}): {detail}")
    output = result.stdout

    unread_sa_emails = []
    lines = output.strip().split('\n')

    # Skip header (line 0) and separator (line 1)
    for line in lines[2:]:
        if not line.startswith('|'):
            continue
        parts = line.split('|')
        if len(parts) < 7:
            continue

        id_str = parts[1].strip()
        flags = parts[2].strip()
        subject = parts[3].strip() if len(parts) > 3 else ''
        from_field = parts[4].strip()
        date_field = parts[5].strip() if len(parts) > 5 else ''

        # '*' in flags column = unread (himalaya unread marker)
        # SA emails have "SA Breaking News" in FROM field
        if id_str and '*' in flags and 'SA Breaking News' in from_field:
            email_time_kst = parse_email_date_to_kst(date_field)
            unread_sa_emails.append({
                'id': int(id_str),
                'email_time_kst': email_time_kst,
                'subject': subject,
            })

    # Sort oldest first, then cap (true_total preserved for accurate reporting)
    unread_sa_emails.sort(key=lambda x: x['id'])
    true_total = len(unread_sa_emails)
    return unread_sa_emails[:SAFETY_CAP], true_total


_SUBJECT_STOPWORDS = {
    'a', 'an', 'the', 'and', 'or', 'of', 'to', 'for', 'in', 'on', 'at',
    'by', 'from', 'as', 'is', 'are', 'be', 'with', 'that', 'this', 'it',
    'its', 'said', 'says', 'say', 'report', 'reports', 'reuters',
    'bloomberg', 'cnbc', 'wsj', 'ft', 'over', 'after', 'before', 'amid',
    'into', 'about', 'than', 'more', 'most', 'less', 'least', 'new',
    'has', 'have', 'had', 'will', 'would', 'could', 'should', 'may',
    'might', 'can', 'who', 'what', 'when', 'where', 'why', 'how',
}


def _subject_tokens(subject: str) -> set[str]:
    """envelope subject에서 의미 있는 영어 토큰 집합 추출 (소문자, stopword 제외).
    ticker prefix("AAPL:")가 있으면 prefix는 제외하고 본문만 토큰화."""
    if not subject:
        return set()
    # ticker prefix 제거: "AAPL: ..." → "..."
    body = re.sub(r'^[A-Z0-9][A-Z0-9.,\s]{0,40}[A-Z0-9]\s*:\s*', '', subject)
    tokens = set()
    for w in re.findall(r'[A-Za-z]{2,}', body.lower()):
        if w not in _SUBJECT_STOPWORDS:
            tokens.add(w)
    return tokens


def _url_slug_tokens(url: str) -> set[str]:
    """SA news URL slug의 토큰 집합. `/news/4595536-airbnb-ceo-brian-chesky-aims...` → {airbnb, ceo, brian, ...}"""
    m = re.search(r'/news/\d+[-_]([\w\-]+?)(?:\?|$)', url.lower())
    if not m:
        return set()
    return set(t for t in re.split(r'[-_]', m.group(1)) if t and len(t) >= 2)


def extract_urls(email_id: int, subject: str = '') -> dict:
    """Extract article URLs from a single SA email.

    Args:
      email_id: himalaya envelope UID (INBOX)
      subject: envelope subject — main_url ticker 검증용 (선택)

    Returns dict:
      - main_url: 메인 기사 URL (envelope subject ticker와 일치 우선)
      - all_urls: 발견된 모든 SA news URL 집합
      - has_main: 메인 기사 발견 여부
      - subject_ticker: subject prefix에서 추출된 ticker (디버깅용, None 가능)
      - subject_mismatch: subject ticker는 있었지만 매칭 URL을 못 찾은 경우 True
    """
    result = subprocess.run(
        [HIMALAYA, 'message', 'read', str(email_id)],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()[-500:]
        raise RuntimeError(
            f"himalaya message read failed for {email_id} "
            f"(rc={result.returncode}): {detail}"
        )
    content = result.stdout

    # 두 가지 source에서 b64 후보를 모두 모음:
    # (1) click URL의 path segment — `email-st.seekingalpha.com/click/.../<b64>/...`
    #     단 경로 separator(`/`) 만나면 잘림 → 디코드 결과가 짧을 수 있음
    # (2) 본문 전역의 'aHR0'로 시작하는 base64 토큰 — 패딩 변형으로 더 긴 b64를 잡을 수 있음
    # 574번 메일 사례: click URL b64만 사용할 경우 메인 기사 URL이 누락됨.
    b64_candidates = set()
    for m in re.finditer(r'https://email-st\.seekingalpha\.com/click/\d+\.\d+/([^/\s]+)', content):
        b64_candidates.add(m.group(1))
    for m in re.finditer(r'aHR0[A-Za-z0-9+/=]{20,}', content):
        b64_candidates.add(m.group(0))

    article_urls = {}  # url -> priority (lower = higher priority)
    for b64 in b64_candidates:
        decoded = decode_b64(b64)
        if not decoded:
            continue
        ref_match = re.search(
            r'ref=(https://seekingalpha\.com/news/\d+[A-Za-z0-9\-_./?=%~]*)', decoded
        )
        url_match = re.search(
            r'(https://seekingalpha\.com/news/\d+[A-Za-z0-9\-_./?=%~]*)', decoded
        )
        if ref_match:
            url = strip_utm(ref_match.group(1))
        elif url_match:
            url = strip_utm(url_match.group(1))
        else:
            continue
        # Priority: main_0_title=0, main_0_textlink=1, no-rc_=2
        if 'main_0_title' in decoded:
            priority = 0
        elif 'main_0_textlink' in decoded:
            priority = 1
        else:
            priority = 2
        if url not in article_urls or priority < article_urls[url]:
            article_urls[url] = priority

    sorted_urls = sorted(article_urls.items(), key=lambda x: x[1])

    # envelope subject 토큰과 URL slug 토큰의 겹침으로 메인 기사 선정.
    # ticker 약자 매칭은 false-negative 발생 (ABNB vs airbnb, ADI vs analog-devices).
    # 회사명 풀네임 기반 SA URL slug 특성상 본문 토큰 매칭이 더 견고함 (574번 사례).
    subj_tokens = _subject_tokens(subject)
    subject_mismatch = False
    best_url = None
    best_score = 0
    if subj_tokens:
        for url, _prio in sorted_urls:
            score = len(subj_tokens & _url_slug_tokens(url))
            # priority도 tie-breaker로 활용: score 동률이면 priority 낮은(즉 main_0_title 우선) URL
            if score > best_score or (score > 0 and score == best_score and best_url is None):
                best_score = score
                best_url = url
        if best_url and best_score >= 2:  # 토큰 2개 이상 일치하면 신뢰
            main_url = best_url
        else:
            main_url = None
            if subj_tokens:  # subject는 있었지만 의미 있는 매칭을 못 찾음
                subject_mismatch = True
    else:
        main_url = None

    # subject 매칭 실패 시 기존 priority 기반 fallback
    if main_url is None:
        for url, priority in sorted_urls:
            if priority <= 1:
                main_url = url
                break
    if main_url is None:
        for url, _prio in sorted_urls:
            if 'rc_' not in url:
                main_url = url
                break

    return {
        'main_url': main_url,
        'all_urls': set(article_urls.keys()),
        'has_main': main_url is not None,
        'subject_match_score': best_score,
        'subject_mismatch': subject_mismatch,
    }



BATCH_SIZE = int(os.environ.get('SA_BATCH_SIZE', '10'))  # 한 사이클 처리 한도. 환경변수로 override 가능.


def main():
    # Step 1: Get unread SA emails (plain text, reliable)
    unread_sa_emails, true_total = get_unread_sa_emails()

    if not unread_sa_emails:
        print("NO_UNREAD_SA_EMAILS")
        return

    batch = unread_sa_emails[:BATCH_SIZE]
    ids = [e['id'] for e in batch]

    if true_total > BATCH_SIZE:
        print(f"FOUND_UNREAD: {len(batch)} emails (of {true_total} unread total, oldest first): {ids}")
    else:
        print(f"FOUND_UNREAD: {len(batch)} emails: {ids}")

    # Step 2: Extract URLs from each
    # 출력 형식: EMAIL_ID<TAB>EMAIL_TIME_KST<TAB>ORIGINAL_TITLE<TAB>ARTICLE_URL
    for email in batch:
        eid = email['id']
        email_time_kst = email['email_time_kst']
        # Subject can contain tab (extremely rare in SA mails) — replace just in case
        title = email['subject'].replace('\t', ' ').replace('\n', ' ')
        try:
            info = extract_urls(eid, subject=title)
            if info['main_url']:
                # envelope subject 토큰과 메인 URL slug의 겹침이 부족해 fallback을 쓴 경우
                # → stderr 경고. 다운스트림에서 ticker/주제 mismatch 가능성 인지하라는 신호.
                if info.get('subject_mismatch'):
                    print(
                        f"WARN: eid={eid} subject tokens did not match any candidate URL "
                        f"(best_score={info.get('subject_match_score', 0)}) — priority fallback used. "
                        f"Verify before insert.",
                        file=sys.stderr,
                    )
                print(f"{eid}\t{email_time_kst}\t{title}\t{info['main_url']}")
            else:
                print(f"{eid}\t{email_time_kst}\t{title}\tNO_MAIN_ARTICLE (found {len(info['all_urls'])} related links)")
        except Exception as e:
            print(f"{eid}\t{email_time_kst}\t{title}\tERROR - {e}")


if __name__ == '__main__':
    main()

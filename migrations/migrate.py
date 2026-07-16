"""Import legacy static HTML dashboard cards into the current SQLite schema."""

import argparse
import json
import sys
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import db  # noqa: E402

DEFAULT_REPORTS_DIR = Path.home() / "Documents" / "reports"

def parse_created_at(filename):
    """파일명에서 KST 시각 추출: sa_dashboard_YYYYMMDD_HHMM.html"""
    m = re.search(r'sa_dashboard_(\d{8})_(\d{4})\.html', filename)
    if not m:
        return None
    date_str, time_str = m.group(1), m.group(2)
    created_at = datetime(
        int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]),
        int(time_str[:2]), int(time_str[2:4]),
        tzinfo=ZoneInfo("Asia/Seoul"),
    )
    return created_at.strftime("%Y-%m-%d %H:%M KST")

def parse_cards(html):
    """HTML에서 카드 데이터 파싱"""
    cards = []
    # div depth를 추적해 각 card 블록 전체를 추출한다.
    raw_cards = []
    pos = 0
    while True:
        start = html.find('<div class="card">', pos)
        if start == -1:
            break
        depth = 1
        i = start + len('<div class="card">')
        while i < len(html) and depth > 0:
            if html[i:i+4] == '<div':
                depth += 1
                i += 4
            elif html[i:i+6] == '</div>':
                depth -= 1
                i += 6
            else:
                i += 1
        raw_cards.append(html[start:i])
        pos = i

    for card_html in raw_cards:
        card = {}

        # ticker
        m = re.search(r'class="ticker-badge ticker-(\w+)">([^<]+)<', card_html)
        if m:
            card['ticker_color'] = m.group(1)
            card['ticker'] = m.group(2).strip()
        else:
            card['ticker'] = 'N/A'
            card['ticker_color'] = 'gray'

        # company_name
        m = re.search(r'class="card-source">([^<]+)<', card_html)
        card['company_name'] = m.group(1).strip() if m else ''

        # email_time_et
        m = re.search(r'class="card-time">([^<]+)<', card_html)
        card['email_time_et'] = m.group(1).strip() if m else ''

        # headline (h2.card-title)
        m = re.search(r'<h2[^>]*class="card-title"[^>]*>([^<]+)</h2>', card_html)
        if not m:
            m = re.search(r'class="card-title">([^<]+)<', card_html)
        card['headline'] = m.group(1).strip() if m else ''

        # tag
        m = re.search(r'class="tag tag-(\w+)">([^<]+)<', card_html)
        if m:
            card['tag_color'] = m.group(1)
            card['tag'] = m.group(2).strip()
        else:
            card['tag'] = '일반'
            card['tag_color'] = 'blue'

        # summary_core (핵심 텍스트 — <strong>핵심</strong>&nbsp; 이후)
        m = re.search(r'<strong>핵심</strong>&nbsp;\s*(.+?)(?=</div>|<div)', card_html, re.DOTALL)
        if m:
            core = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            card['summary_core'] = core
        else:
            card['summary_core'] = ''

        # summary_details (li 항목들)
        details = re.findall(r'<li>([^<]+)</li>', card_html)
        card['summary_details'] = [d.strip() for d in details if d.strip()]

        # article_url
        m = re.search(r'class="card-link"[^>]*>.*?href="([^"]+)"', card_html, re.DOTALL)
        if not m:
            m = re.search(r'href="(https://seekingalpha\.com/[^"]+)"', card_html)
        card['article_url'] = m.group(1) if m else ''

        if card.get('headline') and card.get('article_url'):
            cards.append(card)

    return cards


def migrate(reports_dir: Path = DEFAULT_REPORTS_DIR):
    db.init_db()
    files = sorted(reports_dir.rglob("sa_dashboard_*.html"))

    print(f"총 {len(files)}개 파일 마이그레이션 시작...")
    total_inserted = 0
    total_skipped = 0

    for path in files:
        created_at = parse_created_at(path.name)
        if not created_at:
            print(f"  SKIP (파일명 파싱 실패): {path}")
            continue

        html = path.read_text(encoding="utf-8")

        cards = parse_cards(html)
        inserted = 0
        for i, card in enumerate(cards):
            # email_id 대신 파일명+인덱스로 중복 방지
            pseudo_email_id = f"migrate:{path.name}:{i}"
            with db.get_conn() as conn:
                try:
                    cursor = conn.execute(
                        """INSERT INTO articles
                           (email_id, ticker, company_name, headline,
                            summary_core, summary_details, tag, tag_color,
                            ticker_color, article_url, email_time_et, last_modified,
                            pub_status, retry_count, is_read)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'published', 0, 1)""",
                        (
                            pseudo_email_id, card['ticker'],
                            card['company_name'], card['headline'],
                            card['summary_core'],
                            json.dumps(card['summary_details'], ensure_ascii=False),
                            card['tag'], card['tag_color'],
                            card['ticker_color'], card['article_url'],
                            card['email_time_et'] or created_at, created_at,
                        )
                    )
                    inserted += cursor.rowcount
                except sqlite3.IntegrityError:
                    pass  # 중복

        total_inserted += inserted
        total_skipped += len(cards) - inserted
        print(f"  {path.name}: {len(cards)}개 카드 → {inserted}건 삽입")

    print(f"\n완료: {total_inserted}건 삽입, {total_skipped}건 중복 스킵")

def main() -> None:
    parser = argparse.ArgumentParser(description="legacy HTML → current SQLite")
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    args = parser.parse_args()
    migrate(args.reports_dir)


if __name__ == "__main__":
    main()

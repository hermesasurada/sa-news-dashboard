"""
기존 HTML 대시보드 파일 → SQLite DB 마이그레이션
"""
import sys
import re
import glob
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

db.init_db()

REPORTS_DIR = Path.home() / "Documents" / "reports"

def parse_created_at(filename):
    """파일명에서 KST 시각 추출: sa_dashboard_YYYYMMDD_HHMM.html"""
    m = re.search(r'sa_dashboard_(\d{8})_(\d{4})\.html', filename)
    if not m:
        return None
    date_str, time_str = m.group(1), m.group(2)
    dt = datetime(
        int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]),
        int(time_str[:2]), int(time_str[2:4]),
        tzinfo=timezone(timedelta(hours=9))
    )
    return dt.isoformat()

def parse_cards(html):
    """HTML에서 카드 데이터 파싱"""
    cards = []
    # 각 카드 블록 추출
    card_blocks = re.findall(r'<div class="card">(.*?)</div>\s*</div>\s*(?=<div class="card">|$)', html, re.DOTALL)
    if not card_blocks:
        # 마지막 카드 포함 패턴
        card_blocks = re.findall(r'<div class="card">(.*?)</div>\s*\n?\s*</div>', html, re.DOTALL)

    # 더 robust한 방식: card div 전체를 추출
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


def migrate():
    files = sorted(glob.glob(str(REPORTS_DIR / "**" / "sa_dashboard_*.html"), recursive=True))
    # 루트 레벨도 포함
    files += sorted(glob.glob(str(REPORTS_DIR / "sa_dashboard_*.html")))
    files = sorted(set(files))

    print(f"총 {len(files)}개 파일 마이그레이션 시작...")
    total_inserted = 0
    total_skipped = 0

    for fpath in files:
        created_at = parse_created_at(os.path.basename(fpath))
        if not created_at:
            print(f"  SKIP (파일명 파싱 실패): {fpath}")
            continue

        with open(fpath, encoding='utf-8') as f:
            html = f.read()

        cards = parse_cards(html)
        inserted = 0
        for i, card in enumerate(cards):
            # email_id 대신 파일명+인덱스로 중복 방지
            pseudo_email_id = f"migrate:{os.path.basename(fpath)}:{i}"
            # created_at을 파일 시각 기준으로 직접 주입
            with db.get_conn() as conn:
                import json, sqlite3
                try:
                    conn.execute(
                        """INSERT INTO articles
                           (ticker, ticker_color, company_name, headline,
                            summary_core, summary_details, tag, tag_color,
                            article_url, email_time_et, email_id, created_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            card['ticker'], card['ticker_color'],
                            card['company_name'], card['headline'],
                            card['summary_core'],
                            json.dumps(card['summary_details'], ensure_ascii=False),
                            card['tag'], card['tag_color'],
                            card['article_url'], card['email_time_et'],
                            pseudo_email_id, created_at,
                        )
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass  # 중복

        total_inserted += inserted
        total_skipped += len(cards) - inserted
        print(f"  {os.path.basename(fpath)}: {len(cards)}개 카드 → {inserted}건 삽입")

    print(f"\n완료: {total_inserted}건 삽입, {total_skipped}건 중복 스킵")

if __name__ == "__main__":
    migrate()

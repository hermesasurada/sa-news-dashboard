#!/usr/bin/env python3
"""
Telegram FEED 파일들을 DB에 마이그레이션하는 스크립트
"""
import re
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import sqlite3

DB_PATH = Path(__file__).parent / "sa_news.db"
TELEGRAM_ROOT = Path("/Users/yhandhs/Documents/Asurada/Telegram")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def parse_feed_file(feed_path: Path):
    """FEED-YYYYMMDD.md 파일 파싱"""
    content = feed_path.read_text(encoding="utf-8")
    
    # feed_date 추출 (파일명에서)
    match = re.search(r"FEED-(\d{8})", feed_path.name)
    if not match:
        return []
    
    ymd = match.group(1)
    feed_date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
    
    results = []
    
    # bullet 라인 파싱 (- 로 시작하는 라인)
    lines = content.splitlines()
    for line in lines:
        line = line.strip()
        if not line.startswith("- "):
            continue
        
        # [[원문]] 링크에서 original_path 추출
        link_match = re.search(r'\[\[([^\]]+)\|원문\]\]', line)
        if not link_match:
            continue
        
        original_path = link_match.group(1)
        
        # 제목과 태그 분리
        # 예: - JP모건 TMT WD — ... #WD #HDD [[...|원문]]
        text_part = re.sub(r'\[\[[^\]]+\|원문\]\]', '', line).strip()
        text_part = text_part[2:] if text_part.startswith("- ") else text_part  # "- " 제거
        
        # 태그 추출 (#으로 시작하는 것들)
        tags = re.findall(r'#\S+', text_part)
        clean_text = re.sub(r'#\S+', '', text_part).strip()
        
        # summary는 제목 전체로 사용 (간단하게)
        title = clean_text.split("—")[0].strip() if "—" in clean_text else clean_text[:80]
        summary = clean_text
        
        results.append({
            "feed_date": feed_date,
            "title": title,
            "summary": summary,
            "tags": json.dumps(tags, ensure_ascii=False),
            "original_path": original_path
        })
    
    return results

def migrate():
    conn = get_conn()
    
    # 기존 데이터 삭제 (재실행 시)
    conn.execute("DELETE FROM telegram_feeds")
    
    # 모든 FEED 파일 찾기
    feed_files = list(TELEGRAM_ROOT.glob("*/FEED-*.md"))
    print(f"Found {len(feed_files)} FEED files")
    
    inserted = 0
    for feed_file in sorted(feed_files):
        items = parse_feed_file(feed_file)
        for item in items:
            now_kst = datetime.now(timezone(timedelta(hours=9))).isoformat()
            try:
                conn.execute("""
                    INSERT INTO telegram_feeds 
                    (feed_date, title, summary, tags, original_path, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    item["feed_date"],
                    item["title"],
                    item["summary"],
                    item["tags"],
                    item["original_path"],
                    now_kst
                ))
                inserted += 1
            except Exception as e:
                print(f"Insert error: {e}")
    
    conn.commit()
    conn.close()
    print(f"Migration completed. Inserted {inserted} items.")

if __name__ == "__main__":
    migrate()
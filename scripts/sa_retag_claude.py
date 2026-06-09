#!/usr/bin/env python3
"""SA news — 안읽은 기사의 ticker/company_name을 Claude로 재추출하여 DB 업데이트.

요약 텍스트(summary_core + summary_details)에 언급된 모든 기업의
티커 심볼과 영문 기업명을 Claude CLI로 추출하여 기존 저장값을 대체한다.

사용법:
  python3 sa_retag_claude.py            # 안읽은 published 기사 전체
  python3 sa_retag_claude.py --id 42    # 특정 article_id (읽음 여부 무관)
  python3 sa_retag_claude.py --dry-run  # DB 변경 없이 결과만 출력
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))
import db  # noqa: E402
from sa_claude_cli import call_claude, extract_json  # noqa: E402

_PROMPT_TMPL = """\
다음은 한국어 금융 뉴스 요약 텍스트입니다.
이 텍스트에 명시적으로 언급된 기업들의 주식 티커 심볼과 정식 영문 기업명을 모두 추출하세요.

규칙:
- 텍스트에 직접 언급된 기업만 포함 (추론·기억 기반 추가 금지)
- 티커를 확신할 수 없는 기업은 제외
- 기업명은 정식 영문 원어 표기 (음차·한국어 번역 금지)
  예: 엔비디아→Nvidia, 애플→Apple, 아마존→Amazon
- 주식 티커가 없는 기관(연준, ECB, 규제당국 등)은 제외
- 본문 맥락상 가장 주요한 기업을 첫 번째로
- 중복 제거

출력은 JSON만 (코드블럭·설명 금지):
{{"companies": [{{"ticker": "NVDA", "name": "Nvidia"}}, ...]}}

=== 텍스트 ===
{text}
"""


def build_text(row: dict) -> str:
    parts = [row.get("summary_core") or ""]
    try:
        details = json.loads(row.get("summary_details") or "[]")
        if isinstance(details, list):
            parts.extend(details)
    except (json.JSONDecodeError, TypeError):
        pass
    return "\n".join(p for p in parts if p)


def process(row: dict, dry_run: bool) -> bool:
    article_id = row["id"]
    print(f"  [{article_id}] 현재: ticker={row['ticker']} | company={row['company_name']}")

    text = build_text(row)
    if not text:
        print(f"     요약 텍스트 없음 — 스킵")
        return False

    prompt = _PROMPT_TMPL.format(text=text[:3000])
    response = call_claude(prompt)
    if not response:
        print(f"     Claude 응답 없음 — 스킵", file=sys.stderr)
        return False

    data = extract_json(response)
    if not data or not data.get("companies"):
        print(f"     추출 결과 없음 (raw: {response[:100]}) — 스킵", file=sys.stderr)
        return False

    companies = [
        c for c in data["companies"]
        if c.get("ticker") and re.match(r"^[A-Z0-9.]{1,6}$", c["ticker"])
    ]
    if not companies:
        print(f"     유효한 티커 없음 — 스킵")
        return False

    new_ticker = ", ".join(c["ticker"] for c in companies)
    new_company = "·".join(c["name"] for c in companies if c.get("name"))
    # 동일 종목(GOOGL=GOOG 등) 티커 병합
    new_ticker, new_company = db.canonicalize_tickers(new_ticker, new_company)

    print(f"     → ticker: {new_ticker}")
    print(f"     → company: {new_company}")

    if not dry_run:
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE articles SET ticker = ?, company_name = ? WHERE id = ?",
                (new_ticker, new_company, article_id),
            )
    return True


def get_unread_articles() -> list[dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT id, ticker, company_name, summary_core, summary_details
               FROM articles
               WHERE is_read = 0 AND pub_status = 'published'
               ORDER BY CAST(email_id AS INTEGER) DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_article_by_id(article_id: int) -> dict | None:
    with db.get_conn() as conn:
        r = conn.execute(
            """SELECT id, ticker, company_name, summary_core, summary_details
               FROM articles WHERE id = ? AND pub_status = 'published'""",
            (article_id,),
        ).fetchone()
    return dict(r) if r else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--id", type=int, dest="article_id")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.dry_run:
        print("[DRY-RUN] DB 변경 없이 추출 결과만 출력합니다.")

    if args.article_id:
        row = get_article_by_id(args.article_id)
        if not row:
            print(f"article_id {args.article_id} 없음", file=sys.stderr)
            sys.exit(1)
        process(row, args.dry_run)
    else:
        rows = get_unread_articles()
        if not rows:
            print("안읽은 published 기사 없음")
            return
        print(f"안읽은 기사 {len(rows)}건 재태깅 시작\n")
        ok = skip = 0
        for row in rows:
            if process(row, args.dry_run):
                ok += 1
            else:
                skip += 1
            print()
        print(f"완료 — 업데이트 {ok}건 / 스킵 {skip}건")


if __name__ == "__main__":
    main()

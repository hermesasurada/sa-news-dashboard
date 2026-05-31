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

sys.path.insert(0, "/Users/yhandhs/Documents/sa-dashboard")
import db  # noqa: E402


def _version_key(path: Path):
    for part in path.parts:
        if re.fullmatch(r"\d+(?:\.\d+)+", part):
            return tuple(int(x) for x in part.split("."))
    return ()


def resolve_claude_bin() -> str:
    """Resolve Claude CLI path without pinning a versioned app bundle."""
    env_bin = os.environ.get("CLAUDE_BIN") or os.environ.get("CLAUDE_CODE_BIN")
    if env_bin:
        return str(Path(env_bin).expanduser())

    app_support = Path.home() / "Library/Application Support/Claude"
    candidates = [
        *app_support.glob("claude-code/*/claude.app/Contents/MacOS/claude"),
        *app_support.glob("claude-code-vm/*/claude"),
    ]
    candidates = [p for p in candidates if p.is_file()]
    if candidates:
        return str(max(candidates, key=lambda p: (_version_key(p), "claude.app" in str(p))))

    return "claude"


CLAUDE_BIN = resolve_claude_bin()
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "sonnet")

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


def call_claude(prompt: str) -> str | None:
    try:
        proc = subprocess.Popen(
            [CLAUDE_BIN, "--output-format", "stream-json", "--verbose",
             "--model", CLAUDE_MODEL, "-p", prompt],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
        )
        result_text = None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "result" and ev.get("subtype") == "success":
                result_text = ev.get("result", "")
            elif ev.get("type") == "assistant" and result_text is None:
                for blk in ev.get("message", {}).get("content", []):
                    if blk.get("type") == "text":
                        result_text = blk.get("text", "")
        proc.wait(timeout=60)
        if proc.returncode != 0:
            err = proc.stderr.read(200)
            print(f"     Claude CLI 오류: {err}", file=sys.stderr)
            return None
        return (result_text or "").strip() or None
    except Exception as e:
        print(f"     Claude CLI 실패: {e}", file=sys.stderr)
        return None


def extract_json(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m2 = re.search(r"\{[\s\S]*\}", text)
    if m2:
        try:
            return json.loads(m2.group())
        except json.JSONDecodeError:
            pass
    return None


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

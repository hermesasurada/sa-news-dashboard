#!/usr/bin/env python3
"""SA news monitor — Stage 2 (Publish) driven by Claude CLI.

sa_publish.py list/parse 결과를 받아 Claude CLI로 한국어 요약을 생성하고
db.publish_article() 또는 db.mark_attempt_failed()를 호출한다.

사용법:
  python3 sa_summarize_claude.py            # pending 최대 10건 일괄 처리
  python3 sa_summarize_claude.py --batch 5  # 5건
  python3 sa_summarize_claude.py --id 42    # 특정 article_id만 강제 처리
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
sys.path.insert(0, "/Users/yhandhs/Documents/sa-dashboard")

import db  # noqa: E402

def _version_key(path: Path) -> tuple[int, ...]:
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

# ── 프롬프트 ──────────────────────────────────────────────────────────────
_PROMPT_TMPL = """\
다음은 Seeking Alpha 기사 원문입니다.
아래 JSON 형식으로만 응답하세요. JSON 외의 텍스트·설명·마크다운 코드블럭은 절대 출력하지 마세요.

출력 형식 (한 줄, key 순서 고정):
{{"ticker":"AAPL, MSFT","company_name":"Apple·Microsoft","headline":"한국어제목","summary_details":["포인트1","포인트2","포인트3","포인트4"],"ticker_color":"blue"}}

규칙:
- ticker: 기사에 명시적으로 언급된 기업들의 거래소 티커 심볼. 쉼표+공백으로 구분 (예: "NVDA, AMD").
  기사 맥락상 가장 주요한 기업을 첫 번째로. 티커를 확신할 수 없거나 상장사가 아닌
  기관(연준·ECB·규제당국 등)은 제외. 기사에 티커 없으면 빈 문자열 "".
- company_name: ticker 순서와 동일하게 정식 영문 기업명을 · 로 연결 (예: "Nvidia·AMD").
  한국어 번역·음차 절대 금지. 티커 기호(AAPL 등) 포함 금지.
- headline: 티커 prefix 금지. 구체적이고 정보량 있는 한국어 제목. 핵심 수치·방향·이벤트 포함.
  예) 'TSLA: 테슬라 가격 인상' ✗ → 'Tesla, 2년 만에 첫 모델 Y 가격 인상' ✓
- summary_details: 4~6개 배열. 각 항목 완결 문장. '분석가 X는 Y라고 전망했다' 형식 선호.
  분석가 이름·목표주가·수치·날짜 등 핵심 정보를 반드시 포함.
- ticker_color: blue|green|red|orange|yellow|purple|gray 중 1개.
  상승·긍정=green, 하락·부정=red, 중립·기타=blue
- 외국 기업·인명·약품명 = 영문 원어 유지. 한국 기업만 한국어 유지.
  음차 금지 예: 앤티로픽→Anthropic, 파란티어→Palantir, 애플→Apple, 테슬라→Tesla, 엔비디아→Nvidia
- 한자·가나 절대 금지. 売上→매출, 格上げ→상향 등으로 순 한국어 교체.

=== 기사 원문 ===
{content}
"""


# ── Claude CLI 호출 ────────────────────────────────────────────────────────

def call_claude(prompt: str, timeout: int = 120) -> str | None:
    """Claude CLI를 호출하고 최종 텍스트 응답을 반환. 실패 시 None."""
    try:
        proc = subprocess.Popen(
            [
                CLAUDE_BIN,
                "--output-format", "stream-json",
                "--verbose",
                "--model", CLAUDE_MODEL,
                "-p", prompt,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
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
            ev_type = ev.get("type")
            # result 이벤트 — 최종 응답 텍스트
            if ev_type == "result" and ev.get("subtype") == "success":
                result_text = ev.get("result", "")
            # assistant 이벤트 — result 없을 때 fallback
            elif ev_type == "assistant" and result_text is None:
                for blk in ev.get("message", {}).get("content", []):
                    if blk.get("type") == "text":
                        result_text = blk.get("text", "")

        proc.wait(timeout=timeout)
        if proc.returncode != 0:
            err = proc.stderr.read(300)
            print(f"     Claude CLI 오류 (rc={proc.returncode}): {err}", file=sys.stderr)
            return None
        return (result_text or "").strip() or None

    except subprocess.TimeoutExpired:
        proc.kill()
        print("     Claude CLI 타임아웃", file=sys.stderr)
        return None
    except Exception as e:
        print(f"     Claude CLI 호출 실패: {e}", file=sys.stderr)
        return None


# ── JSON 추출 ──────────────────────────────────────────────────────────────

def extract_json(text: str) -> dict | None:
    """Claude 응답에서 JSON 객체 추출."""
    text = text.strip()
    # 마크다운 코드블럭 제거
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    # 직접 파싱 시도
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # { ... } 블럭 추출
    m2 = re.search(r"\{[\s\S]*\}", text)
    if m2:
        try:
            return json.loads(m2.group())
        except json.JSONDecodeError:
            pass
    return None


_VALID_COLORS = {"blue", "green", "red", "orange", "yellow", "purple", "gray"}


def validate(d: dict) -> dict:
    """필드 타입 보정 및 기본값 설정."""
    # ticker: 쉼표 구분된 심볼 목록, 각각 ^[A-Z0-9.]{1,6}$ 검증
    raw_tickers = str(d.get("ticker") or "").strip()
    valid_tickers = [
        t.strip() for t in raw_tickers.split(",")
        if re.match(r"^[A-Z0-9.]{1,6}$", t.strip())
    ]
    d["ticker"] = ", ".join(valid_tickers)
    d["company_name"] = str(d.get("company_name") or "").strip()
    d["headline"] = str(d.get("headline") or "").strip()
    # summary_core / tag 는 더 이상 생성하지 않음 — 빈 값으로 고정
    d["summary_core"] = ""
    details = d.get("summary_details") or []
    if not isinstance(details, list):
        details = [str(details)]
    d["summary_details"] = [str(x).strip() for x in details if str(x).strip()][:6]
    d["tag"] = ""
    tc = str(d.get("ticker_color") or "blue").lower()
    d["ticker_color"] = tc if tc in _VALID_COLORS else "blue"
    d["tag_color"] = "blue"
    return d


# ── SA 파싱 ────────────────────────────────────────────────────────────────

def parse_article(article_id: int) -> tuple[str | None, str | None]:
    """sa_publish.py parse 호출 → (본문, None) 또는 (None, 오류사유)."""
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "sa_publish.py"), "parse", str(article_id)],
            capture_output=True, text=True, timeout=90,
        )
        if result.returncode != 0:
            reason = result.stderr.strip() or f"parse exit {result.returncode}"
            return None, reason
        content = result.stdout.strip()
        if not content:
            return None, "parse returned empty content"
        return content, None
    except subprocess.TimeoutExpired:
        return None, "parse timeout"
    except Exception as e:
        return None, str(e)


# ── 단일 기사 처리 ─────────────────────────────────────────────────────────

def process_article(row: dict) -> bool:
    """기사 1건 처리. 성공 True / 실패 False."""
    article_id = row["id"]
    ticker = row.get("ticker", "")
    orig = (row.get("original_title") or "")[:60]
    print(f"  [{article_id}] {ticker} | {orig}")

    # 1. SA 페이지 파싱
    content, parse_err = parse_article(article_id)
    if not content:
        reason = parse_err or "PARSE_FAIL"
        print(f"     파싱 실패: {reason}", file=sys.stderr)
        res = db.mark_attempt_failed(article_id, reason[:200])
        print(f"     → {res}")
        return False

    # 2. Claude로 한국어 요약 생성
    prompt = _PROMPT_TMPL.format(content=content[:10000])
    print(f"     Claude 요약 중…", end="", flush=True)
    response = call_claude(prompt)
    if not response:
        reason = "Claude CLI 응답 없음"
        print(f"\n     {reason}", file=sys.stderr)
        db.mark_attempt_failed(article_id, reason)
        return False
    print(" 완료")

    # 3. JSON 추출 및 검증
    data = extract_json(response)
    if not data:
        reason = f"JSON 파싱 실패: {response[:120]}"
        print(f"     {reason}", file=sys.stderr)
        db.mark_attempt_failed(article_id, reason[:200])
        return False

    data = validate(data)
    if not data["headline"] or not data["summary_details"]:
        reason = f"필수 필드 누락: headline={bool(data['headline'])} summary_details={bool(data['summary_details'])}"
        print(f"     {reason}", file=sys.stderr)
        db.mark_attempt_failed(article_id, reason[:200])
        return False

    # 4. DB 발행 (ticker가 추출됐으면 교체, 없으면 Stage 1 값 유지)
    new_ticker = data.get("ticker") or ""
    ok = db.publish_article(
        article_id,
        ticker=new_ticker if new_ticker else None,
        company_name=data["company_name"],
        headline=data["headline"],
        summary_core=data["summary_core"],
        summary_details=data["summary_details"],
        tag=data["tag"],
        ticker_color=data["ticker_color"],
        tag_color=data["tag_color"],
    )
    if ok:
        print(f"     ✓ published: {data['headline'][:70]}")
    else:
        print(f"     publish 실패 (이미 삭제된 행?)", file=sys.stderr)
    return ok


# ── 배치 실행 ──────────────────────────────────────────────────────────────

def run_batch(batch_size: int) -> None:
    rows = db.get_pending_due(batch_size=batch_size)
    if not rows:
        print("SA summarize (claude): pending 없음")
        return
    print(f"SA summarize (claude): {len(rows)}건 처리 시작")
    ok = fail = 0
    for row in rows:
        if process_article(row):
            ok += 1
        else:
            fail += 1
    print(f"SA summarize (claude): 완료 — 성공 {ok}건 / 실패 {fail}건")


def main() -> None:
    p = argparse.ArgumentParser(description="SA Stage 2 — Claude CLI 요약")
    p.add_argument("--batch", type=int, default=10, help="일괄 처리 건수 (기본 10)")
    p.add_argument("--id", type=int, dest="article_id", help="특정 article_id 강제 처리")
    args = p.parse_args()

    if args.article_id:
        # due 조건 무시하고 직접 조회
        with db.get_conn() as conn:
            r = conn.execute(
                "SELECT id, ticker, original_title, article_url, retry_count "
                "FROM articles WHERE id = ? AND pub_status != 'deleted'",
                (args.article_id,),
            ).fetchone()
        if not r:
            print(f"article_id {args.article_id} 없음 또는 삭제됨", file=sys.stderr)
            sys.exit(1)
        process_article(dict(r))
    else:
        run_batch(args.batch)


if __name__ == "__main__":
    main()

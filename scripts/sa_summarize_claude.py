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
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT))

import db  # noqa: E402
from sa_claude_cli import call_claude, call_grok, extract_json  # noqa: E402
from sa_lock import single_instance  # noqa: E402

# ── 프롬프트 ──────────────────────────────────────────────────────────────
_PROMPT_TMPL = """\
다음은 Seeking Alpha 기사 원문입니다.
아래 JSON 형식으로만 응답하세요. JSON 외의 텍스트·설명·마크다운 코드블럭은 절대 출력하지 마세요.

출력 형식 (한 줄, key 순서 고정):
{{"ticker":"AVGO, NVDA, GOOG, META","company_name":"Broadcom·Nvidia·Alphabet·Meta Platforms","headline":"한국어제목","summary_details":["포인트1","포인트2","포인트3","포인트4"],"ticker_color":"blue"}}

규칙:
- ticker: 기사 이벤트에 **실질적으로 관련된 상장 기업만** 추출해 거래소 티커 심볼로.
  쉼표+공백으로 구분 (예: "AVGO, NVDA"). 기사 맥락상 가장 주요한 기업을 첫 번째로.
  판단 기준: **"이 기사가 그 기업 주가에 의미 있는 정보인가?"** — 그렇다면 포함, 아니면 제외.
  포함: 기사 주제의 당사자, 그리고 해당 이벤트로 실질적 영향을 받는 기업
     (계약·수주 상대방, 인수·피인수 대상, 소송 상대, 실적에 직접 영향을 받는 고객·공급사 등).
     당사자가 여럿이면 모두 포함 — 실질 관련 기업을 1개로 줄이지 말 것.
  제외: 단순 비교·예시·나열로만 스치는 기업, 배경 설명 속 언급, 지수·업종 구성원 나열,
     과거 이력 언급 등 이번 이벤트와 무관한 등장.
     (예: Broadcom 수주 기사에 "경쟁사로는 Nvidia가 있다" 식 언급만 있으면 NVDA 제외)
  또한 제외: 티커를 확신할 수 없는 경우, 비상장 기업(OpenAI·Anthropic 등),
     상장사 아닌 기관(연준·ECB·규제당국 등), 본문에 등장하지 않는 종목.
  기사에 해당 기업이 없으면 빈 문자열 "".
- company_name: ticker 순서·개수와 **정확히 동일하게** 정식 영문 기업명을 · 로 연결 (예: "Nvidia·AMD").
  ticker를 N개 넣었으면 company_name도 N개. 한국어 번역·음차 절대 금지. 티커 기호(AAPL 등) 포함 금지.
- headline: 티커 prefix 금지. 구체적이고 정보량 있는 한국어 제목. 핵심 수치·방향·이벤트 포함.
  예) 'TSLA: 테슬라 가격 인상' ✗ → 'Tesla, 2년 만에 첫 모델 Y 가격 인상' ✓
- summary_details: 4~6개 배열. 각 항목 완결 문장. '분석가 X는 Y라고 전망했다' 형식 선호.
  분석가 이름·목표주가·수치·날짜 등 핵심 정보를 반드시 포함.
  단, 페이월(paywall)·구독·로그인·본문 접근 제한·내용 잘림 등으로 인한 정보 누락은
  절대 언급하지 말 것. (예: '페이월로 상세 내용 확인 불가', '구독 필요' 같은 문장 금지)
  접근 가능한 원문 범위 내에서만 요약하고, 누락 자체를 기술하지 않는다.
- ticker_color: blue|green|red|orange|yellow|purple|gray 중 1개.
  상승·긍정=green, 하락·부정=red, 중립·기타=blue
- 외국 기업·인명·약품명 = 영문 원어 유지. 한국 기업만 한국어 유지.
  음차 금지 예: 앤티로픽→Anthropic, 파란티어→Palantir, 애플→Apple, 테슬라→Tesla, 엔비디아→Nvidia
- 한자·가나 절대 금지. 売上→매출, 格上げ→상향 등으로 순 한국어 교체.{candidates}

=== 기사 원문 ===
{content}
"""


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
    details = d.get("summary_details") or []
    if not isinstance(details, list):
        details = [str(details)]
    d["summary_details"] = [str(x).strip() for x in details if str(x).strip()][:6]
    tc = str(d.get("ticker_color") or "blue").lower()
    d["ticker_color"] = tc if tc in _VALID_COLORS else "blue"
    return d


# ── SA 파싱 ────────────────────────────────────────────────────────────────

def parse_article(article_id: int) -> tuple[str | None, str | None, list, str | None]:
    """sa_publish.py parse 호출 → (본문, method, 공식티커후보, 오류사유).
    성공: (content, method, [{symbol,name}...], None) / 실패: (None, None, [], reason)."""
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "sa_publish.py"), "parse", str(article_id)],
            # SA 페이지 로딩이 느릴 수 있고, 폴백(API+Jina+Playwright+curl_cffi)이
            # 순차로 돌면 worst-case가 길어지므로 래퍼는 넉넉히 잡음.
            capture_output=True, text=True, timeout=200,
        )
        # stderr에서 PARSE_METHOD / SA_TICKERS 추출 (성공/실패 무관하게 시도)
        method = None
        sa_tickers = []
        for line in (result.stderr or "").splitlines():
            if line.startswith("PARSE_METHOD:"):
                method = line.split(":", 1)[1].strip() or None
            elif line.startswith("SA_TICKERS:"):
                try:
                    sa_tickers = json.loads(line.split(":", 1)[1].strip())
                except Exception:
                    sa_tickers = []
        if result.returncode != 0:
            reason = result.stderr.strip() or f"parse exit {result.returncode}"
            return None, None, [], reason
        content = result.stdout.strip()
        if not content:
            return None, None, [], "parse returned empty content"
        return content, method, sa_tickers, None
    except subprocess.TimeoutExpired:
        return None, None, [], "parse timeout"
    except Exception as e:
        return None, None, [], str(e)


# ── 단일 기사 처리 ─────────────────────────────────────────────────────────

def process_article(row: dict) -> bool:
    """기사 1건 처리. 성공 True / 실패 False."""
    article_id = row["id"]
    ticker = row.get("ticker", "")
    orig = (row.get("original_title") or "")[:60]
    print(f"  [{article_id}] {ticker} | {orig}")

    # 1. SA 페이지 파싱
    content, parse_method, sa_tickers, parse_err = parse_article(article_id)
    if not content:
        reason = parse_err or "PARSE_FAIL"
        print(f"     파싱 실패: {reason}", file=sys.stderr)
        res = db.mark_attempt_failed(article_id, reason[:200])
        print(f"     → {res}")
        return False

    # 2. Claude로 한국어 요약 생성 — SA 공식 태깅 티커가 있으면 후보 화이트리스트로 주입
    candidates = ""
    if sa_tickers:
        pairs = ", ".join(
            f"{t['symbol']}={t.get('name') or t['symbol']}" for t in sa_tickers if t.get("symbol")
        )
        if pairs:
            candidates = (
                "\n\nSA 공식 태깅 후보 종목(심볼=회사명): " + pairs +
                "\n- 위 후보 중 본문상 **실질 관련**인 것만 ticker/company_name에 사용(단순 나열·비교대상 제외)."
                "\n- 심볼·회사명은 이 표기를 그대로 사용(임의 변형 금지)."
                "\n- 목록에 없어도 본문의 핵심 상장사는 추가 가능."
            )
    prompt = _PROMPT_TMPL.format(content=content[:10000], candidates=candidates)
    print(f"     Claude 요약 중…", end="", flush=True)
    response, summary_model = call_claude(prompt)
    if not response:
        # Claude 실패 → grok CLI 폴백
        print(" 실패 → grok 폴백…", end="", flush=True)
        response, summary_model = call_grok(prompt)
    if not response:
        reason = "Claude/grok CLI 응답 없음"
        print(f"\n     {reason}", file=sys.stderr)
        db.mark_attempt_failed(article_id, reason)
        return False
    print(f" 완료 ({summary_model})")

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
        summary_details=data["summary_details"],
        ticker_color=data["ticker_color"],
        parse_method=parse_method,
        summary_model=summary_model,
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
        # due 조건 무시하고 직접 조회 (수동 단건 — 락 불필요)
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
        # cron 틱 겹침 방지 — 이전 배치가 아직 돌고 있으면 skip
        with single_instance("sa-publish") as ok:
            if not ok:
                print("SA summarize (claude): 이전 배치 실행 중 — skip", file=sys.stderr)
                return
            run_batch(args.batch)


if __name__ == "__main__":
    main()

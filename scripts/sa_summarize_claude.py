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
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT))

import db  # noqa: E402
import settings  # noqa: E402
from sa_claude_cli import call_claude, call_grok, extract_json  # noqa: E402
from sa_lock import single_instance  # noqa: E402

# ── 프롬프트 ──────────────────────────────────────────────────────────────
_PROMPT_TMPL = """\
다음은 Seeking Alpha 기사 원문입니다.
아래 JSON 형식으로만 응답하세요. JSON 외의 텍스트·설명·마크다운 코드블럭은 절대 출력하지 마세요.

출력 형식 (한 줄, key 순서 고정):
{{"ticker":"AVGO, NVDA","company_name":"Broadcom·Nvidia","headline":"한국어제목","summary_details":["핵심 이벤트·수치","두 번째 포인트"],"ticker_color":"blue"}}

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
  ⚠️ SpaceX는 **상장사(SPCX)** 다. 비상장으로 오인해 빠뜨리지 말고, 실질 관련이면 반드시 포함한다.
     (예: 'VinSpace가 SpaceX와 발사 계약' → SPCX 포함. 단순 배경 언급이면 기존대로 제외)
  기사에 해당 기업이 없으면 빈 문자열 "".
- company_name: ticker 순서·개수와 **정확히 동일하게** 정식 영문 기업명을 · 로 연결 (예: "Nvidia·AMD").
  ticker를 N개 넣었으면 company_name도 N개. 한국어 번역·음차 절대 금지. 티커 기호(AAPL 등) 포함 금지.
- headline: 티커 prefix 금지. 핵심 이벤트와 수치만 담은 짧은 한국어 제목.
  예) 'TSLA: 테슬라 가격 인상' ✗ → 'Tesla, 2년 만에 첫 모델 Y 가격 인상' ✓
- summary_details: 아래 === 기사 원문 === 에 적힌 SA 사이트 수집본만 근거로 요약.
  각 항목은 간결한 단문. 한 항목에 사실 하나만. 핵심 이벤트·주체·수치·날짜만 남긴다.
  '~했다' '~밝혔다' '~보도했다' '~전망했다' 같은 완결형 종결은 쓰지 말 것.
  명사구·체언 종결로 끝낸다. 예) '월요일 캘리포니아 AG와 면담, 1110억 달러 합병 화해'
  종목 나열, 세부 시나리오, 컨센서스 병기, 배경 설명, 수식은 빼거나 한 덩어리로 압축한다.
  원문에 있는 이름·수치·날짜만 쓰고, 없는 사실은 쓰지 않는다.
  항목 수를 채우려고 내용을 늘리지 말 것. 원문이 짧거나 미리보기면 1~2개가 맞다.
  사전 지식, 다른 기사, 추정, 일반적인 배경으로 빈칸을 메우지 말 것.
  원문에 없는 인물·법원·합의조건·발언을 보강하는 것은 금지.
- ticker_color: blue|green|red|orange|yellow|purple|gray 중 1개.
  상승·긍정=green, 하락·부정=red, 중립·기타=blue
- 외국 기업·인명·약품명 = 영문 원어 유지. 한국 기업만 한국어 유지.
  음차 금지 예: 앤티로픽→Anthropic, 파란티어→Palantir, 애플→Apple, 테슬라→Tesla, 엔비디아→Nvidia
- 한자·가나 절대 금지. 売上→매출, 格上げ→상향 등으로 순 한국어 교체.{candidates}

=== 기사 원문 ===
{content}
"""


_VALID_COLORS = {"blue", "green", "red", "orange", "yellow", "purple", "gray"}
_TICKER_RE = re.compile(r"^[A-Z0-9.^-]{1,12}$")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)]\([^)]+\)")

EXIT_OK = 0
EXIT_INFRA_FAILURE = 1
EXIT_PARTIAL_FAILURE = 2


@dataclass(frozen=True)
class AttemptSuccess:
    """파싱·요약·검증은 완료됐지만 아직 DB에 반영하지 않은 결과."""

    ticker: str | None
    company_name: str
    headline: str
    summary_details: list[str]
    ticker_color: str
    parse_method: str | None
    summary_model: str | None


@dataclass(frozen=True)
class AttemptFailure:
    """DB에 정확히 한 번 기록해야 할 기사 단위 실패."""

    reason: str


@dataclass(frozen=True)
class BatchResult:
    attempted: int
    succeeded: int
    failed: int


def _plain_text(value) -> str:
    text = str(value or "").strip()
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    return text.replace("**", "").replace("__", "").replace("*", "").replace("_", " ")


def validate(d: dict) -> dict:
    """Normalize model output and reject forbidden writing-system leakage."""
    raw_tickers = str(d.get("ticker") or "").upper().strip()
    valid_tickers = []
    for ticker in raw_tickers.split(","):
        ticker = ticker.strip()
        if _TICKER_RE.fullmatch(ticker) and ticker not in valid_tickers:
            valid_tickers.append(ticker)
    d["ticker"] = ", ".join(valid_tickers)
    d["company_name"] = _plain_text(d.get("company_name"))
    d["headline"] = _plain_text(d.get("headline"))
    details = d.get("summary_details") or []
    if not isinstance(details, list):
        details = [str(details)]
    normalized_details = [_plain_text(item) for item in details]
    d["summary_details"] = [item for item in normalized_details if item][:6]
    tc = str(d.get("ticker_color") or "blue").lower()
    d["ticker_color"] = tc if tc in _VALID_COLORS else "blue"

    korean_blob = d["headline"] + "".join(d["summary_details"])
    if _HAN_RE.search(korean_blob):
        raise ValueError("한자 문자가 요약에 포함됨")
    if _KANA_RE.search(korean_blob):
        raise ValueError("가나 문자가 요약에 포함됨")
    return d


# ── SA 파싱 ────────────────────────────────────────────────────────────────

def parse_article(
    article_id: int,
    *,
    reuse_source: bool = False,
) -> tuple[str | None, str | None, list, str | None]:
    """sa_publish.py parse 호출 → (본문, method, 공식티커후보, 오류사유).
    reuse_source 이면 저장된 source_text 를 쓰고 SA 에 접속하지 않는다.
    성공: (content, method, [{symbol,name}...], None) / 실패: (None, None, [], reason)."""
    if reuse_source:
        src = db.get_source(article_id)
        if src and db.source_quality_ok(src["chars"], src["locked"]):
            return src["text"], src["method"], [], None
        return None, None, [], "저장된 본문 없음 또는 품질 미달"
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "sa_publish.py"), "parse", str(article_id)],
            # SA 페이지 로딩이 느릴 수 있고, 폴백(API+Jina+Playwright+curl_cffi)이
            # 순차로 돌면 worst-case가 길어지므로 래퍼는 넉넉히 잡음.
            capture_output=True,
            text=True,
            timeout=settings.PUBLISH_PARSE_TIMEOUT_SECONDS,
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

def pick_summarizers(article_id: int):
    """기사별 1차/폴백 요약 모델 결정 → (1차 이름, 1차 함수, 폴백 이름, 폴백 함수).

    라운드로빈은 기사 id 홀짝으로 정한다. cron이 배치마다 새 프로세스를 띄우므로
    메모리 카운터는 배치가 1건일 때 항상 같은 모델만 골라 무의미하기 때문.
    id는 연속 증가라 실제로는 기사 단위로 번갈아 배정된다.
    재시도 시에도 같은 1차 모델이 배정되지만, 실패하면 폴백이 받으므로 가용성은 유지된다.
    """
    if settings.SUMMARY_ROUND_ROBIN and article_id % 2 == 1:
        return "grok", call_grok, "Claude", call_claude
    return "Claude", call_claude, "grok", call_grok


def attempt_article(row: dict, *, reuse_source: bool = False) -> AttemptSuccess | AttemptFailure:
    """기사 1건을 파싱·요약·검증하되 DB 상태는 변경하지 않는다."""
    article_id = row["id"]
    ticker = row.get("ticker", "")
    orig = (row.get("original_title") or "")[:60]
    print(f"  [{article_id}] {ticker} | {orig}")

    # 1. SA 페이지 파싱 (또는 저장된 본문)
    content, parse_method, sa_tickers, parse_err = parse_article(
        article_id, reuse_source=reuse_source
    )
    if not content:
        reason = parse_err or "PARSE_FAIL"
        print(f"     파싱 실패: {reason}", file=sys.stderr)
        return AttemptFailure(reason[:200])
    if not db.source_quality_ok(len(content), False):
        reason = f"본문 품질 미달 ({len(content)}자, 최소 {settings.SOURCE_MIN_CHARS})"
        print(f"     {reason}", file=sys.stderr)
        return AttemptFailure(reason[:200])

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
    prompt = _PROMPT_TMPL.format(
        content=content[: settings.SUMMARY_CONTENT_LIMIT],
        candidates=candidates,
    )
    primary_name, primary, fallback_name, fallback = pick_summarizers(article_id)
    print(f"     {primary_name} 요약 중…", end="", flush=True)
    response, summary_model = primary(prompt)
    if not response:
        # 1차 실패 → 다른 모델로 폴백
        print(f" 실패 → {fallback_name} 폴백…", end="", flush=True)
        response, summary_model = fallback(prompt)
    if not response:
        reason = "Claude/grok CLI 응답 없음"
        print(f"\n     {reason}", file=sys.stderr)
        return AttemptFailure(reason)
    print(f" 완료 ({summary_model})")

    # 3. JSON 추출 및 검증
    data = extract_json(response)
    if not data:
        reason = f"JSON 파싱 실패: {response[:120]}"
        print(f"     {reason}", file=sys.stderr)
        return AttemptFailure(reason[:200])

    try:
        data = validate(data)
    except ValueError as exc:
        reason = f"출력 검증 실패: {exc}"
        print(f"     {reason}", file=sys.stderr)
        return AttemptFailure(reason)
    if not data["headline"] or not data["summary_details"]:
        reason = f"필수 필드 누락: headline={bool(data['headline'])} summary_details={bool(data['summary_details'])}"
        print(f"     {reason}", file=sys.stderr)
        return AttemptFailure(reason[:200])

    # DB 반영은 process_article()이 단 한 번만 담당한다.
    new_ticker = data.get("ticker") or ""
    return AttemptSuccess(
        ticker=new_ticker if new_ticker else None,
        company_name=data["company_name"],
        headline=data["headline"],
        summary_details=data["summary_details"],
        ticker_color=data["ticker_color"],
        parse_method=parse_method,
        summary_model=summary_model,
    )


def process_article(row: dict, *, reuse_source: bool = False) -> bool:
    """기사 1건 처리. 기사 실패는 한 번 기록하고, DB 장애는 호출자로 올린다."""
    article_id = row["id"]
    try:
        outcome = attempt_article(row, reuse_source=reuse_source)
    except sqlite3.Error:
        raise
    except Exception as exc:
        reason = f"예상하지 못한 처리 오류: {type(exc).__name__}: {exc}"
        print(f"     {reason}", file=sys.stderr)
        outcome = AttemptFailure(reason[:200])

    if isinstance(outcome, AttemptFailure):
        result = db.mark_attempt_failed(article_id, outcome.reason)
        print(f"     → {result}")
        return False

    # DB 발행 (ticker가 추출됐으면 교체, 없으면 Stage 1 값 유지)
    ok = db.publish_article(
        article_id,
        ticker=outcome.ticker,
        company_name=outcome.company_name,
        headline=outcome.headline,
        summary_details=outcome.summary_details,
        ticker_color=outcome.ticker_color,
        parse_method=outcome.parse_method,
        summary_model=outcome.summary_model,
    )
    if ok:
        print(f"     ✓ published: {outcome.headline[:70]}")
    else:
        print("     publish 실패 (삭제/영구정리 상태 또는 동시 변경)", file=sys.stderr)
    return ok


# ── 배치 실행 ──────────────────────────────────────────────────────────────

def run_batch(batch_size: int) -> BatchResult:
    rows = db.get_pending_due(batch_size=batch_size)
    if not rows:
        print("SA summarize (claude): pending 없음")
        return BatchResult(attempted=0, succeeded=0, failed=0)
    print(f"SA summarize (claude): {len(rows)}건 처리 시작")
    ok = fail = 0
    gap = settings.ARTICLE_GAP_SECONDS
    for i, row in enumerate(rows):
        if i and gap > 0:
            print(f"     SA 요청 간격 {gap}s …")
            time.sleep(gap)
        if process_article(row):
            ok += 1
        else:
            fail += 1
    print(f"SA summarize (claude): 완료 — 성공 {ok}건 / 실패 {fail}건")
    return BatchResult(attempted=len(rows), succeeded=ok, failed=fail)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SA Stage 2 — Claude CLI 요약")
    p.add_argument(
        "--batch",
        type=int,
        default=settings.PUBLISH_BATCH_SIZE,
        help=f"일괄 처리 건수 (기본 {settings.PUBLISH_BATCH_SIZE})",
    )
    p.add_argument("--id", type=int, dest="article_id", help="특정 article_id 강제 처리")
    p.add_argument(
        "--reuse-source",
        action="store_true",
        help="저장된 source_text 로만 재요약 (SA 재접속 없음)",
    )
    args = p.parse_args(argv)

    try:
        if args.article_id:
            # due 조건 무시하고 직접 조회 (수동 단건 — 락 불필요)
            with db.get_conn() as conn:
                r = conn.execute(
                    "SELECT id, ticker, original_title, article_url, retry_count "
                    "FROM articles WHERE id = ? "
                    "AND pub_status IN ('pending', 'published', 'failed')",
                    (args.article_id,),
                ).fetchone()
            if not r:
                print(f"article_id {args.article_id} 없음 또는 처리 불가 상태", file=sys.stderr)
                return EXIT_INFRA_FAILURE
            return (
                EXIT_OK
                if process_article(dict(r), reuse_source=args.reuse_source)
                else EXIT_PARTIAL_FAILURE
            )

        # cron 틱 겹침 방지 — 이전 배치가 아직 돌고 있으면 skip
        with single_instance("sa-publish") as ok:
            if not ok:
                print("SA summarize (claude): 이전 배치 실행 중 — skip", file=sys.stderr)
                return EXIT_OK
            result = run_batch(args.batch)
            return EXIT_PARTIAL_FAILURE if result.failed else EXIT_OK
    except sqlite3.Error as exc:
        print(f"SA summarize (claude): DB 오류 — {exc}", file=sys.stderr)
        return EXIT_INFRA_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())

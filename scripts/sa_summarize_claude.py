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
from sa_llm import call_claude, call_codex, call_gemini, call_grok  # noqa: E402
import summary_config  # noqa: E402
from sa_lock import single_instance  # noqa: E402
from summary_contract import (
    _HAN_RE, _KANA_RE, _MARKDOWN_LINK_RE, _PROMPT_TMPL, _TICKER_RE, _VALID_COLORS,
    _checked_summary, _plain_text, validate,
)

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

def summary_chain(config: dict | None = None, article_id: int | None = None) -> list[tuple[str, object]]:
    """대시보드 설정(summary_config)의 요약 슬롯으로 [(모델, 호출함수)] — 라운드로빈.

    2026-09-26부터 설정 팝업이 정한다(모델은 공용 LLM 카탈로그). 2026-10-12 사용자 지시로
    순차 폴백 → 라운드로빈, 같은 날 슬롯(칸마다 모델+추론, 1~5칸, 같은 모델 여러 칸 가능)으로:
    기사 id로 시작 슬롯을 돌리고(id % 칸 수) 실패하면 나머지 슬롯이 순서대로 받는다. 같은
    모델은 한 번만 부른다(여러 칸에 두는 건 시작 비중을 높이려는 것 — wm과 같은 규칙).
    article_id가 없으면 1번 칸부터. 설정 밖 모델로는 가지 않는다.
    """
    cfg = summary_config.normalize(config) if config is not None else summary_config.load()
    callers = {"claude": call_claude, "codex": call_codex, "grok": call_grok, "gemini": call_gemini}
    slots = cfg["slots"]
    start = int(article_id) % len(slots) if article_id is not None else 0
    chain, seen = [], set()
    for slot in slots[start:] + slots[:start]:
        model, effort = slot["model"], slot["effort"]
        fn = callers.get(summary_config.family(model))
        if not fn or model in seen:
            continue
        seen.add(model)
        chain.append((model, lambda prompt, title=None, _f=fn, _m=model, _e=effort:
                      _f(prompt, title=title, model=_m, reasoning=_e)))
    return chain


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
    # title은 LLM 호출 이력(llm_log)의 제목 — 기사 원제를 그대로 넘긴다.
    log_title = row.get("original_title") or None
    # 응답이 있어도 JSON·출력 검증·필수 필드까지 통과해야 성공이다. 어느 단계에서든
    # 실패하면 다음 순번 모델로 넘긴다(Astra 검토, 2026-09-26 — 예전엔 문자열만 오면
    # 체인을 끝내고 검증에서 실패해 다음 모델을 한 번도 부르지 않았다).
    data, summary_model, reason = None, None, "요약 모델 응답 없음"
    for i, (name, summarize) in enumerate(summary_chain(article_id=article_id)):
        # 라운드로빈 시작 모델 실패 → 남은 모델 (이력에는 실패 행 + 다음 행이 각각 남는다)
        print(f"{' 실패 →' if i else '    '} {name} 요약 중…", end="", flush=True)
        response, model = summarize(prompt, title=log_title)
        if not response:
            reason = "요약 모델 응답 없음"
            continue
        data, reason = _checked_summary(response, row.get("original_title") or "")
        if data is not None:
            summary_model = model
            break
        print(f"\n     {name}: {reason}", file=sys.stderr)
    if data is None:
        print(f"\n     {reason}", file=sys.stderr)
        return AttemptFailure(reason[:200])
    print(f" 완료 ({summary_model})")

    # DB 반영은 process_article()이 단 한 번만 담당한다.
    # 모델이 티커를 비우면 비운 그대로 저장한다 — None으로 넘기면 1단계에 저장된 메일 제목 앞 티커(SA 태그)가
    # 남아 '태그일 뿐이면 넣지 않는다'는 지시문 규칙이 무력해진다(2026-11-24, sa 12497).
    return AttemptSuccess(
        ticker=data.get("ticker") or "",
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

def run_grok_batch(batch_size: int) -> BatchResult:
    """Grok Bot 원문 모드: 드라이브로 요청을 올리고 결과를 가져온 뒤, 원문이 들어온 기사만 요약한다.
    SA 사이트에는 접속하지 않는다(2026-10-11 사용자 결정)."""
    import grok_bridge
    try:
        stats = grok_bridge.sync()
        print(f"Grok 연동: 요청 {stats.get('sent', 0)}건 · 원문 도착 {stats.get('ready', 0)}건 · "
              f"대기 {stats.get('waiting', 0)}건 · 실패 {stats.get('failed', 0) + stats.get('timeout', 0)}건")
    except Exception as exc:                       # 드라이브 장애여도 이미 받은 원문은 요약한다
        print(f"Grok 연동 오류(다음 주기에 다시): {type(exc).__name__}: {exc}", file=sys.stderr)
    ready = {r["id"] for r in grok_bridge.ready_rows(1000)}
    rows = [r for r in db.get_pending_due(batch_size=1000) if r["id"] in ready][:batch_size]
    if not rows:
        print("SA summarize (claude): 요약할 Grok 원문 없음")
        return BatchResult(attempted=0, succeeded=0, failed=0)
    print(f"SA summarize (claude): {len(rows)}건 처리 시작 (Grok 원문)")
    ok = fail = 0
    for row in rows:
        if process_article(row, reuse_source=True):
            ok += 1
        else:
            fail += 1
    print(f"SA summarize (claude): 완료 — 성공 {ok}건 / 실패 {fail}건")
    return BatchResult(attempted=len(rows), succeeded=ok, failed=fail)


def run_batch(batch_size: int) -> BatchResult:
    if settings.SOURCE_MODE == "grok":
        return run_grok_batch(batch_size)
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
                # Grok 원문 모드에서는 수동 재처리도 SA에 접속하지 않고 저장된 원문만 쓴다
                if process_article(dict(r), reuse_source=args.reuse_source or settings.SOURCE_MODE == "grok")
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

"""Runtime configuration shared by the dashboard and worker scripts.

Environment variables are intentionally resolved once at process startup.  This
keeps the existing cron/launchd entrypoints stable while making local tests and
machine migrations independent from hard-coded paths.
"""

from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float, *, minimum: float = 0.1) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default


DB_PATH = Path(os.environ.get("SA_DB_PATH", str(BASE_DIR / "sa_news.db"))).expanduser()
DB_BUSY_TIMEOUT_MS = _env_int("SA_DB_BUSY_TIMEOUT_MS", 5_000)

PORTFOLIO_API_BASE = os.environ.get(
    "PORTFOLIO_API_BASE", "http://127.0.0.1:8765"
).rstrip("/")
PORTFOLIO_API_TIMEOUT_SECONDS = _env_float("PORTFOLIO_API_TIMEOUT_SECONDS", 6.0)

# 요약 모델 라운드로빈 — 기사별로 Claude/grok을 번갈아 1차 모델로 쓴다.
# 0/false/no/off 로 끄면 항상 Claude 우선(구 동작). 어느 쪽이든 1차 실패 시
# 다른 모델로 폴백하므로 가용성은 동일하다.
SUMMARY_ROUND_ROBIN = os.environ.get("SA_SUMMARY_ROUND_ROBIN", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

PUBLISH_BATCH_SIZE = _env_int("SA_PUBLISH_BATCH_SIZE", 10)
PUBLISH_PARSE_TIMEOUT_SECONDS = _env_int("SA_PARSE_TIMEOUT_SECONDS", 200)
# 기사와 기사 사이 Playwright 요청 간격. SA 차단 완화. 0이면 대기 없음.
ARTICLE_GAP_SECONDS = _env_int("SA_ARTICLE_GAP_SECONDS", 20, minimum=0)
SOURCE_MIN_CHARS = _env_int("SA_SOURCE_MIN_CHARS", 700)
# 로그인 세션 사용 여부. SA가 세션을 무효화(403)하면 인증 경로가 기사마다
# ~11초를 헛되이 쓰고 403을 반복 유발하므로, 재로그인 전까지 0으로 꺼둔다.
USE_LOGIN_SESSION = os.environ.get("SA_USE_LOGIN", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

# 로그인 세션이 서버에서 무효화되면(쿠키 만료일과 무관) 익명 경로로 자동 폴백한다.
#   LOGIN_FAIL_THRESHOLD : 인증이 연속 몇 회 프리뷰만 반환하면 무효로 볼지
#   LOGIN_REPROBE_MINUTES: 폴백 중 재로그인 여부를 다시 확인하는 주기
#   DEGRADED_MIN_CHARS   : 폴백 중 본문 길이 기준(익명은 프리뷰라 700자를 못 넘는다)
LOGIN_STATE_PATH = Path(
    os.environ.get("SA_LOGIN_STATE_PATH", str(BASE_DIR / ".sa_login_state.json"))
).expanduser()
LOGIN_FAIL_THRESHOLD = _env_int("SA_LOGIN_FAIL_THRESHOLD", 3)
LOGIN_REPROBE_MINUTES = _env_int("SA_LOGIN_REPROBE_MINUTES", 180)
DEGRADED_MIN_CHARS = _env_int("SA_DEGRADED_MIN_CHARS", 200)

ALLOW_ANON_FETCH = os.environ.get("SA_ALLOW_ANON_FETCH", "0").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
    "",
}
SUMMARY_TIMEOUT_SECONDS = _env_int("SA_SUMMARY_TIMEOUT_SECONDS", 120)
SUMMARY_CONTENT_LIMIT = _env_int("SA_SUMMARY_CONTENT_LIMIT", 10_000)
MAX_RETRY = _env_int("SA_MAX_RETRY", 5)
RETRY_BASE_MINUTES = _env_int("SA_RETRY_BASE_MINUTES", 20)

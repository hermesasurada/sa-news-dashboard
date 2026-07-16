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

PUBLISH_BATCH_SIZE = _env_int("SA_PUBLISH_BATCH_SIZE", 10)
PUBLISH_PARSE_TIMEOUT_SECONDS = _env_int("SA_PARSE_TIMEOUT_SECONDS", 200)
SUMMARY_TIMEOUT_SECONDS = _env_int("SA_SUMMARY_TIMEOUT_SECONDS", 120)
SUMMARY_CONTENT_LIMIT = _env_int("SA_SUMMARY_CONTENT_LIMIT", 10_000)
MAX_RETRY = _env_int("SA_MAX_RETRY", 5)
RETRY_BASE_MINUTES = _env_int("SA_RETRY_BASE_MINUTES", 20)

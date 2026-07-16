"""Portfolio quote adapter used by the FastAPI layer.

The adapter owns ticker validation, transport failures and response
normalization so HTTP concerns stay out of the service logic and the behavior
can be tested without starting the dashboard.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import settings


QUOTE_REDIRECTS = {
    "GOOG": "GOOGL",  # dashboard uses Class C; portfolio serves Class A
}
_TICKER_RE = re.compile(r"^[A-Z0-9.^:-]{1,32}$")


class InvalidTickerError(ValueError):
    """Raised when a ticker cannot safely be passed to the portfolio API."""


def normalize_ticker(ticker: str) -> str:
    clean = (ticker or "").strip().upper()
    if not _TICKER_RE.fullmatch(clean):
        raise InvalidTickerError("invalid ticker")
    return QUOTE_REDIRECTS.get(clean, clean)


def _fallback_name(ticker: str) -> str:
    try:
        import ticker_names

        return ticker_names.name_for(ticker) or ""
    except Exception:
        return ""


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _empty_quote(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "name": _fallback_name(ticker),
        "found": False,
        "currency": "",
        "current_price": None,
        "previous_price": None,
        "change": None,
        "change_pct": None,
        "extended_change_pct": None,
        "market_label": "",
        "market_status": "",
        "is_regular": None,
    }


def _fetch_raw(ticker: str) -> dict[str, Any] | None:
    url = f"{settings.PORTFOLIO_API_BASE}/api/chart?ticker={quote(ticker, safe='.-:')}"
    try:
        request = Request(url, headers={"User-Agent": "sa-dashboard/1.0"})
        with urlopen(request, timeout=settings.PORTFOLIO_API_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def get_price_quote(ticker: str) -> dict[str, Any]:
    clean = normalize_ticker(ticker)
    raw = _fetch_raw(clean)
    current = raw.get("current_price") if raw else None
    if not raw or not raw.get("ticker") or current is None:
        return _empty_quote(clean)

    previous = raw.get("previous_price")
    change = raw.get("change")
    market = raw.get("market") if isinstance(raw.get("market"), dict) else {}

    change_pct = raw.get("change_pct")
    change_number = _as_float(change)
    previous_number = _as_float(previous)
    if change_number is not None and previous_number not in (None, 0):
        change_pct = change_number / previous_number * 100.0

    extended_change_pct = None
    ext_pct = _as_float(raw.get("extended_change_pct"))
    ext_price = _as_float(raw.get("extended_price"))
    current_number = _as_float(current)
    if (
        ext_pct is not None
        and ext_price is not None
        and current_number is not None
        and not market.get("is_regular", True)
        and abs(current_number - ext_price) < 1e-9
    ):
        extended_change_pct = ext_pct

    change_pct_number = _as_float(change_pct)
    if (
        extended_change_pct is not None
        and change_pct_number is not None
        and abs(extended_change_pct - change_pct_number) < 0.005
    ):
        extended_change_pct = None

    name = raw.get("name") or ""
    if not name or str(name).upper() == clean:
        name = _fallback_name(clean) or name or clean

    return {
        "ticker": raw.get("ticker") or clean,
        "name": name,
        "found": True,
        "currency": raw.get("currency") or "",
        "current_price": current,
        "previous_price": previous,
        "change": change,
        "change_pct": change_pct,
        "extended_change_pct": extended_change_pct,
        "market_label": market.get("label") or "",
        "market_status": market.get("status") or "",
        "is_regular": bool(market.get("is_regular")) if market else None,
    }

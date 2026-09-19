"""제목에 드러난 비미국 상장사를 티커로 보정한다.

요약 LLM은 미국 티커는 잘 뽑지만 아시아 상장사는 "티커를 확신할 수 없다"며 통째로
빠뜨리는 일이 있다 — 같은 MediaTek이 어떤 기사에서는 `2454.TW`로 들어가고 다른
기사에서는 아무 심볼도 없었다(2026-09-16 #7864 'MediaTek takes aim at Qualcomm').

두 가지로 오탐을 막는다.
- **제목에 회사명이 실제로 등장할 때만** 보탠다. SA 제목은 그 기사의 주역을 담으므로
  제목에 이름이 있으면 '실질 관련'으로 봐도 안전하다. 본문까지 보면 단순 비교·나열도
  걸려 오탐이 는다.
- 회사마다 **그 회사를 가리키는 다른 심볼**(미국 OTC·ADR 등)을 함께 등록해, 이미
  어떤 형태로든 들어가 있으면 건드리지 않는다. SK hynix(SKHY/HXSCL/…)나 삼성(SSNLF)처럼
  모델이 OTC 심볼로 일관되게 뽑는 회사는 애초에 보정 대상이 아니다.

별칭은 대소문자를 구분해 맞춘다 — 'SAP'를 영어 단어 'sap'와, 'Sony'를 'Sonymobile'과
헷갈리지 않기 위해서다.
"""
from __future__ import annotations

import re
import logging
import os
import sqlite3
import time
from pathlib import Path
from contextlib import closing

PORTFOLIO_DB = Path(os.environ.get("SA_PORTFOLIO_DB", str(Path.home() / ".hermes/data/stock_history.db")))
_catalog_cache = (0.0, [])


def portfolio_companies():
    """Read the local collected universe, cached for five minutes; no network on render."""
    global _catalog_cache
    if time.monotonic() - _catalog_cache[0] < 300:
        return _catalog_cache[1]
    try:
        with closing(sqlite3.connect(PORTFOLIO_DB.as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
            rows = conn.execute("SELECT ticker, name, display_name FROM tickers WHERE COALESCE(category, '') != 'crypto'").fetchall()
        result = []
        for symbol, name, display in rows:
            if symbol.startswith("^") or symbol in {"EUROSTOXX50", "SP500", "DJI", "IXIC"}:
                continue
            if not name or re.search(r"ETF|ETN|Direxion|NEXT FUNDS|iShares|ProShares|Vanguard|\b[23]x\b", name, re.I):
                continue
            aliases = {name.strip(), (display or "").strip()}
            aliases.add(re.sub(r",?\s+(?:Inc\.?|Co\.,? Ltd\.?|Corporation|Corp\.?|Limited|Holdings?|Group Corporation)$", "", name).strip())
            aliases = tuple(a for a in aliases if len(a) >= 4 and not a.isupper() and a != symbol)
            if aliases:
                result.append((symbol, display or name, aliases, ()))
        _catalog_cache = (time.monotonic(), result)
        return result
    except (sqlite3.Error, OSError, ValueError) as exc:
        logging.getLogger(__name__).warning("Portfolio ticker catalog unavailable: %s", exc)
        _catalog_cache = (time.monotonic(), _catalog_cache[1])
        return _catalog_cache[1]

# (티커, 정식 영문 기업명, 제목에서 찾을 별칭, 같은 회사를 가리키는 다른 심볼)
# 티커는 quote_service가 조회할 수 있는 포트폴리오 형식이어야 한다.
_COMPANIES: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = [
    ("2454.TW", "MediaTek", ("MediaTek",), ("MDTKF", "MDTKY")),
    ("6981.T", "Murata Manufacturing", ("Murata",), ("MRAAY", "MRAAF")),
    ("8035.T", "Tokyo Electron", ("Tokyo Electron",), ("TOELY", "TOELF")),
    ("6857.T", "Advantest", ("Advantest",), ("ATEYY", "ADTTF")),
    ("6954.T", "Fanuc", ("Fanuc", "FANUC"), ("FANUY", "FANUF")),
    ("6506.T", "Yaskawa Electric", ("Yaskawa",), ("YASKY", "YASKF")),
    ("6702.T", "Fujitsu", ("Fujitsu",), ("FJTSY", "FJTSF")),
    ("2382.TW", "Quanta Computer", ("Quanta Computer",), ("QUCCF",)),
    ("2308.TW", "Delta Electronics", ("Delta Electronics",), ("DLTLF",)),
    ("3231.TW", "Wistron", ("Wistron",), ("WICOF", "WICOY")),
]

_PATTERNS = [
    (symbol, name, {s.upper() for s in (symbol, *equivalents)},
     re.compile(r"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])"
                % "|".join(re.escape(a) for a in aliases)))       # 대소문자 구분
    for symbol, name, aliases, equivalents in _COMPANIES
]


def missing_from_title(title: str, tickers: list[str]) -> list[tuple[str, str]]:
    """제목에 있으나 어떤 심볼로도 들어가지 않은 (티커, 회사명) 목록."""
    have = {t.strip().upper() for t in tickers if t.strip()}
    if re.search(r"(?:Yield Shares|Purpose ETF|ETF.*declares|ETF.*dividend)", title or "", re.I):
        return []
    out: list[tuple[str, str]] = []
    patterns = list(_PATTERNS)
    curated = {symbol for symbol, *_ in _COMPANIES}
    # ADR/local equivalents are one issuer, not additional chips.
    equivalents = {"2330.TW": ("TSM",), "6758.T": ("SONY",),
                   "005930.KS": ("SSNLF", "SSNNF"), "000660.KS": ("HXSCL", "SKHY", "HXSCF"),
                   "GOOGL": ("GOOG",), "BRK-B": ("BRK.A", "BRK.B", "BRK-A"),
                   "AIR.PA": ("EADSY", "EADSF"), "9984.T": ("SFTBY", "SFTBF"),
                   "285A.T": ("KXIAY",), "2FE.DE": ("RACE",),
                   "7974.T": ("NTDOY", "NTDOF"), "6501.T": ("HTHIY", "HTHIF"),
                   "LHA.DE": ("DLAKF", "DLAKY"), "RHM.DE": ("RNMBF", "RNMBY"),
                   "SIE.DE": ("SIEGY",), "ENR.DE": ("SMEGF", "SMNEY"),
                   "1211.HK": ("BYDDY", "BYDDF"), "2317.TW": ("HNHPF",),
                   "7731.T": ("NINOY",), "ADS.DE": ("ADDYY",), "BMW.DE": ("BMWKY",),
                   "VOW3.DE": ("VWAGY",), "SAF.PA": ("SAFRF", "SAFRY"),
                   "RMS.PA": ("HESAY", "HESAF"), "AM.PA": ("DUAVF",),
                   "RR.L": ("RYCEY", "RYCEF"), "BA.L": ("BAESY",),
                   "SAAB-B.ST": ("SAABF", "SAABY"), "D05.SI": ("DBSDY",),
                   "IFX.DE": ("IFNNY", "IFNNF"), "STM.PA": ("STM",)}
    for home, others in equivalents.items():
        if have & {home, *others}:
            have.update({home, *others})
    for symbol, name, aliases, _ in portfolio_companies():
        if symbol in curated:
            continue
        patterns.append((symbol, name, {symbol, *equivalents.get(symbol, ())},
                         re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(a) for a in aliases) + r")(?![A-Za-z0-9])")))
    for symbol, name, known, pattern in patterns:
        if have & known:
            continue                       # 이 회사는 이미 어떤 형태로든 들어 있다
        match = pattern.search(title or "")
        if match:
            after = title[match.end():]
            before = title[:match.start()]
            if symbol in {"JPM", "GS", "MS", "C", "BAC", "UBS", "DB", "WFC", "BCS", "HSBC", "MCO", "NDAQ"}:
                if not re.match(r"(?:['’]s)?\s+(?:earnings|revenue|profit|dividend|acquires|partners|shares|stock|launches)\b", after, re.I):
                    continue
            if symbol == "LDO.MI" and re.match(r"\s+DRS\b", after):
                continue
            if symbol == "SIE.DE" and re.match(r"\s+Energy\b", after):
                continue
            if symbol == "BLK" and re.match(r"\s+TCP\b", after):
                continue
            if symbol == "FDX" and re.match(r"\s+Freight\b", after):
                continue
            if re.search(r"(?:according to|analysts? at|rated by|unlike|compared (?:with|to)|ahead of|cites|hires from|older)\s*$", before, re.I):
                continue
            out.append((symbol, name))
            have.update(known)
    return out


def supplement_pairs(title: str, ticker_text: str, company_text: str) -> tuple[str, str]:
    """Keep symbol/name pairs together, including legacy mismatched name counts."""
    symbols = [t.strip() for t in (ticker_text or "").split(",") if t.strip()]
    names = [n.strip() for n in (company_text or "").split("·")]
    pairs = [(symbol, names[i] if i < len(names) and names[i] else symbol)
             for i, symbol in enumerate(symbols)]
    added = missing_from_title(title, symbols)
    if not added:
        return ticker_text, company_text
    # Extra names cannot reliably be assigned; preserve the original rather than guess.
    if len([n for n in names if n]) > len(symbols):
        return ticker_text, company_text
    pairs.extend(added)
    return ", ".join(p[0] for p in pairs), "·".join(p[1] for p in pairs)

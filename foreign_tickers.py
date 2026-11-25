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

import company_table

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

def numeric_code_names() -> dict[str, str]:
    """숫자로 시작하는 종목코드 → 포트폴리오 표시명칭(칩 표기용, 2026-10-12)."""
    with closing(sqlite3.connect(PORTFOLIO_DB.as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
        rows = conn.execute("SELECT ticker, COALESCE(NULLIF(display_name, ''), name) FROM tickers "
                            "WHERE ticker GLOB '[0-9]*' AND COALESCE(category, '') != 'crypto'").fetchall()
    return {t: n for t, n in rows if n}


# (티커, 제목에서 찾을 별칭) — 제목 별칭(대소문자 구분)은 sa의 제목 판정 규칙이라 여기 둔다.
# 정식 영문 기업명과 같은 회사의 다른 심볼(OTC·ADR)은 증류 기업 등록부에서 온다(company_table, 2026-11-11 —
# 예전엔 이 표에 이름과 심볼 묶음을 직접 적었다). 티커는 quote_service가 조회할 수 있는 포트폴리오 형식이어야 한다.
_COMPANIES: list[tuple[str, tuple[str, ...]]] = [
    ("2454.TW", ("MediaTek",)),
    ("6981.T", ("Murata",)),
    ("8035.T", ("Tokyo Electron",)),
    ("6857.T", ("Advantest",)),
    ("6954.T", ("Fanuc", "FANUC")),
    ("6506.T", ("Yaskawa",)),
    ("6702.T", ("Fujitsu",)),
    ("2382.TW", ("Quanta Computer",)),
    ("2308.TW", ("Delta Electronics",)),
    ("3231.TW", ("Wistron",)),
    # 2026-10-12 사용자 지적(sa 9081): 카탈로그 이름이 'CXMT CORPORATION'(전부 대문자)이라 짧은 대문자 약어 제외
    # 규칙에 걸려 별칭이 하나도 없었다. 'CXMT'는 다른 뜻으로 쓰이지 않는 고유 약어라 대소문자 구분해 직접 등록.
    ("688825.SS", ("CXMT", "ChangXin Memory", "ChangXin")),
]


def _brand_patterns(equivalents: dict) -> list:
    """등록부 brands(자회사·브랜드 → 모회사, 2026-11-20 사용자 지시 sa 12163 'Boston Dynamics → 현대차').
    제목에 브랜드 이름이 나오면 모회사 티커를 보탠다 — 회사 별칭과 같은 제목 한정·대소문자 구분·오탐 가드를 그대로 받는다."""
    return [
        (symbol, company_table.company_name(symbol, symbol), {s.upper() for s in (symbol, *equivalents.get(symbol, ()))},
         re.compile(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(brand)))
        for brand, symbol in sorted(company_table.brands().items())
    ]


def _curated_patterns(equivalents: dict) -> list:
    return [
        (symbol, company_table.company_name(symbol, symbol), {s.upper() for s in (symbol, *equivalents.get(symbol, ()))},
         re.compile(r"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])"
                    % "|".join(re.escape(a) for a in aliases)))       # 대소문자 구분
        for symbol, aliases in _COMPANIES
    ]


def missing_from_title(title: str, tickers: list[str]) -> list[tuple[str, str]]:
    """제목에 있으나 어떤 심볼로도 들어가지 않은 (티커, 회사명) 목록."""
    have = {t.strip().upper() for t in tickers if t.strip()}
    if re.search(r"(?:Yield Shares|Purpose ETF|ETF.*declares|ETF.*dividend)", title or "", re.I):
        return []
    out: list[tuple[str, str]] = []
    # ADR/local equivalents are one issuer, not additional chips. 묶음은 등록부(symbol·other_symbols·other_listings).
    equivalents = company_table.equivalents()
    patterns = _curated_patterns(equivalents)
    curated = {symbol for symbol, _ in _COMPANIES}
    for home, others in equivalents.items():
        if have & {home, *others}:
            have.update({home, *others})
    for symbol, name, aliases, _ in portfolio_companies():
        if symbol in curated:
            continue
        patterns.append((symbol, name, {symbol, *equivalents.get(symbol, ())},
                         re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(a) for a in aliases) + r")(?![A-Za-z0-9])")))
    patterns.extend(_brand_patterns(equivalents))     # 회사 이름이 먼저 — 같은 회사면 아래 '이미 들어 있음'에서 걸러진다
    for symbol, name, known, pattern in patterns:
        if have & known:
            continue                       # 이 회사는 이미 어떤 형태로든 들어 있다
        match = pattern.search(title or "")
        if match:
            after = title[match.end():]
            before = title[:match.start()]
            if symbol in {"JPM", "GS", "MS", "C", "BAC", "UBS", "DB", "WFC", "BCS", "HSBC", "MCO", "NDAQ", "BLK"}:
                if not re.match(r"(?:['’]s)?\s+(?:earnings|revenue|profit|dividend|acquires|partners|shares|stock|launches)\b", after, re.I):
                    continue
            if symbol in {"LDO.MI", "FMNB.DE"} and re.match(r"\s+DRS\b", after):
                continue
            # 후보 75건 점검(2026-10-12)에서 확인된 동명·부분일치 오탐
            if re.match(r"-(?:class|like|style|type)\b", after, re.I):
                continue                   # Ford-class 항모, Reddit-like 앱
            if symbol == "MSTR" and re.search(r"[A-Z][\w&-]*\s*$", before):
                continue                   # ClearBridge Growth Strategy 등 펀드 전략명
            if symbol == "8058.T" and re.match(r"\s+(?:Heavy|UFJ|Electric|Motors|Estate|Chemical|HC|Materials|Logistics)\b", after):
                continue                   # 미쓰비시상사가 아닌 그룹 계열사
            if symbol == "ETN" and re.match(r"\s+(?:Fiber|Vance)\b", after):
                continue
            if symbol == "RS" and (re.match(r"\s+(?:Industries|Jio|Retail)\b", after)
                                   or re.search(r"Ambani['’]s\s*$", before)):
                continue                   # Reliance Industries ≠ Reliance, Inc.(RS)
            if symbol == "MRK" and have & {"MKGAF", "MKKGY", "MRK.DE"}:
                continue                   # Merck KGaA ≠ Merck & Co.
            if symbol == "BN" and have & {"BAM", "BEP", "BIP", "BBU"}:
                continue                   # 다른 Brookfield 상장사가 이미 있음
            if symbol == "AIR.PA" and re.match(r"\s+aircraft\b", after) and re.search(r"\bfor\s*$", before):
                continue                   # 'for Airbus aircraft' 제품 언급
            if symbol == "SIE.DE" and re.match(r"\s+Energy\b", after):
                continue
            if symbol == "BLK" and re.match(r"\s+TCP\b", after):
                continue
            if symbol == "FDX" and re.match(r"\s+Freight\b", after):
                continue
            if re.search(r"(?:according to|analysts? at|rated by|unlike|compared (?:with|to)|ahead of|cites|hires from|older|former|aboard)\s*$", before, re.I):
                continue
            out.append((symbol, name))
            have.update(known)
    return out


# 자산 칩 — 회사가 아닌 자산을 제목에서 찾아 포트폴리오 종목 칩을 보탠다. 회사 별칭 표(portfolio_companies는 crypto
# 제외)와 따로 둔다. 원제가 'COIN: … crypto …'처럼 자산 이름을 안 쓰는 일이 많아 **모델 헤드라인도 본다**(본문은 보지
# 않는다). 칩이 'NONE'(주체 없음 표시)뿐이면 그 자리를 바꾼다.
# - 암호화폐(2026-11-24 사용자 지시, sa 12490 'CFTC, Bitcoin·Ether 등 암호화폐 준비금 인정'): BTC·ETH(포트폴리오
#   category crypto — 시세 팝오버가 원화 시세로 열린다). 영문은 대소문자 구분 — 소문자 'ether'(화합물)·'Ethernet'은
#   걸리지 않는다. 한글은 '비트코인'·'이더리움'만 — 맨 '이더'는 '트레이더'·'레이더'에 걸린다(31일 소급 시험 sa 12068·10814).
# - 금(2026-11-25 사용자 지시, sa 12595 'GLD: Gold gets a rude reminder…'): 포트폴리오에 금 현물이 없어 GLD(SPDR Gold
#   Shares) 칩을 붙인다. 영문 Gold·gold는 낱말 경계 + 회사 이름 가드('Maple Gold'·'Barrick Gold'처럼 대문자 낱말 뒤,
#   'Gold Fields'·'Gold Corp'처럼 회사 접미사 앞은 뺀다 — Goldman·Golden은 낱말 경계로 빠진다). 한글 '금'은 앞이 한글·영숫자가
#   아니고 뒤가 끝·공백·문장부호·조사(이·은·을·의·과·와·도·에)·값·가격·ETF·선물·현물·시세일 때만 — '금리'·'금융'·'자금'·
#   '현금'·'금요일'은 걸리지 않는다(90일 5,913건 시험: 오탐은 Maple Gold 1건 → 가드로 해결).
_CRYPTO_BTC = re.compile(r"(?<![A-Za-z0-9])(?:Bitcoin|bitcoin|BTC)(?![A-Za-z0-9])|비트코인")
_CRYPTO_ETH = re.compile(r"(?<![A-Za-z0-9])(?:Ethereum|ethereum|Ether|ETH)(?![A-Za-z0-9])|이더리움")
_GOLD_EN = re.compile(r"(?<![A-Za-z0-9])(?:Gold|gold)(?![A-Za-z0-9])")
_GOLD_COMPANY_BEFORE = re.compile(r"[A-Z][A-Za-z&.'-]*\s$")
_GOLD_COMPANY_AFTER = re.compile(r"\s(?:Fields|Corp|Corporation|Resources|Mining|Mines|Inc|Ltd|Royalty|Standard)\b")
_GOLD_KO = re.compile(r"(?<![가-힣A-Za-z0-9])금(?=$|[\s,.·:;!?)\]'\"’”/~-]|값|가격|이|은|을|의|과|와|도|에|ETF|선물|현물|시세)")


def _gold_hit(text: str) -> bool:
    if _GOLD_KO.search(text):
        return True
    for m in _GOLD_EN.finditer(text):
        if m.group(0) == "Gold" and (_GOLD_COMPANY_BEFORE.search(text[:m.start()])
                                     or _GOLD_COMPANY_AFTER.match(text, m.end())):
            continue
        return True
    return False


_ASSET_CHIPS: list[tuple[str, str, object]] = [
    ("BTC", "Bitcoin", lambda t: bool(_CRYPTO_BTC.search(t))),
    ("ETH", "Ethereum", lambda t: bool(_CRYPTO_ETH.search(t))),
    ("GLD", "SPDR Gold Shares", _gold_hit),
]


def asset_chips_from_titles(titles, tickers: list[str]) -> list[tuple[str, str]]:
    """제목들(원제·헤드라인)에 나왔는데 칩에 없는 (심볼, 이름) — BTC·ETH·GLD."""
    have = {t.strip().upper() for t in tickers if t.strip()}
    return [(symbol, name) for symbol, name, hit in _ASSET_CHIPS
            if symbol not in have and any(hit(t) for t in titles if t)]


def supplement_asset_chips(titles, ticker_text: str, company_text: str) -> tuple[str, str]:
    """supplement_pairs와 같은 짝 규칙으로 자산 칩(BTC·ETH·GLD)을 뒤에 붙인다."""
    symbols = [t.strip() for t in (ticker_text or "").split(",") if t.strip()]
    added = asset_chips_from_titles(titles, symbols)
    names = [n.strip() for n in (company_text or "").split("·")]
    if added and [t.upper() for t in symbols] == ["NONE"]:
        symbols, names = [], []
    if not added or len([n for n in names if n]) > len(symbols):
        return ticker_text, company_text
    pairs = [(symbol, names[i] if i < len(names) and names[i] else symbol) for i, symbol in enumerate(symbols)]
    pairs.extend(added)
    return ", ".join(p[0] for p in pairs), "·".join(p[1] for p in pairs)


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

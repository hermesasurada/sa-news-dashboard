"""미국 상장 심볼 → 정식 종목명 캐시 (NASDAQ Trader 공식 파일).

company_name이 비어 있을 때(매크로/라운드업 기사라 Claude가 회사명을 못 뽑은 경우)
티커의 정식 종목명으로 자동 백필하기 위한 조회 모듈.

- 캐시: ticker_names.json (repo 루트, gitignore). MAX_AGE_DAYS 경과 시 재다운로드.
- 네트워크 실패해도 stale 캐시/빈 맵으로 폴백 (호출측은 절대 깨지지 않음).
"""
import json
import re
import datetime
import urllib.request
from pathlib import Path

CACHE_PATH = Path(__file__).resolve().parent / "ticker_names.json"
MAX_AGE_DAYS = 7
_URLS = [
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
]

_cache = None  # 프로세스 내 메모이즈


def _clean(s: str) -> str:
    s = s.split(" - ")[0]
    s = re.sub(
        r"\s+(Common Stock|Capital Stock|Ordinary Shares|Common Shares|"
        r"Class [A-Z] (Common Stock|Ordinary Shares|Capital Stock)|"
        r"Depositary.*|American Depositary.*)$",
        "", s).strip()
    s = re.sub(r",?\s+(Inc\.?|Corp\.?|Corporation|Co\.?|Ltd\.?|plc|N\.V\.|S\.A\.)$", "", s).strip()
    return s


def _download_map() -> dict:
    out = {}
    for url in _URLS:
        with urllib.request.urlopen(url, timeout=20) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        for ln in text.splitlines()[1:]:
            p = ln.split("|")
            if len(p) > 1 and p[0] and "File Creation" not in ln:
                out.setdefault(p[0].strip().upper(), _clean(p[1].strip()))
    return out


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    # 신선한 파일 캐시가 있으면 사용
    try:
        if CACHE_PATH.exists():
            age = datetime.datetime.now() - datetime.datetime.fromtimestamp(CACHE_PATH.stat().st_mtime)
            if age.days < MAX_AGE_DAYS:
                _cache = json.loads(CACHE_PATH.read_text())
                return _cache
    except Exception:
        pass
    # 없거나 오래됨 → 다운로드 시도
    try:
        m = _download_map()
        if m:
            CACHE_PATH.write_text(json.dumps(m, ensure_ascii=False))
            _cache = m
            return _cache
    except Exception:
        pass
    # 다운로드 실패 → stale 캐시라도 사용, 그것도 없으면 빈 맵
    try:
        if CACHE_PATH.exists():
            _cache = json.loads(CACHE_PATH.read_text())
            return _cache
    except Exception:
        pass
    _cache = {}
    return _cache


def name_for(ticker: str) -> str:
    return _load().get(str(ticker).strip().upper(), "")


def fill_company(ticker_str: str, company_str: str = "") -> str:
    """ticker 순서에 맞춰 company의 빈 슬롯만 정식명으로 채움 (기존 값은 보존)."""
    tks = [t.strip() for t in str(ticker_str or "").split(",") if t.strip()]
    if not tks:
        return company_str or ""
    cos = [c.strip() for c in str(company_str or "").split("·")]
    out = []
    for i, t in enumerate(tks):
        cur = cos[i] if i < len(cos) else ""
        out.append(cur or name_for(t))
    return "·".join(out)

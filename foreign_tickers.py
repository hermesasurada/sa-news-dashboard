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
    out: list[tuple[str, str]] = []
    for symbol, name, known, pattern in _PATTERNS:
        if have & known:
            continue                       # 이 회사는 이미 어떤 형태로든 들어 있다
        if pattern.search(title or ""):
            out.append((symbol, name))
    return out

"""같은 회사의 여러 심볼(본국 상장·미국 OTC/ADR·다른 상장)과 칩 표시 이름 — 증류 기업 등록부에서 만든다.

2026-11-11 기업 이름 표 통합 7단계(사용자 지시, Knowledge Distiller 인계): sa에 따로 있던 세 표
(foreign_tickers의 같은 회사 심볼 묶음·`_COMPANIES` 4번째 칸, static/app.js `FOREIGN_LISTINGS`·`EXTRA_LISTINGS`)의
'어느 심볼이 어느 회사인지'와 '칩에 쓸 이름'은 이제 등록부(~/.hermes/vault-enrich/company_registry.json)가 정본이다.
  - 회사의 `symbol` + `other_symbols`(OTC·ADR·주식 종류) + `other_listings`가 한 묶음(같은 회사)
  - 칩 이름 = 그 상장의 `chip_label`, 없으면 회사 정규 이름. 아시아 상장(.KS·.T·.TW·.HK·.SS·.SZ)은 이름으로 표시(byName)
  - 시세 조회 상장(home) = 회사 `symbol`이 해외 상장이면 그것, 미국 심볼이면 묶음의 첫 해외 상장(Sony SONY → 6758.T)

sa 고유 규칙은 여기 남긴다(등록부에 두지 않는다):
  - FOREIGN_KEYS: 칩에서 본국 상장으로 '바꿔' 보일 미국 OTC·ADR 심볼(SSNLF → 삼성전자 005930.KS)
  - EXTRA_KEYS: 칩은 그대로 두고 본국 상장 칩을 '하나 더' 붙일 심볼(RACE + 2FE.DE, TSM + 2330.TW, SKHY + 000660.KS)
  - BARE_CODES: 거래소 접미사 없는 종목코드 표기(등록부 심볼 형식이 아니라서 여기 둔다)
  - 병합 방향(GOOGL → GOOG, 한국 코드 → OTC)은 db.TICKER_ALIASES
종목·OTC 심볼을 더할 때는 등록부의 그 회사 `other_symbols`에 넣는다(sa에 표를 다시 만들지 않는다).
확인: cd ~/.hermes/scripts && python3 -m distill.company_registry --show <이름|심볼>

등록부를 못 읽으면 마지막으로 읽은 내용(company_table.snapshot.json)으로, 그것도 없으면 빈 표로 돈다(칩은 OTC 심볼 그대로).
등록부 파일이 바뀌면 다음 조회 때(최대 30초 뒤) 다시 읽는다.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import time
from pathlib import Path

REGISTRY_MODULE_PATH = Path(os.path.expanduser(os.environ.get(
    "SA_COMPANY_REGISTRY_MODULE", "~/.hermes/scripts/distill/company_registry.py")))
SNAPSHOT_PATH = Path(os.environ.get(
    "SA_COMPANY_TABLE_SNAPSHOT", str(Path(__file__).resolve().parent / "company_table.snapshot.json")))
REFRESH_SECONDS = 30.0

# 칩에서 본국 상장으로 바꿔 보일 심볼(옛 app.js FOREIGN_LISTINGS의 키 — 시세가 없는 미국 OTC·ADR)
FOREIGN_KEYS = (
    "SSNLF", "HXSCL", "LGEIY", "NHNCF",                                            # 한국
    "EADSY", "EADSF", "ADDYY", "BMWKY", "VWAGY", "SIEGY", "SMEGF", "SMNEY", "DLAKF", "DLAKY", "DHER",
    "SAFRF", "SAFRY", "HESAY", "HESAF", "DUAVF", "ENI", "NTOIY", "IBDRY", "IBDSF", "CAMRF", "SAABF", "SAABY",
    "RYCEY", "RYCEF", "BAESY", "HEINY", "RNMBF", "RNMBY",                          # 유럽
    "SONY", "SNEJF", "NTDOY", "NTDOF", "SFTBY", "SFTBF", "NINOY", "HTHIY", "HTHIF",   # 일본(SONY ADR은 포트폴리오에 없다)
    "BYDDY", "BYDDF", "HNHPF", "FXCOF", "IVBIY", "IVBXF", "LNVGY",                 # 중국·대만·홍콩
    "QABSY", "SYAAF", "SRHYY", "DBSDY", "BDRBF", "BDRAF", "BOMBF", "KRKNF", "TAKOF",  # 기타
)
# 칩은 그대로 두고 본국 상장 칩을 더할 심볼(같은 회사 복수 상장 — 옛 EXTRA_LISTINGS의 키)
EXTRA_KEYS = ("RACE", "TSM", "SKHY")
# 접미사 없는 종목코드 표기 → 같은 회사(등록부 심볼 형식이 아니다)
BARE_CODES = {"688825.SS": ("688825",)}

_ASIA_RE = re.compile(r"\.(?:KS|KQ|T|TW|TWO|HK|SS|SZ)$")
_EXCHANGE_RE = re.compile(r"\.(?:KS|KQ|T|TW|TWO|HK|SS|SZ|PA|DE|MI|HE|MC|ST|L|AS|AX|SI|TO|V|SW|CO|OL|BR|LS|VI|IR|NS|BO)$")

_state = {"checked": 0.0, "mtime": None, "source": "none", "data": None}
_registry_module = None


def _registry():
    global _registry_module
    if _registry_module is None:
        spec = importlib.util.spec_from_file_location("sa_company_registry", str(REGISTRY_MODULE_PATH))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _registry_module = module
    return _registry_module


def _is_foreign_listing(symbol: str) -> bool:
    return bool(_EXCHANGE_RE.search(symbol or ""))


def build(reg: dict) -> dict:
    """등록부 → {"groups": [[회사, [심볼 …]]], "names": {심볼: 칩 이름}, "companies": {심볼: 정규 이름},
    "home": {심볼: 시세 조회 상장}}."""
    groups, names, companies, home = [], {}, {}, {}
    for company, e in (reg.get("companies") or {}).items():
        if not isinstance(e, dict) or not e.get("symbol"):
            continue
        listings = [x for x in e.get("other_listings") or [] if isinstance(x, dict) and x.get("symbol")]
        members = [e["symbol"], *[x["symbol"] for x in listings], *(e.get("other_symbols") or [])]
        name = e.get("chip_label") or company
        for m in members:
            names.setdefault(m, name)
            companies.setdefault(m, company)
        for x in listings:
            names[x["symbol"]] = x.get("chip_label") or name
        if len(members) < 2:
            continue
        foreign = [m for m in members if _is_foreign_listing(m)]
        main = e["symbol"] if _is_foreign_listing(e["symbol"]) else (foreign[0] if foreign else e["symbol"])
        for m in members:
            home[m] = main
        groups.append([company, members])
    return {"groups": groups, "names": names, "companies": companies, "home": home}


def _read_snapshot():
    try:
        data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        return data if data.get("groups") is not None else None
    except Exception:  # noqa: BLE001
        return None


def _write_snapshot(data) -> None:
    try:
        text = json.dumps(data, ensure_ascii=False)
        if SNAPSHOT_PATH.is_file() and SNAPSHOT_PATH.read_text(encoding="utf-8") == text:
            return
        tmp = SNAPSHOT_PATH.with_name(SNAPSHOT_PATH.name + f".{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, SNAPSHOT_PATH)
    except Exception:  # noqa: BLE001 — 사본은 부가 기능
        pass


def _table() -> dict:
    now = time.monotonic()
    if _state["data"] is not None and now - _state["checked"] < REFRESH_SECONDS:
        return _state["data"]
    _state["checked"] = now
    try:
        module = _registry()
        mtime = os.stat(module.REGISTRY_PATH).st_mtime_ns
    except Exception:  # noqa: BLE001
        module, mtime = None, None
    if _state["data"] is not None and mtime is not None and mtime == _state["mtime"] and _state["source"] == "registry":
        return _state["data"]
    data, source = None, "none"
    try:
        if module is not None:
            data = build(module.load())
            if data["groups"]:
                source = "registry"
                _write_snapshot(data)
            else:
                data = None
    except Exception:  # noqa: BLE001
        data = None
    if data is None:
        data = _read_snapshot()
        source = "snapshot" if data else "none"
    if data is None:
        if _state["data"] is not None:
            return _state["data"]        # 다시 읽기 실패 — 잘 돌던 표를 빈 표로 덮지 않는다
        data = {"groups": [], "names": {}, "companies": {}, "home": {}}
    _state.update(data=data, mtime=mtime, source=source)
    return data


def table_source() -> str:
    _table()
    return str(_state["source"])


def equivalents() -> dict[str, tuple[str, ...]]:
    """{심볼: (같은 회사의 다른 심볼 …)} — 묶음의 모든 심볼이 키(제목 보정의 '이미 들어 있음' 판정용)."""
    out: dict[str, tuple[str, ...]] = {}
    for _company, members in _table()["groups"]:
        for m in members:
            out[m] = tuple(x for x in members if x != m)
    for code, others in BARE_CODES.items():
        out[code] = tuple(dict.fromkeys((*out.get(code, ()), *others)))
    return out


def company_name(symbol: str, default: str = "") -> str:
    """등록부 정규 이름(영문 정식명 — 기사 company_name에 저장되는 이름)."""
    return (_table().get("companies") or {}).get(symbol, default)


def listings() -> dict:
    """칩 표시 표(프런트 /api/filters로 내려 준다): foreign {심볼: {home, name, byName}}, extra {심볼: [{ticker, name, byName}]}."""
    t = _table()
    home, names = t["home"], t["names"]

    def entry(symbol):
        h = home.get(symbol)
        if not h or h == symbol:
            return None
        return {"home": h, "name": names.get(h, h), **({"byName": True} if _ASIA_RE.search(h) else {})}

    foreign = {k: e for k in FOREIGN_KEYS if (e := entry(k))}
    extra = {}
    for k in EXTRA_KEYS:
        e = entry(k)
        if e:
            extra[k] = [{"ticker": e["home"], "name": e["name"], **({"byName": True} if e.get("byName") else {})}]
    return {"foreign": foreign, "extra": extra}

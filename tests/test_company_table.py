"""같은 회사 심볼 묶음·칩 표시 표를 증류 기업 등록부에서 만든다(company_table, 2026-11-11 기업 이름 표 통합 7단계)."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKE = '''
import json
from pathlib import Path
REGISTRY_PATH = Path(__file__).with_name("registry.json")
def load():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
'''
REG = {"companies": {
    "삼성전자": {"symbol": "005930.KS", "chip_label": "삼성전자", "other_symbols": ["SSNLF", "SSNNF"]},
    "Sony": {"symbol": "SONY", "other_symbols": ["6758.T", "SNEJF"]},
    "Airbus": {"symbol": "AIR.PA", "other_symbols": ["EADSY", "EADSF"]},
    "Ferrari": {"symbol": "RACE", "other_symbols": ["2FE.DE"]},
    "TSMC": {"symbol": "TSM", "other_listings": [{"symbol": "2330.TW", "chip_label": "TSMC"}]},
    "MediaTek": {"symbol": "2454.TW", "chip_label": "MediaTek", "other_symbols": ["MDTKF", "MDTKY"]},
    "Apple": {"symbol": "AAPL"}}}


def load_table(module, snapshot):
    os.environ["SA_COMPANY_REGISTRY_MODULE"], os.environ["SA_COMPANY_TABLE_SNAPSHOT"] = str(module), str(snapshot)
    try:
        spec = importlib.util.spec_from_file_location(f"ct_{os.urandom(3).hex()}", ROOT / "company_table.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        os.environ.pop("SA_COMPANY_REGISTRY_MODULE"); os.environ.pop("SA_COMPANY_TABLE_SNAPSHOT")
    m.REFRESH_SECONDS = 0
    return m


class CompanyTableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.module, self.reg, self.snap = d / "company_registry.py", d / "registry.json", d / "snap.json"
        self.module.write_text(FAKE, encoding="utf-8")
        self.reg.write_text(json.dumps(REG, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_listings_and_equivalents_come_from_the_registry(self):
        t = load_table(self.module, self.snap)
        L = t.listings()
        self.assertEqual(L["foreign"]["SSNLF"], {"home": "005930.KS", "name": "삼성전자", "byName": True})
        self.assertEqual(L["foreign"]["SONY"], {"home": "6758.T", "name": "Sony", "byName": True})   # 미국 심볼 회사 → 첫 해외 상장
        self.assertEqual(L["foreign"]["EADSY"], {"home": "AIR.PA", "name": "Airbus"})                 # 유럽은 티커 배지
        self.assertNotIn("MDTKY", L["foreign"])                                                       # 바꿀 심볼은 sa 규칙(FOREIGN_KEYS)
        self.assertEqual(L["extra"]["RACE"], [{"ticker": "2FE.DE", "name": "Ferrari"}])
        self.assertEqual(L["extra"]["TSM"], [{"ticker": "2330.TW", "name": "TSMC", "byName": True}])
        eq = t.equivalents()
        self.assertEqual(set(eq["2454.TW"]), {"MDTKF", "MDTKY"})
        self.assertEqual(eq["688825.SS"], ("688825",))                                               # 접미사 없는 코드는 sa 규칙
        self.assertNotIn("AAPL", eq)
        self.assertEqual(t.company_name("6758.T"), "Sony")

    def test_snapshot_is_used_when_the_registry_cannot_be_read(self):
        load_table(self.module, self.snap).listings()
        t = load_table(self.module.with_name("없음.py"), self.snap)
        self.assertEqual(t.table_source(), "snapshot")
        self.assertEqual(t.listings()["foreign"]["SSNLF"]["home"], "005930.KS")

    def test_nothing_breaks_without_registry_and_snapshot(self):
        t = load_table(self.module.with_name("없음.py"), self.snap.with_name("없음.json"))
        self.assertEqual(t.listings(), {"foreign": {}, "extra": {}})
        self.assertEqual(t.equivalents(), {"688825.SS": ("688825",)})

    def test_live_registry_covers_every_policy_key(self):
        import company_table as ct
        if ct.table_source() == "none":
            self.skipTest("등록부도 사본도 없는 환경")
        L = ct.listings()
        self.assertEqual(set(L["foreign"]), set(ct.FOREIGN_KEYS), "FOREIGN_KEYS 심볼은 등록부 other_symbols에 있어야 한다")
        self.assertEqual(set(L["extra"]), set(ct.EXTRA_KEYS))
        import db
        eq = ct.equivalents()
        for src, dst in db.TICKER_ALIASES.items():                 # 병합 방향(sa 규칙)은 등록부 묶음과 어긋나면 안 된다
            if src in eq and src.endswith((".KS",)):
                self.assertIn(dst, eq[src], (src, dst))


if __name__ == "__main__":
    unittest.main()

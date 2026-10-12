import unittest
from unittest.mock import patch
import foreign_tickers as ft


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = patch.object(ft, "portfolio_companies", return_value=[
            ("7974.T", "Nintendo", ("Nintendo",), ()),
            ("JPM", "JPMorgan", ("JPMorgan",), ()),
            ("2330.TW", "TSMC", ("TSMC",), ()),
        ])
        self.catalog.start()
        self.addCleanup(self.catalog.stop)

    def test_new_company(self):
        self.assertEqual(ft.missing_from_title("Nintendo raises sales outlook", []), [("7974.T", "Nintendo")])
        self.assertEqual(ft.missing_from_title("Nintendo earnings beat", []), [("7974.T", "Nintendo")])

    def test_provider_and_comparison(self):
        for title in ("Apple upgraded by analysts at JPMorgan", "JPMorgan upgrades Apple", "Apple gains compared with Nintendo"):
            self.assertEqual(ft.missing_from_title(title, ["AAPL"]), [])

    def test_adr_equivalent(self):
        self.assertEqual(ft.missing_from_title("TSMC earnings beat", ["TSM"]), [])

    def test_pairs_fill_missing_name(self):
        self.assertEqual(ft.supplement_pairs("Nintendo earnings beat", "AAPL", ""), ("AAPL, 7974.T", "AAPL·Nintendo"))

    def test_idempotent(self):
        first = ft.supplement_pairs("Nintendo earnings beat", "", "")
        self.assertEqual(ft.supplement_pairs("Nintendo earnings beat", *first), first)

    def test_etf_name_is_not_underlying_company(self):
        self.assertEqual(ft.missing_from_title("Nintendo Yield Shares Purpose ETF declares dividend", []), [])

    def test_suffix_research_attribution(self):
        self.assertEqual(ft.missing_from_title("Apple has upside - JPMorgan", ["AAPL"]), [])

    def test_adr_and_parent_brand_collisions(self):
        with patch.object(ft, "portfolio_companies", return_value=[
            ("9984.T", "SoftBank", ("SoftBank",), ()),
            ("LDO.MI", "Leonardo", ("Leonardo",), ()),
            ("BLK", "BlackRock", ("BlackRock",), ())]):
            self.assertEqual(ft.missing_from_title("SoftBank raises capital", ["SFTBY"]), [])
            self.assertEqual(ft.missing_from_title("Leonardo DRS wins contract", ["DRS"]), [])
            self.assertEqual(ft.missing_from_title("BlackRock TCP CEO resigns", ["TCPC"]), [])


class CxmtTests(unittest.TestCase):
    """sa 9081(2026-10-12): 카탈로그 이름이 전부 대문자라 빠지던 CXMT를 직접 등록."""

    def test_cxmt_and_changxin_titles_get_chip(self):
        import foreign_tickers
        self.assertEqual(foreign_tickers.missing_from_title(
            "SKHY: China’s CXMT makes ‘key progress’ on new chip structure: SCMP", ["SSNLF", "SKHY"]),
            [("688825.SS", "CXMT")])
        self.assertEqual(foreign_tickers.missing_from_title("MU: ChangXin hopes to raise $8.5B in IPO", ["MU"]),
                         [("688825.SS", "CXMT")])
        self.assertEqual(foreign_tickers.missing_from_title("CXMT plans plant", ["688825.SS"]), [])


if __name__ == "__main__":
    unittest.main()


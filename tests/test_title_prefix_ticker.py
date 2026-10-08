import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import sa_summarize_claude as m  # noqa: E402


class TitlePrefixTickerTests(unittest.TestCase):
    """제목 앞 티커는 기본으로 칩에 넣는다(2026-10-08, 9360 'FDX: ... upgrades XPO')."""

    def test_prefix_ticker_is_appended_after_model_tickers(self):
        self.assertEqual(m.merge_title_prefix("XPO", "XPO, Inc.", "FDX: Citi Research sees opportunities in trucking, upgrades XPO to Buy")[0],
                         "XPO, FDX")

    def test_class_alias_is_not_duplicated(self):
        self.assertEqual(m.merge_title_prefix("OPENAI, GOOG, META", "OpenAI·Alphabet·Meta",
                                              "GOOGL: ChatGPT, Gemini see daily active user increases")[0], "OPENAI, GOOG, META")

    def test_multi_prefix_and_company_slots_align(self):
        t, c = m.merge_title_prefix("NVDA", "Nvidia", "AMD, INTC: Chip stocks rally")
        self.assertEqual(t.split(", ")[:1], ["NVDA"])
        self.assertEqual(len(t.split(", ")), len(c.split("·")))

    def test_no_prefix_no_change(self):
        self.assertEqual(m.merge_title_prefix("AAPL", "Apple", "Apple unveils new iPhone"), ("AAPL", "Apple"))


if __name__ == "__main__":
    unittest.main()

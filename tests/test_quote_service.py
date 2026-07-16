import unittest
from unittest.mock import patch

import quote_service


class QuoteServiceTests(unittest.TestCase):
    def test_normalize_ticker(self):
        self.assertEqual(quote_service.normalize_ticker(" goog "), "GOOGL")
        self.assertEqual(quote_service.normalize_ticker("005930.KS"), "005930.KS")
        for invalid in ("", "AAPL/../../x", "AAPL B", "AAPL?debug=true"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(quote_service.InvalidTickerError):
                    quote_service.normalize_ticker(invalid)

    @patch.object(quote_service, "_fallback_name", return_value="Alphabet")
    @patch.object(quote_service, "_fetch_raw", return_value=None)
    def test_unavailable_quote_has_stable_shape(self, _fetch, _name):
        result = quote_service.get_price_quote("GOOG")
        self.assertFalse(result["found"])
        self.assertEqual(result["ticker"], "GOOGL")
        self.assertEqual(result["name"], "Alphabet")

    @patch.object(quote_service, "_fallback_name", return_value="")
    @patch.object(
        quote_service,
        "_fetch_raw",
        return_value={
            "ticker": "AAPL",
            "name": "Apple",
            "current_price": "102",
            "previous_price": "100",
            "change": "2",
            "extended_price": "not-a-number",
            "extended_change_pct": "1.2",
            "market": {"is_regular": False, "label": "장외", "status": "post"},
        },
    )
    def test_malformed_extended_price_does_not_break_quote(self, _fetch, _name):
        result = quote_service.get_price_quote("AAPL")
        self.assertTrue(result["found"])
        self.assertEqual(result["change_pct"], 2.0)
        self.assertIsNone(result["extended_change_pct"])


if __name__ == "__main__":
    unittest.main()

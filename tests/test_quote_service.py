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
        # extended_price는 더 이상 병기 조건에 쓰지 않는다 → 값이 깨져도
        # 유효한 extended_change_pct는 그대로 살린다.
        self.assertEqual(result["extended_change_pct"], 1.2)

    @patch.object(quote_service, "_fallback_name", return_value="")
    @patch.object(
        quote_service,
        "_fetch_raw",
        return_value={
            "ticker": "PLTR",
            "name": "Palantir",
            # 장외 급등: current(=장외가) 143.66 vs 정규장 종가 기준 raw.change(2.59)
            "current_price": 143.66,
            "previous_price": 123.06,
            "change": 2.59,
            "change_pct": 2.1046,
            "extended_price": 143.66,
            "extended_change_pct": 14.3334,
            "market": {"is_regular": False, "label": "장외", "status": "open"},
        },
    )
    def test_large_after_hours_move_keeps_both_lines(self, _fetch, _name):
        """애프터장 변동이 커도 장외 병기가 사라지지 않고, 전일대비는 표시가 기준."""
        result = quote_service.get_price_quote("PLTR")
        # 전일대비는 raw.change_pct(2.10, 정규장 구간)가 아니라 표시가 기준
        self.assertAlmostEqual(result["change_pct"], 16.7398, places=3)
        self.assertAlmostEqual(result["extended_change_pct"], 14.3334, places=3)

    @patch.object(quote_service, "_fallback_name", return_value="")
    @patch.object(
        quote_service,
        "_fetch_raw",
        return_value={
            "ticker": "AAPL",
            "name": "Apple",
            "current_price": 102.0,
            "previous_price": 100.0,
            "change": 2.0,
            "extended_price": 102.0,
            "extended_change_pct": 1.9999,
            "market": {"is_regular": True, "label": "정규장", "status": "open"},
        },
    )
    def test_regular_hours_has_no_extended_line(self, _fetch, _name):
        result = quote_service.get_price_quote("AAPL")
        self.assertEqual(result["change_pct"], 2.0)
        self.assertIsNone(result["extended_change_pct"])

    @patch.object(quote_service, "_fallback_name", return_value="")
    @patch.object(
        quote_service,
        "_fetch_raw",
        return_value={
            "ticker": "AAPL",
            "name": "Apple",
            # 프리장: 정규장 구간이 없어 전일대비와 장외 등락이 사실상 동일 → 중복 병기 생략
            "current_price": 102.0,
            "previous_price": 100.0,
            "change": 2.0,
            "extended_price": 102.0,
            "extended_change_pct": 2.0,
            "market": {"is_regular": False, "label": "장외", "status": "open"},
        },
    )
    def test_duplicate_extended_line_is_suppressed(self, _fetch, _name):
        result = quote_service.get_price_quote("AAPL")
        self.assertEqual(result["change_pct"], 2.0)
        self.assertIsNone(result["extended_change_pct"])


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from scripts import sa_claude_cli, sa_summarize_claude


class SummaryPipelineTests(unittest.TestCase):
    def test_validate_normalizes_tickers_and_markdown(self):
        result = sa_summarize_claude.validate(
            {
                "ticker": "googl, GOOG, 005930.KS, bad ticker",
                "company_name": "**Alphabet**·삼성전자",
                "headline": "[Alphabet](https://example.com), 서비스_공개",
                "summary_details": ["**첫째**", "둘째"],
                "ticker_color": "GREEN",
            }
        )
        self.assertEqual(result["ticker"], "GOOGL, GOOG, 005930.KS")
        self.assertEqual(result["company_name"], "Alphabet·삼성전자")
        self.assertEqual(result["headline"], "Alphabet, 서비스 공개")
        self.assertEqual(result["summary_details"], ["첫째", "둘째"])
        self.assertEqual(result["ticker_color"], "green")

    def test_validate_rejects_han_and_kana(self):
        for contaminated in ("売上 증가", "メーカー 전망"):
            with self.subTest(contaminated=contaminated):
                with self.assertRaises(ValueError):
                    sa_summarize_claude.validate(
                        {"headline": contaminated, "summary_details": ["정상 문장"]}
                    )

    def test_parse_claude_stream_prefers_result_event(self):
        output = "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "model": "claude-opus-4-8",
                            "content": [{"type": "text", "text": "draft"}],
                        },
                    }
                ),
                json.dumps({"type": "result", "subtype": "success", "result": "final"}),
            ]
        )
        self.assertEqual(
            sa_claude_cli._parse_claude_stream(output),
            ("final", "claude-opus-4-8"),
        )


if __name__ == "__main__":
    unittest.main()

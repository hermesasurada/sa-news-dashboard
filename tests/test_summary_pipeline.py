import contextlib
import io
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
import ticker_names
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

    def test_call_claude_timeout_returns_empty_result(self):
        expired = subprocess.TimeoutExpired(cmd="claude", timeout=1)
        with (
            patch.object(sa_claude_cli.subprocess, "run", side_effect=expired),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            result = sa_claude_cli.call_claude("test", timeout=1)
        self.assertEqual(result, (None, None))


class BatchResilienceTests(unittest.TestCase):
    def setUp(self):
        self._original_path = db.DB_PATH
        self._tempdir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tempdir.name) / "summary.db"
        with contextlib.redirect_stdout(io.StringIO()):
            db.init_db()

    def tearDown(self):
        db.DB_PATH = self._original_path
        self._tempdir.cleanup()

    def _pending(self, email_id: str, minute: int) -> int:
        article_id = db.insert_pending_article(
            email_id=email_id,
            ticker="AAPL",
            article_url=f"https://seekingalpha.com/news/{email_id}-test",
            original_title=f"AAPL: test {email_id}",
            email_time_et=f"2026-08-01 01:{minute:02d} KST",
        )
        self.assertIsNotNone(article_id)
        return int(article_id)

    @staticmethod
    def _response(headline: str) -> str:
        return json.dumps(
            {
                "ticker": "AAPL",
                "company_name": "Apple",
                "headline": headline,
                "summary_details": ["첫 번째", "두 번째", "세 번째", "네 번째"],
                "ticker_color": "blue",
            },
            ensure_ascii=False,
        )

    def _row(self, article_id: int):
        with db.get_conn() as conn:
            return conn.execute(
                "SELECT * FROM articles WHERE id = ?", (article_id,)
            ).fetchone()

    def test_claude_timeout_grok_success_publishes_and_continues(self):
        first = self._pending("9101", 1)
        second = self._pending("9102", 2)
        with (
            patch.object(
                sa_summarize_claude,
                "parse_article",
                return_value=("article body", "sa_api", [], None),
            ),
            patch.object(
                sa_summarize_claude,
                "call_claude",
                side_effect=[(None, None), (self._response("둘째 기사"), "claude-opus-5")],
            ),
            patch.object(
                sa_summarize_claude,
                "call_grok",
                return_value=(self._response("첫 기사"), "grok-4.5"),
            ) as grok,
            patch.object(ticker_names, "fill_company", side_effect=lambda _t, c: c),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            result = sa_summarize_claude.run_batch(2)

        self.assertEqual((result.succeeded, result.failed), (2, 0))
        self.assertEqual(grok.call_count, 1)
        self.assertEqual(self._row(first)["pub_status"], db.STATUS_PUBLISHED)
        self.assertEqual(self._row(first)["summary_model"], "grok-4.5")
        self.assertEqual(self._row(first)["retry_count"], 0)
        self.assertEqual(self._row(second)["pub_status"], db.STATUS_PUBLISHED)
        self.assertEqual(self._row(second)["summary_model"], "claude-opus-5")

    def test_both_models_fail_records_once_and_continues(self):
        first = self._pending("9201", 1)
        second = self._pending("9202", 2)
        with (
            patch.object(
                sa_summarize_claude,
                "parse_article",
                return_value=("article body", "sa_api", [], None),
            ),
            patch.object(
                sa_summarize_claude,
                "call_claude",
                side_effect=[(None, None), (self._response("둘째 기사"), "claude-opus-5")],
            ),
            patch.object(sa_summarize_claude, "call_grok", return_value=(None, None)),
            patch.object(ticker_names, "fill_company", side_effect=lambda _t, c: c),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            result = sa_summarize_claude.run_batch(2)

        first_row = self._row(first)
        self.assertEqual((result.succeeded, result.failed), (1, 1))
        self.assertEqual(first_row["pub_status"], db.STATUS_PENDING)
        self.assertEqual(first_row["retry_count"], 1)
        self.assertTrue(first_row["last_attempt"])
        self.assertIn("Claude/grok", first_row["fail_reason"])
        self.assertEqual(self._row(second)["pub_status"], db.STATUS_PUBLISHED)
        self.assertNotIn(first, [row["id"] for row in db.get_pending_due(batch_size=10)])

    def test_unexpected_article_error_records_once_and_continues(self):
        first = self._pending("9301", 1)
        second = self._pending("9302", 2)
        success = sa_summarize_claude.AttemptSuccess(
            ticker="AAPL",
            company_name="Apple",
            headline="둘째 기사",
            summary_details=["상세"],
            ticker_color="blue",
            parse_method="sa_api",
            summary_model="claude-opus-5",
        )
        with (
            patch.object(
                sa_summarize_claude,
                "attempt_article",
                side_effect=[RuntimeError("boom"), success],
            ),
            patch.object(ticker_names, "fill_company", side_effect=lambda _t, c: c),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            result = sa_summarize_claude.run_batch(2)

        self.assertEqual((result.succeeded, result.failed), (1, 1))
        self.assertEqual(self._row(first)["retry_count"], 1)
        self.assertIn("예상하지 못한", self._row(first)["fail_reason"])
        self.assertEqual(self._row(second)["pub_status"], db.STATUS_PUBLISHED)

    def test_main_returns_infrastructure_exit_for_database_error(self):
        with (
            patch.object(
                sa_summarize_claude,
                "single_instance",
                return_value=contextlib.nullcontext(True),
            ),
            patch.object(
                sa_summarize_claude.db,
                "get_pending_due",
                side_effect=sqlite3.OperationalError("db down"),
            ),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exit_code = sa_summarize_claude.main(["--batch", "2"])
        self.assertEqual(exit_code, sa_summarize_claude.EXIT_INFRA_FAILURE)

    def test_main_returns_partial_exit_for_recorded_article_failure(self):
        result = sa_summarize_claude.BatchResult(attempted=2, succeeded=1, failed=1)
        with (
            patch.object(
                sa_summarize_claude,
                "single_instance",
                return_value=contextlib.nullcontext(True),
            ),
            patch.object(sa_summarize_claude, "run_batch", return_value=result),
        ):
            exit_code = sa_summarize_claude.main(["--batch", "2"])
        self.assertEqual(exit_code, sa_summarize_claude.EXIT_PARTIAL_FAILURE)


if __name__ == "__main__":
    unittest.main()

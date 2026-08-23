import contextlib
import io
import json
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import db
import settings
import ticker_names
from scripts import sa_claude_cli, sa_publish, sa_summarize_claude


class RoundRobinTests(unittest.TestCase):
    """요약 모델 라운드로빈 배정 — 기사 id 홀짝으로 1차/폴백이 뒤바뀐다."""

    def setUp(self):
        self._rr = settings.SUMMARY_ROUND_ROBIN
        settings.SUMMARY_ROUND_ROBIN = True

    def tearDown(self):
        settings.SUMMARY_ROUND_ROBIN = self._rr

    def test_alternates_primary_by_article_id(self):
        even = sa_summarize_claude.pick_summarizers(100)
        odd = sa_summarize_claude.pick_summarizers(101)
        self.assertEqual(even[0], "Claude")
        self.assertEqual(even[1], sa_summarize_claude.call_claude)
        self.assertEqual(even[2], "grok")
        self.assertEqual(odd[0], "grok")
        self.assertEqual(odd[1], sa_summarize_claude.call_grok)
        self.assertEqual(odd[2], "Claude")

    def test_consecutive_ids_alternate(self):
        picks = [sa_summarize_claude.pick_summarizers(i)[0] for i in range(10, 16)]
        self.assertEqual(picks, ["Claude", "grok", "Claude", "grok", "Claude", "grok"])

    def test_disabled_always_uses_claude_first(self):
        settings.SUMMARY_ROUND_ROBIN = False
        for article_id in (100, 101, 102, 103):
            self.assertEqual(sa_summarize_claude.pick_summarizers(article_id)[0], "Claude")


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

    def test_prompt_uses_only_collected_source_and_does_not_pad(self):
        prompt = sa_summarize_claude._PROMPT_TMPL
        self.assertIn("SA 사이트 수집본만", prompt)
        self.assertIn("항목 수를 채우려고 내용을 늘리지 말 것", prompt)
        self.assertIn("한 항목에 사실 하나만", prompt)
        self.assertIn("완결형 종결은 쓰지 말 것", prompt)
        self.assertIn("명사구·체언 종결", prompt)
        self.assertIn("사전 지식", prompt)
        self.assertNotIn("4~6개", prompt)
        self.assertNotIn("핵심 정보를 반드시 포함", prompt)
        self.assertNotIn("짧은 완결 문장", prompt)

    def test_validate_accepts_one_detail_sentence(self):
        result = sa_summarize_claude.validate(
            {
                "ticker": "WBD",
                "company_name": "Warner Bros. Discovery",
                "headline": "Paramount, 월요일 법무장관 회동",
                "summary_details": ["Variety는 월요일 회동 예정이라고 보도했다."],
                "ticker_color": "blue",
            }
        )
        self.assertEqual(len(result["summary_details"]), 1)

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


class GrokModelDetectionTests(unittest.TestCase):
    """grok 기본 모델 탐지 — 간헐 실패로 버전('grok-4.5')이 소실되지 않아야 한다."""

    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self._orig_cache = sa_claude_cli.GROK_MODEL_CACHE
        sa_claude_cli.GROK_MODEL_CACHE = Path(self._tempdir.name) / "grok_model.json"
        sa_claude_cli._GROK_DEFAULT_MODEL = None   # 프로세스 메모리 캐시 초기화

    def tearDown(self):
        sa_claude_cli.GROK_MODEL_CACHE = self._orig_cache
        sa_claude_cli._GROK_DEFAULT_MODEL = None
        self._tempdir.cleanup()

    def test_probe_success_is_cached_to_disk(self):
        with patch.object(sa_claude_cli, "_probe_grok_model", return_value="grok-4.5"):
            self.assertEqual(sa_claude_cli._grok_default_model(), "grok-4.5")
        self.assertTrue(sa_claude_cli.GROK_MODEL_CACHE.exists())
        cached, _fresh = sa_claude_cli._read_grok_model_cache()
        self.assertEqual(cached, "grok-4.5")

    def test_probe_failure_falls_back_to_stale_cache(self):
        # 어제 저장된(만료된) 캐시가 있으면 탐지 실패해도 버전을 유지한다.
        sa_claude_cli.GROK_MODEL_CACHE.write_text(
            json.dumps({"model": "grok-4.5", "fetched_at": time.time() - 86400 * 5}),
            encoding="utf-8",
        )
        with (
            patch.object(sa_claude_cli, "_probe_grok_model", return_value=None),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(sa_claude_cli._grok_default_model(), "grok-4.5")

    def test_probe_failure_without_cache_marks_unknown(self):
        with (
            patch.object(sa_claude_cli, "_probe_grok_model", return_value=None),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(sa_claude_cli._grok_default_model(), sa_claude_cli.GROK_MODEL_UNKNOWN)

    def test_fresh_cache_skips_probe(self):
        sa_claude_cli.GROK_MODEL_CACHE.write_text(
            json.dumps({"model": "grok-9", "fetched_at": time.time()}), encoding="utf-8"
        )
        with patch.object(sa_claude_cli, "_probe_grok_model") as probe:
            self.assertEqual(sa_claude_cli._grok_default_model(), "grok-9")
        probe.assert_not_called()

    def test_probe_retries_once_on_transient_failure(self):
        ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="Default model: grok-4.5\n", stderr="")
        with patch.object(
            sa_claude_cli.subprocess, "run",
            side_effect=[subprocess.TimeoutExpired(cmd="grok", timeout=1), ok],
        ):
            self.assertEqual(sa_claude_cli._probe_grok_model(), "grok-4.5")


class BatchResilienceTests(unittest.TestCase):
    def setUp(self):
        self._original_path = db.DB_PATH
        self._tempdir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tempdir.name) / "summary.db"
        with contextlib.redirect_stdout(io.StringIO()):
            db.init_db()
        # 배치 격리·폴백 자체를 검증하는 테스트이므로 1차 모델을 Claude로 고정한다.
        # (라운드로빈 배정 규칙은 RoundRobinTests에서 별도로 검증)
        self._rr = settings.SUMMARY_ROUND_ROBIN
        settings.SUMMARY_ROUND_ROBIN = False
        self._gap = settings.ARTICLE_GAP_SECONDS
        settings.ARTICLE_GAP_SECONDS = 0

    def tearDown(self):
        settings.SUMMARY_ROUND_ROBIN = self._rr
        settings.ARTICLE_GAP_SECONDS = self._gap
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
                return_value=("article body " * 80, "playwright_auth", [], None),
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
                return_value=("article body " * 80, "playwright_auth", [], None),
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

    def test_batch_waits_between_articles(self):
        self._pending("9401", 1)
        self._pending("9402", 2)
        settings.ARTICLE_GAP_SECONDS = 20
        with (
            patch.object(sa_summarize_claude, "process_article", return_value=True) as proc,
            patch.object(sa_summarize_claude.time, "sleep") as slept,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            sa_summarize_claude.run_batch(2)
        self.assertEqual(proc.call_count, 2)
        slept.assert_called_once_with(20)


class ParseUsesSiteTests(unittest.TestCase):
    def setUp(self):
        self._original_path = db.DB_PATH
        self._tempdir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tempdir.name) / "parse.db"
        with contextlib.redirect_stdout(io.StringIO()):
            db.init_db()

    def tearDown(self):
        db.DB_PATH = self._original_path
        self._tempdir.cleanup()

    def test_parse_fetches_article_url(self):
        article_id = db.insert_pending_article(
            email_id="6492",
            ticker="WBD",
            article_url="https://seekingalpha.com/news/4636039-paramount",
            original_title="WBD: Paramount to meet California AG",
            email_time_et="2026-08-22 22:21 KST",
        )
        fake = {
            "success": True,
            "content": "SITE FULL ARTICLE " * 80,
            "method": "sa_api_auth",
            "tickers": [{"symbol": "WBD", "name": "Warner Bros. Discovery"}],
        }
        with patch(
            "sa_article_parser.parse_sa_article", return_value=fake
        ) as mocked:
            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                sa_publish.cmd_parse(int(article_id))
        mocked.assert_called_once_with(
            "https://seekingalpha.com/news/4636039-paramount"
        )
        stdout = out.getvalue()
        stderr = err.getvalue()
        self.assertIn("SITE FULL ARTICLE", stdout)
        self.assertIn("PARSE_METHOD: sa_api_auth", stderr)
        self.assertIn("WBD", stderr)
        src = db.get_source(int(article_id))
        self.assertIsNotNone(src)
        self.assertGreaterEqual(src["chars"], settings.SOURCE_MIN_CHARS)
        self.assertFalse(src["locked"])

    def test_reuse_source_skips_sa_fetch(self):
        article_id = db.insert_pending_article(
            email_id="6493",
            ticker="MRVL",
            article_url="https://seekingalpha.com/news/2-test",
            original_title="MRVL: test",
            email_time_et="2026-08-22 21:00 KST",
        )
        body = "Marvell reported stronger hyperscaler demand. " * 40
        db.save_source(int(article_id), text=body, method="playwright_auth", locked=False)
        content, method, tickers, err = sa_summarize_claude.parse_article(
            int(article_id), reuse_source=True
        )
        self.assertIsNone(err)
        self.assertEqual(method, "playwright_auth")
        self.assertEqual(content, body)
        self.assertEqual(tickers, [])

    def test_reuse_source_rejects_locked_preview(self):
        article_id = db.insert_pending_article(
            email_id="6494",
            ticker="WBD",
            article_url="https://seekingalpha.com/news/3-test",
            original_title="WBD: test",
            email_time_et="2026-08-22 21:00 KST",
        )
        db.save_source(int(article_id), text="preview only", method="sa_api", locked=True)
        content, method, tickers, err = sa_summarize_claude.parse_article(
            int(article_id), reuse_source=True
        )
        self.assertIsNone(content)
        self.assertIn("품질 미달", err)


if __name__ == "__main__":
    unittest.main()

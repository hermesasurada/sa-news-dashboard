import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sa_article_parser as parser
import settings


class CookieLoadTests(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.get("SA_COOKIES_PATH")
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "sa_cookies.json"
        os.environ["SA_COOKIES_PATH"] = str(self.path)

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("SA_COOKIES_PATH", None)
        else:
            os.environ["SA_COOKIES_PATH"] = self._prev
        self.dir.cleanup()

    def _write(self, cookies):
        self.path.write_text(json.dumps(cookies), encoding="utf-8")

    def test_keeps_seekingalpha_login_cookies_and_skips_expired_foreign(self):
        self._write(
            [
                {"name": "user_id", "value": "1", "domain": "seekingalpha.com", "path": "/", "expires": -1},
                {"name": "user_remember_token", "value": "tok", "domain": ".seekingalpha.com", "path": "/", "expires": 9_999_999_999, "httpOnly": True, "secure": True, "sameSite": "Lax"},
                {"name": "SID", "value": "g", "domain": ".google.com", "path": "/", "expires": -1},
                {"name": "old", "value": "x", "domain": "seekingalpha.com", "path": "/", "expires": 1},
            ]
        )
        loaded = parser.load_sa_cookies()
        names = {c["name"] for c in loaded}
        self.assertEqual(names, {"user_id", "user_remember_token"})
        self.assertTrue(parser.has_login_cookies(loaded))
        header = parser.cookie_header(loaded)
        self.assertIn("user_id=1", header)
        self.assertIn("user_remember_token=tok", header)

    def test_korean_locale_is_forced_to_english_original(self):
        """계정 언어 ko면 SA가 번역판(앞부분만)을 준다 — 영문 원문으로 고정(2026-10-10)."""
        self._write([{"name": "user_locale", "value": "ko", "domain": ".seekingalpha.com", "path": "/", "expires": -1}])
        self.assertEqual([c["value"] for c in parser.load_sa_cookies()], ["en"])

    def test_missing_file_is_anonymous(self):
        self.assertEqual(parser.load_sa_cookies(), [])
        self.assertFalse(parser.has_login_cookies([]))


class AuthenticatedApiTests(unittest.TestCase):
    def test_sends_cookie_header_and_rejects_locked_preview(self):
        cookies = [{"name": "user_id", "value": "1", "domain": "seekingalpha.com"}]
        payload = {
            "data": {
                "attributes": {
                    "title": "Headline",
                    "content": "<p>" + ("preview " * 20) + "</p>",
                    "isMpwLocked": True,
                    "isPaywalled": False,
                    "isLockedPro": False,
                },
                "relationships": {"primaryTickers": {"data": []}},
            },
            "included": [],
        }
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        with patch.object(parser.curl_requests, "get", return_value=resp) as get:
            rejected = parser.parse_with_sa_api(
                "https://seekingalpha.com/news/4636038-x",
                cookies=cookies,
                reject_locked_preview=True,
            )
            self.assertTrue(rejected["rejected"])
            self.assertTrue(rejected["locked"])
            self.assertEqual(rejected["method"], "sa_api_auth")
            kwargs = get.call_args.kwargs
            self.assertIn("Cookie", kwargs["headers"])
            self.assertIn("user_id=1", kwargs["headers"]["Cookie"])

            accepted = parser.parse_with_sa_api(
                "https://seekingalpha.com/news/4636038-x",
                cookies=None,
                reject_locked_preview=False,
            )
            self.assertEqual(accepted["method"], "sa_api")
            self.assertGreater(len(accepted["content"]), 80)

    def test_unlocked_auth_body_is_kept(self):
        cookies = [{"name": "user_remember_token", "value": "tok", "domain": "seekingalpha.com"}]
        body = "<p>" + ("full article paragraph. " * 80) + "</p>"
        payload = {
            "data": {
                "attributes": {
                    "title": "Full",
                    "content": body,
                    "isMpwLocked": False,
                    "isPaywalled": False,
                    "isLockedPro": False,
                },
                "relationships": {"primaryTickers": {"data": []}},
            },
            "included": [],
        }
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        with patch.object(parser.curl_requests, "get", return_value=resp):
            result = parser.parse_with_sa_api(
                "https://seekingalpha.com/news/1-x",
                cookies=cookies,
                reject_locked_preview=True,
            )
        self.assertEqual(result["method"], "sa_api_auth")
        self.assertGreater(len(result["content"]), parser._min_chars())


class FetchOrderTests(unittest.TestCase):
    """단계 순서 검증. 실제 로그인 상태 파일에 좌우되면 안 되므로 격리한다.

    폴백(degraded) 중에는 익명 경로가 설정과 무관하게 열리도록 돼 있어서,
    상태 파일을 그대로 두면 '익명은 기본적으로 호출되지 않는다'가 깨진다."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self._patch = patch.object(
            settings, "LOGIN_STATE_PATH", Path(self._dir.name) / "state.json"
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._dir.cleanup()

    def test_playwright_is_tried_before_api_and_wins(self):
        full = {"method": "playwright_auth", "content": "P" * 800, "tickers": []}
        with (
            patch.object(parser, "_og_lead", return_value=""),
            patch.object(parser, "load_sa_cookies", return_value=[{"name": "user_id", "value": "1"}]),
            patch.object(parser, "has_login_cookies", return_value=True),
            patch.object(parser, "parse_with_playwright_stealth", return_value=full) as pw,
            patch.object(parser, "parse_with_curl_cffi_rotated") as curl,
            patch.object(parser, "parse_with_sa_api") as api,
            patch.object(parser, "parse_with_jina_reader") as jina,
        ):
            result = parser.parse_sa_article("https://seekingalpha.com/news/1-x")
        self.assertTrue(result["success"])
        self.assertEqual(result["method"], "playwright_auth")
        pw.assert_called_once()
        curl.assert_not_called()
        api.assert_not_called()
        jina.assert_not_called()
        self.assertTrue(result["attempts"][0]["accepted"])

    def test_short_preview_is_not_success_without_anon(self):
        short = {"method": "playwright_auth", "content": "s" * 200, "locked": True}
        with (
            patch.object(parser, "_og_lead", return_value=""),
            patch.object(parser, "load_sa_cookies", return_value=[{"name": "user_id", "value": "1"}]),
            patch.object(parser, "has_login_cookies", return_value=True),
            patch.object(parser, "parse_with_playwright_stealth", return_value=short),
            patch.object(parser, "parse_with_curl_cffi_rotated", return_value=None),
            patch.object(
                parser,
                "parse_with_sa_api",
                return_value={"method": "sa_api_auth", "content": "a" * 200, "locked": True, "rejected": True},
            ),
            patch.object(parser, "parse_with_jina_reader", return_value=None),
            patch.object(parser.settings, "ALLOW_ANON_FETCH", False),
        ):
            result = parser.parse_sa_article("https://seekingalpha.com/news/1-x")
        self.assertFalse(result["success"])
        self.assertIn("preview-only", result["error"])
        self.assertFalse(any(a["accepted"] for a in result["attempts"]))

    def test_anon_api_not_called_by_default(self):
        with (
            patch.object(parser, "_og_lead", return_value=""),
            patch.object(parser, "load_sa_cookies", return_value=[]),
            patch.object(parser, "has_login_cookies", return_value=False),
            patch.object(parser, "parse_with_jina_reader", return_value=None),
            patch.object(parser, "parse_with_sa_api") as api,
            patch.object(parser.settings, "ALLOW_ANON_FETCH", False),
        ):
            result = parser.parse_sa_article("https://seekingalpha.com/news/1-x")
        api.assert_not_called()
        self.assertFalse(result["success"])


class NoLoginWarningTests(unittest.TestCase):
    """로그인 세션이 없으면 조용히 프리뷰로 떨어지지 않고 stderr로 원인을 알린다."""

    def _run(self, cookies_file, login):
        import contextlib, io
        err = io.StringIO()
        with patch.dict(os.environ, {"SA_COOKIES_PATH": cookies_file}), \
             patch.object(parser, "has_login_cookies", return_value=login), \
             patch.object(parser, "load_sa_cookies", return_value=[]), \
             patch.object(parser, "_og_lead", return_value=""), \
             patch.object(parser, "parse_with_jina_reader", return_value=None), \
             patch.object(parser, "parse_with_playwright_stealth", return_value=None), \
             patch.object(parser, "parse_with_curl_cffi_rotated", return_value=None), \
             patch.object(parser, "parse_with_sa_api", return_value=None), \
             patch.object(parser.settings, "ALLOW_ANON_FETCH", False), \
             contextlib.redirect_stderr(err):
            parser.parse_sa_article("https://seekingalpha.com/news/1-x")
        return err.getvalue()

    def test_warns_when_cookie_file_missing(self):
        with tempfile.TemporaryDirectory() as d:
            out = self._run(os.path.join(d, "nope.json"), False)
        self.assertIn("SA 로그인 세션 없음", out)
        self.assertIn("쿠키 파일 없음", out)
        self.assertIn("sa_refresh_login.py", out)

    def test_warns_when_login_cookies_expired(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sa_cookies.json")
            Path(path).write_text("[]", encoding="utf-8")
            out = self._run(path, False)
        self.assertIn("만료/무효", out)

    def test_no_warning_when_logged_in(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sa_cookies.json")
            Path(path).write_text("[]", encoding="utf-8")
            out = self._run(path, True)
        self.assertNotIn("SA 로그인 세션 없음", out)


if __name__ == "__main__":
    unittest.main()


class BlockGuardTests(unittest.TestCase):
    """SA 봇 확인 화면(PerimeterX) 쿨다운(2026-10-10)."""

    def setUp(self):
        import sa_block_guard
        self.guard = sa_block_guard
        self.dir = tempfile.TemporaryDirectory()
        self._prev = settings.BLOCK_STATE_PATH
        settings.BLOCK_STATE_PATH = Path(self.dir.name) / "block.json"

    def tearDown(self):
        settings.BLOCK_STATE_PATH = self._prev
        self.dir.cleanup()

    def test_detects_px_page_only(self):
        page = "<title>Access to this page has been denied</title> Press & Hold to confirm you are a human"
        self.assertTrue(self.guard.is_block_page(403, page))
        self.assertTrue(self.guard.is_block_page(429, ""))
        self.assertFalse(self.guard.is_block_page(403, "<html>Forbidden</html>"))
        self.assertFalse(self.guard.is_block_page(200, page))

    def test_cooldown_is_fixed_even_when_repeated(self):
        """연속 차단이어도 쉬는 시간은 늘리지 않는다(2026-10-10 사용자 지시)."""
        with patch("sys.stdout"), patch("sys.stderr"):
            self.assertEqual(self.guard.record_block("t"), settings.BLOCK_COOLDOWN_MINUTES)
            self.assertEqual(self.guard.record_block("t"), settings.BLOCK_COOLDOWN_MINUTES)
        self.assertEqual(self.guard.load_state()["consecutive_blocks"], 2)
        self.assertGreater(self.guard.remaining_seconds(), 0)
        self.guard.record_ok()
        self.assertEqual(self.guard.load_state()["consecutive_blocks"], 0)

    def test_parse_skips_sa_entirely_during_cooldown(self):
        with patch("sys.stdout"), patch("sys.stderr"):
            self.guard.record_block("t")
        with patch.object(parser, "load_sa_cookies") as cookies, patch.object(parser, "_og_lead") as lead:
            r = parser.parse_sa_article("https://seekingalpha.com/news/1-x")
        self.assertFalse(r["success"])
        self.assertTrue(r["blocked"])
        self.assertIn("SA_BLOCKED", r["error"])
        cookies.assert_not_called()
        lead.assert_not_called()

    def test_block_mid_fetch_stops_remaining_paths(self):
        calls = []

        def blocked(*a, **k):
            calls.append("pw")
            with patch("sys.stdout"), patch("sys.stderr"):
                self.guard.record_block("playwright")
            raise self.guard.SABlocked("playwright")

        with (
            patch.object(parser, "load_sa_cookies", return_value=[{"name": "user_id", "value": "1"}]),
            patch.object(parser, "has_login_cookies", return_value=True),
            patch.object(parser.sa_login_state, "is_degraded", return_value=False),
            patch.object(parser, "parse_with_playwright_stealth", side_effect=blocked),
            patch.object(parser, "parse_with_curl_cffi_rotated") as curl,
            patch.object(parser.sa_login_state, "record_auth_result") as auth,
        ):
            r = parser.parse_sa_article("https://seekingalpha.com/news/1-x")
        self.assertTrue(r["blocked"])
        self.assertEqual(calls, ["pw"])
        curl.assert_not_called()
        auth.assert_not_called()           # 차단은 로그인 실패로 세지 않는다


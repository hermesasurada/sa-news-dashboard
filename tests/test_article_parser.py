import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sa_article_parser as parser


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

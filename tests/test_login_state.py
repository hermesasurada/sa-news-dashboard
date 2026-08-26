import time
import unittest
from unittest.mock import patch

import sa_login_state
import settings


class LoginStateTests(unittest.TestCase):
    """세션 무효 자동 감지 → 익명 폴백 → 재로그인 시 자동 복귀."""

    def setUp(self):
        self.tmp = settings.BASE_DIR / f".sa_login_state.test.{id(self)}.json"
        self._patch = patch.object(settings, "LOGIN_STATE_PATH", self.tmp)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.unlink(missing_ok=True)

    def test_starts_healthy(self):
        self.assertFalse(sa_login_state.is_degraded())
        self.assertEqual(sa_login_state.effective_min_chars(), settings.SOURCE_MIN_CHARS)
        self.assertTrue(sa_login_state.enforce_locked_gate())

    def test_degrades_only_after_threshold(self):
        for _ in range(settings.LOGIN_FAIL_THRESHOLD - 1):
            sa_login_state.record_auth_result(False)
            self.assertFalse(sa_login_state.is_degraded(), "임계치 전에는 폴백하지 않는다")
        sa_login_state.record_auth_result(False)
        self.assertTrue(sa_login_state.is_degraded())

    def test_degraded_relaxes_gates(self):
        """폴백 중에는 프리뷰라도 발행할 수 있어야 한다."""
        for _ in range(settings.LOGIN_FAIL_THRESHOLD):
            sa_login_state.record_auth_result(False)
        self.assertEqual(sa_login_state.effective_min_chars(), settings.DEGRADED_MIN_CHARS)
        self.assertFalse(sa_login_state.enforce_locked_gate())

    def test_success_resets_counter(self):
        sa_login_state.record_auth_result(False)
        sa_login_state.record_auth_result(True)
        self.assertEqual(sa_login_state.load_state()["consecutive_failures"], 0)
        self.assertFalse(sa_login_state.is_degraded())

    def test_reprobe_is_rate_limited(self):
        for _ in range(settings.LOGIN_FAIL_THRESHOLD):
            sa_login_state.record_auth_result(False)
        self.assertFalse(sa_login_state.should_probe(), "진입 직후에는 재프로브하지 않는다")

        state = sa_login_state.load_state()
        state["last_probe"] = time.time() - (settings.LOGIN_REPROBE_MINUTES * 60 + 1)
        sa_login_state._save(state)
        self.assertTrue(sa_login_state.should_probe())

    def test_recovers_on_successful_probe(self):
        for _ in range(settings.LOGIN_FAIL_THRESHOLD):
            sa_login_state.record_auth_result(False)
        sa_login_state.record_auth_result(True, probed=True)
        self.assertFalse(sa_login_state.is_degraded())
        self.assertEqual(sa_login_state.effective_min_chars(), settings.SOURCE_MIN_CHARS)
        self.assertTrue(sa_login_state.enforce_locked_gate())

    def test_corrupt_state_file_is_survivable(self):
        self.tmp.write_text("{ not json", encoding="utf-8")
        self.assertFalse(sa_login_state.is_degraded())

    def test_disabled_login_never_degrades(self):
        with patch.object(settings, "USE_LOGIN_SESSION", False):
            for _ in range(settings.LOGIN_FAIL_THRESHOLD + 2):
                sa_login_state.record_auth_result(False)
            self.assertFalse(sa_login_state.is_degraded())
            self.assertEqual(
                sa_login_state.effective_min_chars(), settings.DEGRADED_MIN_CHARS
            )


if __name__ == "__main__":
    unittest.main()

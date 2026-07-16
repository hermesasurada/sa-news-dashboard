import tempfile
import unittest
from pathlib import Path

import db


class DatabaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self._original_path = db.DB_PATH
        self._tempdir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tempdir.name) / "test.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._original_path
        self._tempdir.cleanup()

    def _pending(self, email_id: str = "9001") -> int:
        article_id = db.insert_pending_article(
            email_id=email_id,
            ticker="GOOGL, GOOG",
            article_url="https://seekingalpha.com/news/1-test",
            original_title='Alphabet says "hello"',
            email_time_et="2026-07-17 01:00 KST",
        )
        self.assertIsNotNone(article_id)
        return int(article_id)

    def _publish(self, article_id: int) -> None:
        self.assertTrue(
            db.publish_article(
                article_id,
                ticker="GOOGL, GOOG",
                company_name="Alphabet·Alphabet",
                headline="Alphabet, 신규 서비스 공개",
                summary_details=["첫 번째 상세 내용입니다."],
                parse_method="sa_api",
                summary_model="test-model",
            )
        )

    def test_publish_canonicalizes_and_search_handles_special_characters(self):
        article_id = self._pending()
        self._publish(article_id)

        result = db.query_articles(q="Alphabet 신규")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["ticker"], "GOOG")
        self.assertEqual(result["items"][0]["summary_details"], ["첫 번째 상세 내용입니다."])

        self.assertEqual(db.query_articles(q='"')["total"], 0)
        self.assertEqual(db.query_articles(q="C++")["total"], 0)

    def test_failed_reprocess_keeps_published_article_visible(self):
        article_id = self._pending()
        self._publish(article_id)

        result = db.mark_attempt_failed(article_id, "temporary parser failure")
        self.assertEqual(result["pub_status"], db.STATUS_PUBLISHED)
        self.assertEqual(db.query_articles()["total"], 1)

    def test_deleted_article_cannot_be_revived_by_late_worker_failure(self):
        article_id = self._pending()
        self._publish(article_id)
        self.assertTrue(db.delete_article(article_id))

        result = db.mark_attempt_failed(article_id, "late failure")
        self.assertEqual(result["pub_status"], db.STATUS_DELETED)
        self.assertEqual(db.query_articles()["total"], 0)
        self.assertEqual(db.query_articles(deleted=True)["total"], 1)

    def test_legacy_summary_decoder(self):
        self.assertEqual(db.decode_summary_details("['하나', '둘']"), ["하나", "둘"])
        self.assertEqual(db.decode_summary_details("not a list"), [])

    def test_health_check(self):
        self.assertEqual(db.health_check(), {"status": "ok", "database": "ok"})


if __name__ == "__main__":
    unittest.main()

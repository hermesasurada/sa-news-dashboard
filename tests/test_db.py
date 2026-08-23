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

    def test_pending_article_reaches_failed_at_retry_limit(self):
        article_id = self._pending()

        result = db.mark_attempt_failed(article_id, "provider failure", max_retry=1)

        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(result["pub_status"], db.STATUS_FAILED)
        self.assertNotIn(article_id, [row["id"] for row in db.get_pending_due()])

    def test_deleted_article_cannot_be_revived_by_late_worker_failure(self):
        article_id = self._pending()
        self._publish(article_id)
        self.assertTrue(db.delete_article(article_id))

        result = db.mark_attempt_failed(article_id, "late failure")
        self.assertEqual(result["pub_status"], db.STATUS_DELETED)
        self.assertEqual(db.query_articles()["total"], 0)
        self.assertEqual(db.query_articles(deleted=True)["total"], 1)

    def test_delete_can_be_restored_from_undo_action(self):
        article_id = self._pending()
        self._publish(article_id)

        self.assertTrue(db.delete_article(article_id))
        self.assertTrue(db.restore_article(article_id))
        self.assertEqual(db.query_articles()["total"], 1)
        self.assertEqual(db.query_articles(deleted=True)["total"], 0)

    def test_legacy_summary_decoder(self):
        self.assertEqual(db.decode_summary_details("['하나', '둘']"), ["하나", "둘"])
        self.assertEqual(db.decode_summary_details("not a list"), [])

    def test_health_check(self):
        self.assertEqual(db.health_check(), {"status": "ok", "database": "ok"})

    def test_article_list_includes_queue_stats(self):
        article_id = self._pending()
        self._publish(article_id)

        result = db.query_articles()

        self.assertEqual(result["queue"]["pending"], 0)
        self.assertEqual(result["queue"]["failed"], 0)
        self.assertEqual(result["queue"]["unread"], 1)

    def test_article_list_can_skip_metadata_and_projects_card_fields(self):
        article_id = self._pending()
        self._publish(article_id)

        result = db.query_articles(include_total=False, include_queue=False)

        self.assertNotIn("total", result)
        self.assertNotIn("queue", result)
        self.assertEqual(set(result["items"][0]), set(db.ARTICLE_LIST_COLUMNS))

    def test_published_article_count_excludes_non_published_rows(self):
        published_id = self._pending("9001")
        self._publish(published_id)
        self._pending("9002")

        self.assertEqual(db.get_published_article_count(), 1)

    def test_list_sort_uses_composite_index(self):
        with db.get_conn() as conn:
            plan = conn.execute(
                """
                EXPLAIN QUERY PLAN
                SELECT * FROM articles
                WHERE pub_status = 'published' AND is_read = 0
                ORDER BY email_time_et DESC, CAST(email_id AS INTEGER) DESC
                LIMIT 15
                """
            ).fetchall()

        detail = " ".join(str(row[3]) for row in plan)
        self.assertIn("idx_status_unread_email_time", detail)
        self.assertNotIn("TEMP B-TREE", detail)

    def test_read_state_update_does_not_reindex_fts(self):
        article_id = self._pending()
        self._publish(article_id)

        with db.get_conn() as conn:
            before = conn.total_changes
            conn.execute("UPDATE articles SET is_read = 1 WHERE id = ?", (article_id,))
            changed_rows = conn.total_changes - before

        self.assertEqual(changed_rows, 1)

    def test_init_db_drops_legacy_columns(self):
        path = Path(self._tempdir.name) / "legacy.db"
        import sqlite3
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE articles (
                id INTEGER PRIMARY KEY,
                email_id TEXT UNIQUE,
                ticker TEXT NOT NULL DEFAULT 'X',
                article_url TEXT NOT NULL DEFAULT '',
                original_title TEXT,
                company_name TEXT,
                headline TEXT,
                summary_details TEXT,
                ticker_color TEXT DEFAULT 'blue',
                summary_core TEXT,
                tag TEXT,
                tag_color TEXT DEFAULT 'blue',
                email_body TEXT,
                pub_status TEXT DEFAULT 'pending',
                email_time_et TEXT,
                last_modified TEXT,
                is_read INTEGER DEFAULT 0,
                retry_count INTEGER DEFAULT 0
            );
            """
        )
        conn.close()
        db.DB_PATH = path
        db.init_db()
        with db.get_conn() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(articles)")}
        for name in ("summary_core", "tag", "tag_color", "email_body"):
            self.assertNotIn(name, cols)
        self.assertIn("source_text", cols)
        self.assertIn("summary_details", cols)


if __name__ == "__main__":
    unittest.main()

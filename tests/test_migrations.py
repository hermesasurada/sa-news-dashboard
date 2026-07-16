import tempfile
import unittest
from pathlib import Path

import db
from migrations import migrate as legacy_migrate


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self):
        self._original_path = db.DB_PATH
        self._tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tempdir.name)
        db.DB_PATH = self.root / "migration.db"

    def tearDown(self):
        db.DB_PATH = self._original_path
        self._tempdir.cleanup()

    def test_parse_created_at(self):
        self.assertEqual(
            legacy_migrate.parse_created_at("sa_dashboard_20260520_0130.html"),
            "2026-05-20 01:30 KST",
        )
        self.assertIsNone(legacy_migrate.parse_created_at("other.html"))

    def test_migrate_legacy_card_into_current_schema(self):
        html = """
        <div class="card">
          <span class="ticker-badge ticker-green">AAPL</span>
          <div class="card-source">Apple</div>
          <div class="card-time">2026-05-20 01:20 KST</div>
          <h2 class="card-title">Apple 테스트</h2>
          <span class="tag tag-blue">실적</span>
          <div><strong>핵심</strong>&nbsp;핵심 문장</div>
          <ul><li>상세 문장</li></ul>
          <a class="card-link" href="https://seekingalpha.com/news/1">원문</a>
        </div>
        """
        report = self.root / "sa_dashboard_20260520_0130.html"
        report.write_text(html, encoding="utf-8")

        legacy_migrate.migrate(self.root)
        result = db.query_articles()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["headline"], "Apple 테스트")
        self.assertEqual(result["items"][0]["summary_details"], ["상세 문장"])


if __name__ == "__main__":
    unittest.main()

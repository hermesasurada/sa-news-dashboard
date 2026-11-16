"""화면 스크립트 배치 — app.js를 나눈 뒤(2026-11-16) 지켜야 할 것들."""
import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
ORDER = ["app.js", "app-cards.js", "app-quote.js", "app-actions.js",
         "app-feed.js", "app-settings.js", "app-boot.js"]


class StaticLayoutTests(unittest.TestCase):
    def setUp(self):
        self.html = (STATIC / "index.html").read_text(encoding="utf-8")

    def test_scripts_load_in_order_with_boot_last(self):
        # 전역 범위를 함께 쓰는 일반 스크립트라 순서가 곧 실행 순서다. init()이 든 app-boot.js가 마지막.
        loaded = re.findall(r'<script src="/static/(app(?:-[a-z]+)?\.js)"', self.html)
        self.assertEqual([n for n in loaded if n != "app-utils.js"], ORDER)
        self.assertLess(loaded.index("app-utils.js"), loaded.index("app.js"))

    def test_every_app_script_is_loaded(self):
        on_disk = sorted(p.name for p in STATIC.glob("app*.js"))
        self.assertEqual(on_disk, sorted(ORDER + ["app-utils.js"]))

    def test_init_runs_only_in_boot(self):
        for name in ORDER[:-1]:
            self.assertNotRegex((STATIC / name).read_text(encoding="utf-8"), r"(?m)^init\(\);")
        self.assertRegex((STATIC / "app-boot.js").read_text(encoding="utf-8"), r"(?m)^init\(\);\s*\Z")

    def test_every_local_asset_gets_a_version(self):
        # 캐시가 1년 고정이라 버전 없는 주소가 하나라도 남으면 고쳐도 옛 파일이 보인다.
        # app을 불러오면 db.init_db()가 돈다 — 운영 DB 대신 임시 DB를 가리키게 한 뒤 불러온다.
        import db
        original = db.DB_PATH
        with tempfile.TemporaryDirectory() as tmp:
            db.DB_PATH = Path(tmp) / "layout.db"
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    import app
                html = app.root().body.decode("utf-8")
            finally:
                db.DB_PATH = original
        assets = re.findall(r'/static/[A-Za-z0-9._-]+\.(?:js|css)[^"]*"', html)
        self.assertGreaterEqual(len(assets), len(ORDER) + 5)
        for ref in assets:
            self.assertRegex(ref, r"\?v=[1-9]\d*\"$", msg=ref)


if __name__ == "__main__":
    unittest.main()

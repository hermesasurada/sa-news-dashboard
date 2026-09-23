"""중앙 LLM 카탈로그가 깨져도 SA 요약 모듈이 import되고 grok 기본 모델을 구한다(2026-09-23)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PROBE = r"""
import json, sys
sys.path.insert(0, "scripts")
import sa_claude_cli as s
s._read_grok_model_cache = lambda: ("grok-4.7", True)   # 네트워크·CLI 없이 캐시 경로만 확인
print(json.dumps({"catalog_none": s.llm_catalog is None, "grok": s._grok_default_model()}))
"""


class CatalogIsolationTests(unittest.TestCase):
    def test_broken_catalog_module_does_not_stop_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "llm_catalog.py").write_text("def broken(:\n", encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=f"{tmp}{os.pathsep}{REPO}", HERMES_LLM_LOG_DISABLED="1")
            proc = subprocess.run([sys.executable, "-c", PROBE], cwd=REPO, env=env,
                                  capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        self.assertIn("카탈로그 없이 진행", proc.stderr)
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(out, {"catalog_none": True, "grok": "grok-4.7"})


if __name__ == "__main__":
    unittest.main()

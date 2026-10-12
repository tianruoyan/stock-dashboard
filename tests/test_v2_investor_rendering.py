"""Run presentation-only DOM contract regressions without starting a browser."""
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class InvestorRenderingTests(unittest.TestCase):
    def test_node_dom_contracts(self):
        if not shutil.which("node"):
            self.skipTest("Node.js is required for frontend DOM-contract tests")
        result = subprocess.run(["node", "--test", str(ROOT / "tests/test_v2_investor_rendering.cjs")], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

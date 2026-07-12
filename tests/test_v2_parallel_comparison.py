from __future__ import annotations

import unittest
from pathlib import Path

from v2_platform.parallel_comparison import V2ParallelComparisonBuilder


ROOT = Path(__file__).resolve().parents[1]


class ParallelComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = V2ParallelComparisonBuilder(ROOT).build()

    def test_both_entries_and_states_are_compared(self) -> None:
        self.assertTrue(self.report["v1"]["entry_ok"])
        self.assertTrue(self.report["v2"]["entry_ok"])
        for side in ("v1", "v2"):
            self.assertIn("market_date", self.report[side])
            self.assertIn("quality_state", self.report[side])
            self.assertIn("automation_state", self.report[side])

    def test_cutover_can_never_happen_automatically(self) -> None:
        self.assertFalse(self.report["cutover"]["ready"])
        self.assertTrue(self.report["cutover"]["requires_new_user_confirmation"])
        self.assertEqual(self.report["mode"], "parallel_shadow")

    def test_divergences_have_actions(self) -> None:
        self.assertTrue(all(item.get("conclusion") and item.get("action") for item in self.report["divergences"]))


if __name__ == "__main__":
    unittest.main()

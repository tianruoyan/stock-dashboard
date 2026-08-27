from __future__ import annotations

import unittest
from pathlib import Path

from v2_platform.v22_learning import V22LearningBuilder


ROOT = Path(__file__).resolve().parents[1]


class V22ParallelAcceptanceTests(unittest.TestCase):
    def test_parallel_comparison_explains_noise_reduction_without_cutover(self) -> None:
        outputs = V22LearningBuilder(ROOT).build()
        comparison = outputs["parallel-comparison.json"]
        self.assertEqual(comparison["mode"], "parallel_shadow")
        self.assertGreaterEqual(comparison["v2_baseline"]["validation_count"], comparison["v22_candidate"]["validation_count"])
        self.assertGreaterEqual(comparison["v22_candidate"]["unformed_clue_count"], 0)
        self.assertFalse(comparison["cutover"]["ready"])
        self.assertFalse(comparison["guardrails"]["automatic_cutover"])
        self.assertFalse(comparison["guardrails"]["user_assets_modified"])
        acceptance = outputs["acceptance-report.json"]
        self.assertEqual(acceptance["status"], "passed")
        self.assertEqual(acceptance["production_promotion"], "hold")


if __name__ == "__main__":
    unittest.main()

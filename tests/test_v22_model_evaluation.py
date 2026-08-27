from __future__ import annotations

import unittest
from pathlib import Path

from v2_platform.v22_learning import V22LearningBuilder


ROOT = Path(__file__).resolve().parents[1]


class V22ModelEvaluationTests(unittest.TestCase):
    def test_insufficient_sample_span_withholds_metrics_and_keeps_baseline(self) -> None:
        evaluation = V22LearningBuilder(ROOT).build()["model-evaluation.json"]
        if evaluation["minimum_requirements_met"]:
            self.assertTrue(evaluation["metrics_published"])
            self.assertEqual(evaluation["recommendation"]["action"], "提交用户评审")
        else:
            self.assertFalse(evaluation["metrics_published"])
            self.assertEqual(evaluation["recommendation"]["action"], "保留当前基线")
        self.assertFalse(evaluation["automatic_live_promotion"])


if __name__ == "__main__":
    unittest.main()

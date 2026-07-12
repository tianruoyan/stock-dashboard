from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v2_platform.model_evaluation import V2ModelEvaluator


ROOT = Path(__file__).resolve().parents[1]


class V2ModelEvaluationTests(unittest.TestCase):
    def prepare(self, root: Path) -> None:
        (root / "config").mkdir(parents=True)
        (root / "data/v2/snapshots/2026-07-01").mkdir(parents=True)
        (root / "config/v2-model-registry.json").write_text((ROOT / "config/v2-model-registry.json").read_text(encoding="utf-8"), encoding="utf-8")

    def test_no_outcomes_keeps_baseline_and_never_promotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            (root / "data/v2/replay-index.json").write_text('{"snapshots":[]}', encoding="utf-8")
            (root / "data/v2/signal-outcomes.json").write_text('{"signals":[]}', encoding="utf-8")
            report = V2ModelEvaluator(root).build()
            self.assertEqual(report["recommendation"]["action"], "keep_baseline")
            self.assertTrue(report["recommendation"]["requires_user_confirmation"])
            self.assertFalse(report["promotion_policy"]["automatic_live_promotion"])

    def test_primary_window_aggregates_at_signal_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            snapshot = {
                "snapshot_id": "s1", "decision_date": "2026-07-01", "decision_model_version": "decision-v2.0-baseline-1",
                "quality": {"state": "usable"}, "market_environment": {"state": "进攻"}
            }
            snapshot_path = root / "data/v2/snapshots/2026-07-01/s1.json"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            (root / "data/v2/replay-index.json").write_text(json.dumps({"snapshots":[{"snapshot_id":"s1","path":"data/v2/snapshots/2026-07-01/s1.json"}]}), encoding="utf-8")
            outcomes = {"signals": [{
                "snapshot_id":"s1", "signal_id":"x", "title":"测试", "kind":"risk", "security_results":[
                    {"windows":[{"window":"T+3","status":"evaluated","result":{"absolute_return_pct":-4.0,"signal_support":"supportive"}}]},
                    {"windows":[{"window":"T+3","status":"evaluated","result":{"absolute_return_pct":2.0,"signal_support":"not_supportive"}}]}
                ]
            }]}
            (root / "data/v2/signal-outcomes.json").write_text(json.dumps(outcomes), encoding="utf-8")
            report = V2ModelEvaluator(root).build()
            summary = next(item for item in report["version_summaries"] if item["version"] == "decision-v2.0-baseline-1")
            self.assertEqual(summary["evaluated_signal_count"], 1)
            self.assertEqual(summary["median_absolute_return_pct"], -1.0)
            self.assertEqual(summary["signal_support_rate"], 100.0)
            self.assertFalse(summary["promotion_eligible"])

    def test_legacy_snapshots_are_not_silently_relabelled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            path = root / "data/v2/snapshots/2026-07-01/legacy.json"
            path.write_text(json.dumps({"snapshot_id":"legacy","decision_date":"2026-07-01","quality":{},"market_environment":{}}), encoding="utf-8")
            (root / "data/v2/replay-index.json").write_text(json.dumps({"snapshots":[{"path":"data/v2/snapshots/2026-07-01/legacy.json"}]}), encoding="utf-8")
            (root / "data/v2/signal-outcomes.json").write_text('{"signals":[]}', encoding="utf-8")
            report = V2ModelEvaluator(root).build()
            self.assertIn("历史快照没有决策模型版本，只能作为旧基线背景", report["data_gaps"])


if __name__ == "__main__":
    unittest.main()

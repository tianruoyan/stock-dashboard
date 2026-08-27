from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v2_platform.environment_evidence import canonical_hash
from v2_platform.v22_learning import V22LearningBuilder


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class V22S1LearningGateTests(unittest.TestCase):
    def test_complete_t3_result_is_evaluable_but_cannot_publish_rate_below_minimums(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = {"case_id": "case1", "business_path": "theme_opportunity", "ended": False}
            snapshot = {
                "snapshot_id": "trigger1", "case_id": "case1", "case_batch_id": "batch", "case_content_hash": canonical_hash(case), "immutable_hash": "immutable",
                "state_hash": "state1", "kind": "opportunity", "trade_date": "2026-07-17", "state_observed_at": "2026-07-17T10:00:00+08:00",
                "representative_quotes": [{"code": "sh600000", "trigger_price": 10.0, "quote_time": "2026-07-17T09:59:00+08:00", "source_id": "quote", "source_label": "真实行情测试源", "collected_at": "2026-07-17T10:00:00+08:00", "cross_source_verified": True, "quality_state": "dual_source_confirmed"}],
            }
            path = root / "data/v2/v22/trigger.json"
            write(path, snapshot)
            write(root / "data/v2/v22/trigger-quote-index.json", {"snapshots": [{"relative_path": str(path.relative_to(root)), "immutable_hash": "immutable"}]})
            case_snapshot = {"case_batch_id": "batch", "cases": [case], "immutable_hash": "case-batch-hash"}
            case_path = root / "data/v2/v22/case-batch.json"
            write(case_path, case_snapshot)
            write(root / "data/v2/v22/decision-case-snapshot-index.json", {"snapshots": [{"case_batch_id": "batch", "relative_path": str(case_path.relative_to(root)), "immutable_hash": "case-batch-hash"}]})
            write(root / "data/v2/v22/outcome-prices.json", {"observations": [{
                "trigger_snapshot_id": "trigger1", "code": "sh600000", "reference_price": 10.0, "reference_at": "2026-07-17T09:59:00+08:00",
                "windows": {"T+3": {"price": 11.0, "quote_time": "2026-07-22T15:00:00+08:00", "source": "real-history", "collected_at": "2026-07-22T15:05:00+08:00"}},
            }]})
            write(root / "data/v2/v22/decision-cases.json", {"case_batch_id": "batch", "trade_date": "2026-07-17", "cases": []})
            write(root / "data/v2/v22/decision-system-candidate.json", {"summary": {"awaiting_confirmation": 0}})
            write(root / "data/v2/decision-system.json", {"validation_queue": [], "system": {"decision_as_of": "2026-07-17T10:00:00+08:00"}})
            write(root / "data/v2/v22/time-semantics.json", {"sources": {"v2_baseline": {"market_date": "2026-07-17"}, "v22_market_environment": {"market_date": "2026-07-17"}}, "comparison": {"allowed": True, "reason": "日期一致"}})
            outputs = V22LearningBuilder(root).build()
            evaluation = outputs["model-evaluation.json"]
            self.assertEqual(evaluation["record_count"], 1)
            self.assertFalse(evaluation["metrics_published"])
            self.assertFalse(evaluation["automatic_live_promotion"])
            self.assertFalse(outputs["parallel-comparison.json"]["hit_rate_comparison_allowed"])

            snapshot["representative_quotes"][0].update({"cross_source_verified": False, "quality_state": "single_source_observation"})
            write(path, snapshot)
            single_source_outputs = V22LearningBuilder(root).build()
            single_source_case = single_source_outputs["signal-outcomes.json"]["cases"][0]
            self.assertFalse(single_source_case["evaluation_included"])
            dual_gate = next(item for item in single_source_case["evaluation_gates"] if item["id"] == "dual_source_trigger_confirmation")
            self.assertFalse(dual_gate["passed"])

    def test_missing_primary_window_never_enters_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "data/v2/v22/decision-cases.json", {"case_batch_id": "batch", "trade_date": "2026-07-17", "cases": [{"case_id": "case1", "business_path": "theme_opportunity", "ended": False}]})
            write(root / "data/v2/v22/decision-system-candidate.json", {"summary": {}})
            write(root / "data/v2/decision-system.json", {"validation_queue": []})
            write(root / "data/v2/v22/time-semantics.json", {"sources": {}, "comparison": {"allowed": False, "reason": "日期不一致"}})
            outputs = V22LearningBuilder(root).build()
            self.assertEqual(outputs["model-evaluation.json"]["record_count"], 0)
            self.assertFalse(outputs["parallel-comparison.json"]["date_comparison_allowed"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v2_platform.decision_system import V2DecisionSystemBuilder
from v2_platform.learning import TradingCalendar, V2LearningBuilder, stable_hash


ROOT = Path(__file__).resolve().parents[1]


class V2LearningTests(unittest.TestCase):
    def test_snapshot_id_ignores_rebuild_clock_only(self) -> None:
        base = {
            "quality": {"state": "degraded", "evidence": [{"summary": "same", "as_of": "2026-07-12T10:00:00+08:00"}]},
            "style_map": {"as_of": "2026-07-12T10:00:00+08:00", "dimensions": []},
            "signals": [{"evidence": [{"type": "decision_evidence", "source": "quality-report.json, source-health.json", "summary": "same", "as_of": "2026-07-12T10:00:00+08:00"}]}],
        }
        later = json.loads(json.dumps(base))
        later["quality"]["evidence"][0]["as_of"] = "2026-07-12T11:00:00+08:00"
        later["style_map"]["as_of"] = "2026-07-12T11:00:00+08:00"
        later["signals"][0]["evidence"][0]["as_of"] = "2026-07-12T11:00:00+08:00"
        self.assertEqual(
            stable_hash(V2LearningBuilder._semantic_snapshot(base)),
            stable_hash(V2LearningBuilder._semantic_snapshot(later)),
        )

    def test_verified_calendar_advances_across_weekend(self) -> None:
        config = json.loads((ROOT / "config" / "v2-market-calendar.json").read_text(encoding="utf-8"))
        calendar = TradingCalendar(config)
        self.assertEqual(calendar.advance(__import__("datetime").date(2026, 7, 10), 1).isoformat(), "2026-07-13")
        self.assertEqual(calendar.advance(__import__("datetime").date(2026, 7, 10), 3).isoformat(), "2026-07-15")

    def test_snapshot_is_idempotent_and_withholds_hit_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            for name in ("v2-learning-policy.json", "v2-market-calendar.json"):
                (root / "config" / name).write_text((ROOT / "config" / name).read_text(encoding="utf-8"), encoding="utf-8")
            decision = V2DecisionSystemBuilder(ROOT).build()
            builder = V2LearningBuilder(root)
            first_index, first_review, first_path = builder.build(decision)
            second_index, second_review, second_path = builder.build(decision)
            self.assertEqual(first_path, second_path)
            self.assertEqual(first_index["snapshot_count"], 1)
            self.assertEqual(second_index["snapshot_count"], 1)
            self.assertIsNone(first_review["hit_rate"])
            self.assertEqual(second_review["hit_rate_state"], "withheld_insufficient_samples_or_time_span")

    def test_snapshot_preserves_evidence_conditions_and_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            for name in ("v2-learning-policy.json", "v2-market-calendar.json"):
                (root / "config" / name).write_text((ROOT / "config" / name).read_text(encoding="utf-8"), encoding="utf-8")
            decision = V2DecisionSystemBuilder(ROOT).build()
            _, _, path = V2LearningBuilder(root).build(decision)
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["quality"]["state"], decision["data_quality_gate"]["state"])
            self.assertEqual(snapshot["decision_model_version"], decision["system"]["decision_model_version"])
            for signal in snapshot["signals"]:
                self.assertIn("evidence", signal)
                self.assertIn("confirm_conditions", signal)
                self.assertIn("invalidation_conditions", signal)
                self.assertTrue(all(item["status"] == "pending_data" for item in signal["outcome_windows"]))

    def test_auditable_price_observation_resolves_without_mutating_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            for name in ("v2-learning-policy.json", "v2-market-calendar.json"):
                (root / "config" / name).write_text((ROOT / "config" / name).read_text(encoding="utf-8"), encoding="utf-8")
            decision = V2DecisionSystemBuilder(ROOT).build()
            builder = V2LearningBuilder(root)
            _, _, path = builder.build(decision)
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            signal = next(item for item in snapshot["signals"] if item["securities"])
            security = next(item for item in signal["securities"] if item["code"])
            observation = {
                "observations": [{
                    "snapshot_id": snapshot["snapshot_id"],
                    "signal_id": signal["signal_id"],
                    "code": security["code"],
                    "reference_price": 100.0,
                    "reference_at": "2026-07-10T15:00:00+08:00",
                    "source": "test-fixture",
                    "windows": {"T+1": {"price": 95.0, "as_of": "2026-07-13T15:00:00+08:00", "source": "test-fixture"}}
                }]
            }
            (root / "data" / "v2" / "outcome-prices.json").write_text(json.dumps(observation), encoding="utf-8")
            builder = V2LearningBuilder(root)
            _, review, _ = builder.build(decision)
            outcomes = json.loads((root / "data" / "v2" / "signal-outcomes.json").read_text(encoding="utf-8"))
            resolved = next(item for item in outcomes["signals"] if item["signal_id"] == signal["signal_id"])
            result = resolved["security_results"][0]["windows"][0]["result"]
            self.assertEqual(result["absolute_return_pct"], -5.0)
            self.assertEqual(result["signal_support"], "supportive")
            self.assertEqual(review["hit_rate_state"], "withheld_insufficient_samples_or_time_span")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["content_hash"], snapshot["content_hash"])


if __name__ == "__main__":
    unittest.main()

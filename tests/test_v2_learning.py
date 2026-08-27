from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from v2_platform.decision_system import V2DecisionSystemBuilder
from v2_platform.learning import TradingCalendar, V2LearningBuilder, stable_hash


ROOT = Path(__file__).resolve().parents[1]
DECISION_NOW = datetime.fromisoformat("2026-07-10T14:58:00+08:00")


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
            root = Path(tmp).resolve()
            (root / "config").mkdir()
            for name in ("v2-learning-policy.json", "v2-market-calendar.json"):
                (root / "config" / name).write_text((ROOT / "config" / name).read_text(encoding="utf-8"), encoding="utf-8")
            decision = V2DecisionSystemBuilder(ROOT, now=DECISION_NOW).build()
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
            decision = V2DecisionSystemBuilder(ROOT, now=DECISION_NOW).build()
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
            decision = V2DecisionSystemBuilder(ROOT, now=DECISION_NOW).build()
            builder = V2LearningBuilder(root)
            _, _, path = builder.build(decision)
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            signal = next(
                item for item in snapshot["signals"]
                if item["securities"] and item.get("kind") in {"opportunity", "risk"}
            )
            security = next(item for item in signal["securities"] if item["code"])
            outcome_price = 105.0 if signal.get("kind") == "opportunity" else 95.0
            expected_return = 5.0 if signal.get("kind") == "opportunity" else -5.0
            observation = {
                "observations": [{
                    "snapshot_id": snapshot["snapshot_id"],
                    "signal_id": signal["signal_id"],
                    "code": security["code"],
                    "reference_price": 100.0,
                    "reference_at": "2026-07-10T15:00:00+08:00",
                    "source": "test-fixture",
                    "windows": {"T+1": {"price": outcome_price, "as_of": "2026-07-13T15:00:00+08:00", "source": "test-fixture"}}
                }]
            }
            (root / "data" / "v2" / "outcome-prices.json").write_text(json.dumps(observation), encoding="utf-8")
            builder = V2LearningBuilder(root)
            _, review, _ = builder.build(decision)
            outcomes = json.loads((root / "data" / "v2" / "signal-outcomes.json").read_text(encoding="utf-8"))
            resolved = next(item for item in outcomes["signals"] if item["signal_id"] == signal["signal_id"])
            result = resolved["security_results"][0]["windows"][0]["result"]
            self.assertEqual(result["absolute_return_pct"], expected_return)
            self.assertEqual(result["signal_support"], "supportive")
            self.assertEqual(review["hit_rate_state"], "withheld_insufficient_samples_or_time_span")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["content_hash"], snapshot["content_hash"])

    def test_p0_03_same_decision_key_has_one_evaluation_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "config").mkdir()
            for name in ("v2-learning-policy.json", "v2-market-calendar.json"):
                (root / "config" / name).write_text((ROOT / "config" / name).read_text(encoding="utf-8"), encoding="utf-8")
            folder = root / "data/v2/snapshots/2026-07-10"
            folder.mkdir(parents=True)
            base = {
                "decision_as_of": "2026-07-10T14:43:40+08:00",
                "decision_date": "2026-07-10",
                "decision_model_version": "decision-v2.0-baseline-1",
                "quality": {"state": "degraded"},
                "market_environment": {"state": "等待"},
                "style_map": {},
                "learning_policy_version": "test",
                "calendar_version": "test",
            }
            first = {**base, "snapshot_id": "s1", "content_hash": "h1", "created_at": "2026-07-12T10:00:00+08:00", "signals": [{"signal_id": "a"}]}
            second = {**base, "snapshot_id": "s2", "content_hash": "h2", "created_at": "2026-07-12T11:00:00+08:00", "signals": [{"signal_id": "a"}, {"signal_id": "b"}]}
            p1, p2 = folder / "s1.json", folder / "s2.json"
            p1.write_text(json.dumps(first), encoding="utf-8")
            p2.write_text(json.dumps(second), encoding="utf-8")
            builder = V2LearningBuilder(root)
            index = builder._index(first, p1)
            (root / "data/v2/replay-index.json").write_text(json.dumps(index), encoding="utf-8")
            index = builder._index(second, p2)
            self.assertEqual(index["snapshot_count"], 2)
            self.assertEqual(index["evaluation_snapshot_count"], 1)
            eligible = [item for item in index["snapshots"] if item["evaluation_eligible"]]
            self.assertEqual([item["snapshot_id"] for item in eligible], ["s2"])
            self.assertTrue(all(item["canonical_snapshot_id"] == "s2" for item in index["snapshots"]))
            outcomes = builder._resolve_outcomes(index)
            self.assertEqual({item["signal_id"] for item in outcomes["signals"]}, {"a", "b"})


if __name__ == "__main__":
    unittest.main()

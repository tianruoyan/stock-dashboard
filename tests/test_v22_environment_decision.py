from __future__ import annotations

import json
import unittest
from pathlib import Path

from v2_platform.environment_decision import V22EnvironmentDecisionBuilder
from v2_platform.environment_state_machine import STATES


ROOT = Path(__file__).resolve().parents[1]


class V22EnvironmentDecisionTests(unittest.TestCase):
    def test_workspace_decision_is_shadow_and_guarded(self) -> None:
        payload = V22EnvironmentDecisionBuilder(ROOT).build()
        self.assertEqual(payload["mode"], "shadow_only")
        self.assertIn(payload["primary_state"], STATES)
        self.assertEqual(len(payload["style_regimes"]), 4)
        decision = json.loads((ROOT / "data/v2/decision-system.json").read_text(encoding="utf-8"))
        expected_ids = {
            item["id"]
            for item in [*decision.get("opportunity_radar", []), *decision.get("validation_queue", [])]
            if isinstance(item, dict) and item.get("id")
        }
        self.assertEqual({item["opportunity_id"] for item in payload["g5_links"]}, expected_ids)
        self.assertFalse(payload["guardrails"]["automatic_trading"])
        self.assertFalse(payload["guardrails"]["user_assets_modified"])
        self.assertFalse(payload["guardrails"]["model_promoted"])
        self.assertFalse(payload["guardrails"]["g5_bypasses_other_gates"])

    def test_written_snapshot_matches_index_and_rebuild_is_idempotent(self) -> None:
        first = V22EnvironmentDecisionBuilder(ROOT).write()
        second = V22EnvironmentDecisionBuilder(ROOT).write()
        self.assertEqual(first["decision_snapshot_id"], second["decision_snapshot_id"])
        self.assertEqual(first["immutable_hash"], second["immutable_hash"])
        index = json.loads((ROOT / "data/v2/v22/environment-decision-snapshot-index.json").read_text(encoding="utf-8"))
        matches = [item for item in index["snapshots"] if item["decision_snapshot_id"] == first["decision_snapshot_id"]]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["immutable_hash"], first["immutable_hash"])

    def test_snapshot_identity_includes_current_g5_projection(self) -> None:
        first = V22EnvironmentDecisionBuilder(ROOT).build()
        decision = json.loads((ROOT / "data/v2/decision-system.json").read_text(encoding="utf-8"))
        expected = {
            item["id"]
            for item in [*decision.get("opportunity_radar", []), *decision.get("validation_queue", [])]
            if isinstance(item, dict) and item.get("id")
        }
        self.assertEqual(expected, {item["opportunity_id"] for item in first["g5_links"]})
        written = V22EnvironmentDecisionBuilder(ROOT).write()
        self.assertEqual(
            {item["opportunity_id"] for item in written["g5_links"]},
            {item["opportunity_id"] for item in first["g5_links"]},
        )


if __name__ == "__main__":
    unittest.main()

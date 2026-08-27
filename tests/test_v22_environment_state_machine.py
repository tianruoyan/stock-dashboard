from __future__ import annotations

import unittest

from v2_platform.environment_state_machine import STATES, decide_environment_transition


def environment(*levels: tuple[str, str, str], quality: str = "usable", snapshot: str = "env-1") -> dict:
    return {
        "environment_snapshot_id": snapshot,
        "quality_state": quality,
        "dimensions": [
            {"dimension_code": code, "support_level": level, "quality_state": item_quality, "evidence_ref_ids": [f"{code}-ref"], "counter_evidence": []}
            for code, level, item_quality in levels
        ],
    }


class V22EnvironmentStateMachineTests(unittest.TestCase):
    def test_reliable_risk_uses_fast_path_without_waiting_two_checks(self) -> None:
        payload = environment(("sentiment_structure", "suppress", "usable"), ("position_fragility", "suppress", "degraded"))
        result = decide_environment_transition(payload)
        self.assertEqual(result["primary_state"], "risk_release")
        self.assertTrue(result["risk_fast_path"])
        self.assertIn(result["primary_state"], STATES)

    def test_positive_upgrade_requires_two_distinct_checks(self) -> None:
        first_env = environment(
            ("index_structure", "support", "usable"),
            ("liquidity", "support", "usable"),
            ("mainline_structure", "support", "usable"),
            snapshot="env-1",
        )
        first = decide_environment_transition(first_env, previous={"primary_state": "repair", "confirmation_count": 0})
        self.assertEqual(first["primary_state"], "repair")
        self.assertEqual(first["transition_type"], "pending_confirmation")
        second_env = {**first_env, "environment_snapshot_id": "env-2"}
        second = decide_environment_transition(second_env, previous=first)
        self.assertEqual(second["primary_state"], "mainline_confirmed")
        self.assertEqual(second["transition_type"], "upgrade")

    def test_quality_block_holds_direction_instead_of_inventing_one(self) -> None:
        result = decide_environment_transition(environment(quality="blocked"), previous={"primary_state": "rotation_trial", "confirmation_count": 1})
        self.assertEqual(result["primary_state"], "rotation_trial")
        self.assertEqual(result["transition_type"], "quality_hold")
        self.assertFalse(result["state_changed"])


if __name__ == "__main__":
    unittest.main()

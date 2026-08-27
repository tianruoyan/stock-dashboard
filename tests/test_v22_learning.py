from __future__ import annotations

import json
import unittest
from pathlib import Path

from v2_platform.v22_learning import V22LearningBuilder


ROOT = Path(__file__).resolve().parents[1]


class V22LearningTests(unittest.TestCase):
    def test_cases_are_indexed_without_rewriting_snapshots(self) -> None:
        outputs = V22LearningBuilder(ROOT).build()
        replay = outputs["replay-index.json"]
        self.assertGreater(replay["snapshot_count"], 0)
        self.assertFalse(replay["guardrails"]["historical_snapshot_rewritten"])
        self.assertFalse(replay["guardrails"]["later_evidence_backfilled_as_known"])

    def test_missing_historical_reference_prices_are_not_fabricated(self) -> None:
        outcomes = V22LearningBuilder(ROOT).build()["signal-outcomes.json"]
        included = [item for item in outcomes["cases"] if item.get("evaluation_included") is True]
        without_trigger = [item for item in outcomes["cases"] if not item.get("trigger_snapshot_id")]
        self.assertEqual(outcomes["evaluated_case_count"], len(included))
        self.assertTrue(all(item.get("evaluation_included") is False for item in without_trigger))
        self.assertFalse(outcomes["guardrails"]["current_quote_used_as_historical_reference"])
        self.assertFalse(outcomes["guardrails"]["hit_rate_published"])

    def test_public_learning_outputs_contain_no_user_fields(self) -> None:
        outputs = V22LearningBuilder(ROOT).build()
        raw = json.dumps(outputs, ensure_ascii=False)
        for forbidden in ("user_note", "user_priority", "user_intent", "watchlist_source", "source_account_id"):
            self.assertNotIn(forbidden, raw)


if __name__ == "__main__":
    unittest.main()

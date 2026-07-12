from __future__ import annotations

import unittest
from pathlib import Path

from v2_platform.decision_system import V2DecisionSystemBuilder


ROOT = Path(__file__).resolve().parents[1]


class V2DecisionSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = V2DecisionSystemBuilder(ROOT).build()

    def test_top_level_contract_is_complete(self) -> None:
        required = {
            "system",
            "data_quality_gate",
            "market_environment",
            "opportunity_radar",
            "validation_queue",
            "style_map",
            "portfolio_risk",
            "research_themes",
            "signal_review",
            "source_registry",
        }
        self.assertTrue(required.issubset(self.payload))
        self.assertEqual(self.payload["system"]["mode"], "shadow_only")
        self.assertFalse(self.payload["system"]["production_behavior_changed"])

    def test_quality_gate_prevents_false_confirmed_opportunities(self) -> None:
        quality = self.payload["data_quality_gate"]["state"]
        if quality != "usable":
            confirmed = [item for item in self.payload["opportunity_radar"] if item["state"] == "confirmed"]
            self.assertEqual(confirmed, [])

    def test_every_radar_card_has_evidence_conditions_and_action(self) -> None:
        for item in self.payload["opportunity_radar"]:
            self.assertTrue(item["title"])
            self.assertTrue(item["trigger"])
            self.assertTrue(item["action"])
            self.assertIsInstance(item["evidence"], list)
            self.assertIsInstance(item["counter_evidence"], list)
            self.assertIsInstance(item["confirm_conditions"], list)
            self.assertIsInstance(item["invalidation_conditions"], list)

    def test_frontend_contract_does_not_expose_abstract_scores(self) -> None:
        for item in self.payload["opportunity_radar"]:
            self.assertNotIn("evidence_score", item)
            self.assertNotIn("signal_score", item)
            self.assertNotIn("signal_grade", item)

    def test_style_contract_keeps_microcap_separate(self) -> None:
        dimensions = {item["id"]: item for item in self.payload["style_map"]["dimensions"]}
        self.assertIn("small_deng", dimensions)
        self.assertIn("microcap", dimensions)
        self.assertNotEqual(dimensions["small_deng"]["definition"], dimensions["microcap"]["definition"])
        self.assertEqual(dimensions["middle_deng"]["state"], "definition_missing")

    def test_portfolio_does_not_infer_positions(self) -> None:
        portfolio = self.payload["portfolio_risk"]
        self.assertEqual(portfolio["state"], "rules_only")
        self.assertIn("真实持仓数量", portfolio["missing_inputs"])


if __name__ == "__main__":
    unittest.main()

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
            "market_structure",
            "portfolio_risk",
            "research_themes",
            "research_library",
            "stock_pool",
            "governance",
            "input_status",
            "model_evaluation",
            "parallel_comparison",
            "signal_review",
            "source_registry",
        }
        self.assertTrue(required.issubset(self.payload))
        self.assertEqual(self.payload["system"]["mode"], "shadow_only")
        self.assertEqual(self.payload["system"]["operation_strategy"], "parallel_shadow")
        self.assertTrue(self.payload["system"]["stop_v1_requires_new_user_confirmation"])
        self.assertFalse(self.payload["system"]["production_behavior_changed"])
        self.assertEqual(self.payload["system"]["decision_model_version"], "decision-v2.0-baseline-1")

    def test_governance_keeps_blogger_content_out_of_facts(self) -> None:
        policy = self.payload["governance"]["event_registry"]["blogger_policy"]
        self.assertFalse(policy["may_support_fact"])
        self.assertEqual(policy["required_role"], "market_expectation_or_sentiment_only")

    def test_research_and_stock_pool_are_connected(self) -> None:
        self.assertGreater(self.payload["stock_pool"]["stock_count"], 0)
        self.assertTrue(self.payload["research_library"]["domains"])
        mapped = sum(item["stock_count"] for item in self.payload["research_library"]["domains"])
        self.assertGreater(mapped, 0)
        self.assertTrue(all(item.get("role_evidence") for item in self.payload["stock_pool"]["stocks"]))

    def test_quality_gate_prevents_false_confirmed_opportunities(self) -> None:
        quality = self.payload["data_quality_gate"]["state"]
        if quality != "usable":
            confirmed = [item for item in self.payload["opportunity_radar"] if item["state"] == "confirmed"]
            self.assertEqual(confirmed, [])

    def test_cross_market_and_two_sided_sentiment_are_explicit(self) -> None:
        environment = self.payload["market_environment"]
        markets = {item["market"] for item in environment["cross_market"]}
        self.assertTrue({"US", "HK", "KR"}.issubset(markets))
        kr = next(item for item in environment["cross_market"] if item["market"] == "KR")
        if kr["quality_state"] != "usable":
            self.assertEqual(kr["actionability"], "background_only")
        sentiment = environment["sentiment_structure"]
        self.assertIn("limit_up_ladder", sentiment)
        self.assertIn("limit_down_ladder", sentiment)
        self.assertIn("high_level_loss_effect", sentiment)
        if sentiment["limit_up_ladder"].get("state") == "data_missing":
            self.assertEqual(sentiment["limit_up_ladder"]["items"], [])

    def test_local_input_status_does_not_expose_absolute_paths(self) -> None:
        status = self.payload["input_status"]
        self.assertIn("privacy_note", status)
        self.assertTrue(status["public_collectors"])
        for item in status["contracts"]:
            self.assertFalse(item["target"].startswith("/"))
            self.assertNotIn("source", item)
        outcome = next(item for item in status["public_collectors"] if item["id"] == "outcome_prices")
        self.assertIn("observation_count", outcome)
        self.assertIn("evaluated_window_input_count", outcome)

    def test_every_radar_card_has_evidence_conditions_and_action(self) -> None:
        for item in self.payload["opportunity_radar"]:
            self.assertTrue(item["title"])
            self.assertTrue(item["trigger"])
            self.assertTrue(item["action"])
            self.assertIsInstance(item["evidence"], list)
            self.assertIsInstance(item["counter_evidence"], list)
            self.assertIsInstance(item["confirm_conditions"], list)
            self.assertIsInstance(item["invalidation_conditions"], list)

    def test_feed_evidence_uses_origin_timestamp_not_rebuild_time(self) -> None:
        intraday_timestamp = next(item["timestamp"] for item in self.payload["source_registry"] if item["path"] == "intraday.json")
        rows = [
            evidence
            for card in self.payload["opportunity_radar"]
            for evidence in card["evidence"]
            if evidence.get("source") == "intraday.json"
        ]
        self.assertTrue(rows)
        self.assertTrue(all(item["as_of"] == intraday_timestamp for item in rows))

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
        middle_sectors = " ".join(dimensions["middle_deng"]["representative_sectors"])
        for expected in ("光伏", "储能", "新能源汽车", "电力设备", "创新药", "军工", "有色", "新材料"):
            self.assertIn(expected, middle_sectors)
        self.assertEqual(dimensions["microcap"]["direction"], self.payload["market_structure"]["direction"])
        self.assertEqual(dimensions["microcap"]["proxy"]["code"], "932000")
        self.assertIn("不等于纯微盘", dimensions["microcap"]["proxy"]["scope_note"])
        self.assertTrue(self.payload["style_map"]["definition_version"])
        self.assertEqual(dimensions["microcap"]["state"], self.payload["market_structure"]["state"])

    def test_portfolio_does_not_infer_positions(self) -> None:
        portfolio = self.payload["portfolio_risk"]
        self.assertEqual(portfolio["state"], "rules_only")
        self.assertIn("真实持仓数量", portfolio["missing_inputs"])

    def test_signal_review_withholds_unearned_hit_rate(self) -> None:
        review = self.payload["signal_review"]
        if review.get("evaluated_signal_count", 0) < 20:
            self.assertIsNone(review.get("hit_rate"))

    def test_model_evaluation_cannot_auto_promote(self) -> None:
        evaluation = self.payload["model_evaluation"]
        self.assertFalse(evaluation["automatic_live_promotion"])
        self.assertTrue(evaluation["recommendation"]["requires_user_confirmation"])


if __name__ == "__main__":
    unittest.main()

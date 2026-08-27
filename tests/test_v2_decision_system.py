from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
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
            "opportunity_history",
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

    def test_p0_01_radar_cards_require_representative_stock_basis(self) -> None:
        cards = [*self.payload["opportunity_radar"], *self.payload["opportunity_history"]]
        self.assertTrue(cards)
        for item in cards:
            self.assertTrue(item["representative_stocks"], item["title"])
            for stock in item["representative_stocks"]:
                self.assertTrue(stock.get("name"))
                self.assertTrue(stock.get("basis"))
                self.assertTrue(stock.get("stock_code"))
                self.assertNotIn("change_pct", stock)
                if stock.get("stock_change_pct") is not None:
                    self.assertTrue(stock.get("stock_quote_as_of"))
                    self.assertTrue(stock.get("stock_quote_source"))
            metrics = item.get("trigger_metrics") or {}
            self.assertIn(metrics.get("metric_scope"), {"theme_pool", "sector", "market", "security"})

    def test_p0_representative_quotes_have_three_auditable_samples(self) -> None:
        stocks = [
            stock
            for card in [*self.payload["opportunity_radar"], *self.payload["opportunity_history"], *self.payload["validation_queue"]]
            for stock in card.get("representative_stocks", [])
            if stock.get("stock_change_pct") is not None
        ]
        names = {stock["name"] for stock in stocks}
        self.assertTrue({"华海清科", "安集科技", "江丰电子"}.issubset(names))
        self.assertTrue(all(stock.get("stock_code") and stock.get("stock_quote_as_of") and stock.get("stock_quote_source") for stock in stocks))

    def test_same_name_a_h_quotes_require_code_identity(self) -> None:
        builder = V2DecisionSystemBuilder(ROOT)
        builder.sources["v2_representative_quotes"].data = {
            "quotes": [
                {
                    "name": "澜起科技",
                    "code": "sh688008",
                    "stock_change_pct": 3.45,
                    "stock_quote_as_of": "2026-07-20T15:00:00+08:00",
                    "stock_quote_source": "A股测试行情",
                },
                {
                    "name": "澜起科技",
                    "code": "hk06809",
                    "stock_change_pct": 3.53,
                    "stock_quote_as_of": "2026-07-20T16:08:00+08:00",
                    "stock_quote_source": "港股测试行情",
                },
            ]
        }
        self.assertEqual(builder._representative_quote("澜起科技"), {})

    def test_p01_all_representative_stocks_have_quote_closure(self) -> None:
        cards = [*self.payload["opportunity_radar"], *self.payload["opportunity_history"], *self.payload["validation_queue"]]
        stocks = [stock for card in cards for stock in card.get("representative_stocks", [])]
        self.assertTrue(stocks)
        self.assertTrue(all(stock.get("stock_code") for stock in stocks))
        self.assertTrue(all(stock.get("stock_change_pct") is not None for stock in stocks))
        self.assertTrue(all(stock.get("stock_quote_as_of") and stock.get("stock_quote_source") for stock in stocks))

    def test_p01_ambiguous_contribution_metric_is_not_exposed(self) -> None:
        cards = [*self.payload["opportunity_radar"], *self.payload["opportunity_history"], *self.payload["validation_queue"]]
        basis_text = " ".join(str(stock.get("basis") or "") for card in cards for stock in card.get("representative_stocks", []))
        self.assertNotIn("领跌贡献", basis_text)

    def test_p01_historical_alert_uses_theme_trigger_metric(self) -> None:
        builder = V2DecisionSystemBuilder(ROOT)
        quality = builder._quality_gate()
        alert = builder.sources["alert"].data
        rows = [*alert.get("alerts", []), *alert.get("historical_alerts", [])]
        cards = [builder._alert_card(item, quality) for item in rows]
        self.assertTrue(cards)
        self.assertTrue(
            all(card.get("trigger_metrics", {}).get("metric_scope") in {"theme_pool", "sector"} for card in cards)
        )
        for item in rows:
            self.assertTrue(all("change_pct" not in leader for leader in item.get("leaders", [])))
            self.assertTrue(all("score" not in leader for leader in item.get("leaders", [])))

    @staticmethod
    def payload_builder_source(name: str) -> dict:
        return V2DecisionSystemBuilder(ROOT).sources[name].data

    def test_p0_cards_expose_risk_and_invalidation(self) -> None:
        cards = [*self.payload["opportunity_radar"], *self.payload["validation_queue"]]
        self.assertTrue(cards)
        self.assertTrue(all(card.get("risk_factors") for card in cards))
        self.assertTrue(all(card.get("invalidation_conditions") for card in cards))

    def test_p0_02_expired_and_missing_validity_are_not_current_radar(self) -> None:
        payload = V2DecisionSystemBuilder(
            ROOT,
            now=datetime(2027, 1, 2, 12, 0, tzinfo=timezone.utc),
        ).build()
        self.assertTrue(payload["opportunity_history"])
        self.assertTrue(all(item["freshness_state"] != "expired" for item in payload["opportunity_radar"]))
        self.assertTrue(all(item.get("valid_until") for item in payload["opportunity_radar"]))
        self.assertTrue(all(item["state"] == "expired" for item in payload["opportunity_history"]))

    def test_p0_04_validation_evidence_stays_inside_theme(self) -> None:
        from scripts.build_opportunity_watch import make_item

        medicine = make_item(
            "医药修复链",
            "专题",
            "恒瑞医药与科伦药业修复；Micron、HBM、半导体设备和雅克科技属于其他主题。",
            "medium",
        )
        self.assertTrue(medicine["theme_id"])
        self.assertTrue(medicine["evidence_refs"])
        visible = " ".join(item.get("summary", "") for item in medicine["evidence_refs"] if item.get("accepted"))
        for forbidden in ("Micron", "300mm", "HBM", "雅克科技", "半导体设备"):
            self.assertNotIn(forbidden, visible)
        self.assertTrue(all(item.get("evidence_id") for item in medicine["evidence_refs"]))

    def test_structured_evening_evidence_exposes_fact_not_backend_contract(self) -> None:
        from scripts.build_opportunity_watch import items_from_evening

        items = items_from_evening({
            "p0_alerts": [{
                "title": "美股芯片股盘中走弱，AI硬件风险尚未解除",
                "why_p0": "隔夜芯片股走弱",
                "watch_next_day": ["若A股算力代表股继续低开，先回避。"],
                "evidence": [{
                    "type": "external_quote",
                    "source": "腾讯美股公开行情",
                    "timestamp": "2026-07-30T20:00:47+08:00",
                    "detail": "英伟达 -3.55%，价格190.01美元",
                }],
            }]
        })
        raw = json.dumps(items, ensure_ascii=False)
        self.assertIn("英伟达 -3.55%", raw)
        for forbidden in ('external_quote', 'timestamp', 'detail', '腾讯美股公开行情'):
            self.assertNotIn(forbidden, raw)
        self.assertFalse(any(item.get("theme") == "港股科网AI应用映射" for item in items))

    def test_semiconductor_watch_uses_early_candidate_ah_repair_rules(self) -> None:
        from scripts.build_opportunity_watch import make_item

        item = make_item("存储/HBM", "专题", "兆易创新、澜起科技和港股半导体等待盘中修复。", "high")
        rules = " ".join(item["confirm_rules"])
        invalidation = " ".join(item["invalidate_rules"])
        self.assertIn("早期候选", rules)
        self.assertIn("A/H共振", rules)
        self.assertIn("分时均价", invalidation)
        self.assertIn("兆易创新H", item["watch_stocks"])
        self.assertIn("澜起科技H", item["watch_stocks"])

    def test_feed_evidence_uses_origin_timestamp_not_rebuild_time(self) -> None:
        builder = V2DecisionSystemBuilder(ROOT)
        quality = builder._quality_gate()
        feed = builder.sources["decision_feed"].data
        cards = [
            builder._feed_card(item, section, quality)
            for section in ("risks", "opportunities", "verifications")
            for item in feed.get(section, [])
            if isinstance(item, dict)
        ]
        rows = [
            evidence
            for card in cards
            for evidence in card["evidence"]
            if evidence.get("source") and evidence.get("as_of")
        ]
        self.assertTrue(rows)
        source_timestamps = {
            source.path.name: source.timestamp
            for source in builder.sources.values()
            if source.timestamp
        }
        rebuild_time = self.payload["system"]["generated_at"]
        for item in rows:
            names = [name.strip() for name in str(item["source"]).split(",")]
            expected = {source_timestamps.get(name) for name in names} - {None}
            self.assertIn(item["as_of"], expected)
            self.assertNotEqual(item["as_of"], rebuild_time)

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

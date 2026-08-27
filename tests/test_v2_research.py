from __future__ import annotations

import unittest
from pathlib import Path

from v2_platform.research import V2ResearchSystemBuilder


ROOT = Path(__file__).resolve().parents[1]


class V2ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.research, cls.stock_pool = V2ResearchSystemBuilder(ROOT).build()

    def test_required_long_term_domains_exist(self) -> None:
        ids = {item["id"] for item in self.research["domains"]}
        self.assertTrue({"ai_hardware", "ai_software", "embodied_ai", "medicine", "fusion", "quantum"}.issubset(ids))

    def test_uncovered_domains_are_explicit_gaps(self) -> None:
        domains = {item["id"]: item for item in self.research["domains"]}
        self.assertEqual(domains["fusion"]["coverage_state"], "template_ready_mapping_gap")
        self.assertEqual(domains["quantum"]["coverage_state"], "mapped")

    def test_fusion_and_quantum_templates_have_evidence_and_invalidation(self) -> None:
        domains = {item["id"]: item for item in self.research["domains"]}
        for domain_id in ("fusion", "quantum"):
            template = domains[domain_id]["research_template"]
            self.assertTrue(template["logic_chain"])
            self.assertTrue(template["tracking_indicators"])
            self.assertTrue(template["confirmation_conditions"])
            self.assertTrue(template["invalidation_conditions"])
            self.assertTrue(all(item["type"].startswith("official") for item in template["source_refs"]))

    def test_ai_interconnect_tracking_is_governed_and_visible(self) -> None:
        domains = {item["id"]: item for item in self.research["domains"]}
        domain = domains["ai_interconnect"]
        template = domain["research_template"]
        self.assertEqual(domain["coverage_state"], "mapped")
        self.assertIn("AI高速互连与内存互连", {item["name"] for item in domain["topics"]})
        self.assertGreaterEqual(len(template["tracking_indicators"]), 8)
        self.assertEqual(template["current_research_judgement"]["classification"], "逻辑成立但未交易确认")
        self.assertTrue(all(item["type"].startswith("official") for item in template["source_refs"]))

    def test_longxin_ipo_transmission_tracking_is_visible_and_governed(self) -> None:
        topics = {
            topic["name"]: topic
            for domain in self.research["domains"]
            for topic in domain["topics"]
        }
        topic = topics["长鑫存储IPO映射"]
        self.assertEqual(topic["priority"], 1)
        self.assertEqual(topic["level"], "事件传导专题")
        self.assertIn(topic["current_status"], {"强化", "阶段性确认", "观察", "风险", "资金博弈"})
        self.assertTrue(
            {"长鑫科技", "中微公司", "拓荆科技", "盛美上海", "华海清科", "芯源微", "中科飞测"}
            .issubset(set(topic["stock_names"]))
        )
        focus = " ".join(topic["focus"])
        self.assertIn("确认条件", focus)
        self.assertIn("失效条件", focus)
        self.assertIn("不代表新增用户自选", focus)

    def test_stock_pool_deduplicates_codes_and_preserves_sources(self) -> None:
        stocks = self.stock_pool["stocks"]
        codes = [item["code"] for item in stocks]
        self.assertEqual(len(codes), len(set(codes)))
        overlapped = [item for item in stocks if len(item["source_pools"]) > 1]
        self.assertTrue(overlapped)

    def test_ai_training_and_edge_formal_observation_is_separate_from_user_assets(self) -> None:
        expected = {
            "sh601138", "sz300308", "sh600183", "sh688008",
            "sh603893", "sh688099", "sh688018", "sh688608",
        }
        stocks = {
            item["code"]: item
            for item in self.stock_pool["stocks"]
            if item.get("formal_observation_requested") is True
            and item.get("chain_side") in {"training", "edge"}
        }
        self.assertEqual(set(stocks), expected)
        self.assertTrue(all(item["observation_source"] == "research_import" for item in stocks.values()))
        self.assertTrue(all(item["is_user_asset"] is False for item in stocks.values()))
        self.assertTrue(all(item["trading_candidate_opt_in"] is False for item in stocks.values()))
        self.assertTrue(all(item["counter_evidence"] for item in stocks.values()))
        self.assertTrue(all(item["trigger_conditions"] for item in stocks.values()))
        self.assertTrue(all(item["invalidation_conditions"] for item in stocks.values()))
        self.assertEqual(
            {item["chain_side"] for item in stocks.values()},
            {"training", "edge"},
        )

    def test_edge_ai_domain_and_observation_topic_are_visible(self) -> None:
        domains = {item["id"]: item for item in self.research["domains"]}
        self.assertEqual(domains["edge_ai"]["coverage_state"], "mapped")
        self.assertIn("端侧AI推理持续观察", {item["name"] for item in domains["edge_ai"]["topics"]})
        self.assertIn("config/v2-formal-observation.json", self.research["source_files"])

    def test_lithography_supply_chain_tracking_is_governed_and_separate_from_user_assets(self) -> None:
        domains = {item["id"]: item for item in self.research["domains"]}
        domain = domains["semiconductor_lithography"]
        template = domain["research_template"]
        self.assertEqual(domain["coverage_state"], "mapped")
        self.assertIn("光刻产业链供应链卡位持续观察", {item["name"] for item in domain["topics"]})
        self.assertEqual(template["current_research_judgement"]["classification"], "逻辑成立但未交易确认")
        self.assertGreaterEqual(len(template["value_content"]), 5)
        self.assertTrue(all(item["type"].startswith("official") for item in template["source_refs"]))

        expected = {
            "sh688037", "sh688502", "sh688268", "sh603650",
            "sz300054", "sz300346", "sh688401", "sh688138",
        }
        lithography_sides = {
            "track_equipment", "duv_optics", "duv_laser_gas", "photoresist_platform",
            "photoresist_commercialization", "arf_photoresist", "photomask_advanced_node",
            "photomask_revenue_visibility",
        }
        stocks = {
            item["code"]: item
            for item in self.stock_pool["stocks"]
            if item.get("formal_observation_requested") is True
            and item.get("chain_side") in lithography_sides
        }
        self.assertEqual(set(stocks), expected)
        self.assertTrue(all(item["observation_source"] == "research_import" for item in stocks.values()))
        self.assertTrue(all(item["is_user_asset"] is False for item in stocks.values()))
        self.assertTrue(all(item["trading_candidate_opt_in"] is False for item in stocks.values()))
        self.assertTrue(all(item["roles"] == ["unclassified"] for item in stocks.values()))
        self.assertTrue(all(item["counter_evidence"] for item in stocks.values()))
        self.assertTrue(all(item["trigger_conditions"] for item in stocks.values()))
        self.assertTrue(all(item["invalidation_conditions"] for item in stocks.values()))
        self.assertTrue(all(item["source_refs"] for item in stocks.values()))

    def test_roles_are_not_inferred_without_explicit_tags_or_topic_names(self) -> None:
        allowed = {"leader", "core", "high_beta", "platform", "unclassified"}
        for item in self.stock_pool["stocks"]:
            self.assertTrue(set(item["roles"]).issubset(allowed))
            if item["roles"] != ["unclassified"]:
                joined = " ".join([*item["tags"], *(theme["name"] for theme in item["themes"])])
                self.assertTrue(any(keyword in joined for keyword in ("龙头", "中军", "弹性", "平台", "指数权重", "核心资产", "大盘权重")))
            self.assertTrue(item["role_evidence"])

    def test_stock_contract_has_decision_bridge_fields(self) -> None:
        required = {"themes", "roles", "role_evidence", "attention_reason", "catalysts", "trigger_conditions", "invalidation_conditions", "history_status"}
        for item in self.stock_pool["stocks"]:
            self.assertTrue(required.issubset(item))


if __name__ == "__main__":
    unittest.main()

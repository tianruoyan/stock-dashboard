from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from v2_platform.stock_pool_v22 import V22StockPoolBuilder, quote_map, research_assessment


ROOT = Path(__file__).resolve().parents[1]


def complete_stock() -> dict:
    return {
        "code": "sh688981",
        "name": "中芯国际",
        "identity_source": "交易所证券主数据",
        "domains": [{"id": "ai_hardware", "name": "AI硬件"}],
        "themes": [{"id": "semiconductor", "name": "半导体"}],
        "roles": ["unclassified"],
        "role_evidence": ["缺少显式龙头证据，保持未分类"],
        "attention_reason": "晶圆代工持续研究",
        "counter_evidence": ["资本开支不及预期"],
        "catalysts": ["季度财报"],
        "trigger_conditions": ["板块放量共振"],
        "invalidation_conditions": ["跌破关键支撑且板块退潮"],
        "suitable_environment": ["主线确认"],
        "unsuitable_environment": ["拥挤退潮"],
    }


class V22StockPoolTests(unittest.TestCase):
    def test_formal_observation_quote_can_come_directly_from_representative_quote_feed(self) -> None:
        quotes = quote_map({}, {"quotes": [{
            "name": "乐鑫科技",
            "code": "sh688018",
            "stock_change_pct": 5.04,
            "stock_quote_as_of": "2026-08-05T15:00:00+08:00",
            "stock_quote_source": "腾讯与富途行情交叉核验",
        }]})
        self.assertEqual(quotes["sh688018"]["change_pct"], 5.04)
        self.assertEqual(quotes["sh688018"]["name"], "乐鑫科技")

    def test_research_gate_accepts_explicit_unclassified_but_requires_all_evidence(self) -> None:
        stock = complete_stock()
        accepted = research_assessment(stock)
        self.assertTrue(accepted["eligible"])
        self.assertEqual(accepted["missing"], [])
        stock["suitable_environment"] = []
        rejected = research_assessment(stock)
        self.assertFalse(rejected["eligible"])
        self.assertIn("适用与不适用市场环境", rejected["missing"])

    def test_current_inventory_is_explained_without_fabricating_roles(self) -> None:
        payload = V22StockPoolBuilder(ROOT).build()
        source_count = len(json.loads((ROOT / "data/v2/stock-pool.json").read_text())["stocks"])
        self.assertEqual(payload["inventory"]["source_stock_count"], source_count)
        self.assertEqual(payload["inventory"]["explained_destination_count"], source_count)
        self.assertGreaterEqual(payload["inventory"]["role_unclassified_count"], 104)
        self.assertEqual(payload["inventory"]["watch_small_overlap_count"], 9)
        unclassified = [
            item for item in payload["formal_observation"]["near_ready_items"]
            if item["roles"] == ["unclassified"]
        ]
        self.assertTrue(unclassified)
        self.assertTrue(all(item["role_evidence"] for item in unclassified))

    def test_public_shadow_contains_no_user_owned_fields_or_records(self) -> None:
        payload = V22StockPoolBuilder(ROOT).build()
        rendered = json.dumps(payload, ensure_ascii=False)
        for forbidden in ("user_priority", "user_intent", "user_note", "source_account_id"):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual(payload["user_asset_layer"]["public_records"], [])
        self.assertFalse(payload["user_asset_layer"]["public_user_fields_included"])
        self.assertFalse(payload["guardrails"]["user_assets_modified"])

    def test_temporary_candidates_never_auto_upgrade_or_become_user_assets(self) -> None:
        payload = V22StockPoolBuilder(ROOT).build()
        temporary = payload["temporary_candidates"]
        self.assertFalse(temporary["automatic_upgrade"])
        self.assertTrue(all(item["is_user_asset"] is False for item in temporary["items"]))
        self.assertTrue(all(item["formal_observation"] is False for item in temporary["items"]))
        self.assertTrue(all(item["applied"] is False for item in temporary["items"]))
        research_codes = {
            item["code"]
            for item in [
                *payload["formal_observation"]["items"],
                *payload["formal_observation"]["near_ready_items"],
            ]
        }
        self.assertTrue(research_codes.isdisjoint({item["code"] for item in temporary["items"]}))

    def test_trading_candidates_are_a_subset_of_formal_observation(self) -> None:
        payload = V22StockPoolBuilder(ROOT).build()
        formal_codes = {item["code"] for item in payload["formal_observation"]["items"]}
        trading_codes = {item["code"] for item in payload["trading_candidates"]["items"]}
        self.assertTrue(trading_codes.issubset(formal_codes))
        self.assertTrue(all(item["formal_observation_required"] for item in payload["trading_candidates"]["items"]))

    def test_requested_ai_research_observations_are_active_but_not_trading_candidates(self) -> None:
        expected = {
            "sh601138", "sz300308", "sh600183", "sh688008",
            "sh603893", "sh688099", "sh688018", "sh688608",
        }
        payload = V22StockPoolBuilder(ROOT).build()
        formal = {
            item["code"]: item
            for item in payload["formal_observation"]["items"]
            if item.get("formal_observation_requested") is True
        }
        self.assertTrue(expected.issubset(formal))
        ai_formal = [formal[code] for code in expected]
        self.assertTrue(all(item["is_user_asset"] is False for item in ai_formal))
        self.assertTrue(all(item["observation_source"] == "research_import" for item in ai_formal))
        self.assertTrue(all(item["trading_candidate_opt_in"] is False for item in ai_formal))
        trading_codes = {item["code"] for item in payload["trading_candidates"]["items"]}
        self.assertTrue(expected.isdisjoint(trading_codes))
        self.assertFalse(payload["guardrails"]["research_observation_modified_user_assets"])

    def test_quotes_are_real_or_explicitly_waiting(self) -> None:
        payload = V22StockPoolBuilder(ROOT).build()
        rows = [
            *payload["formal_observation"]["items"],
            *payload["formal_observation"]["near_ready_items"],
            *payload["temporary_candidates"]["items"],
        ]
        self.assertTrue(rows)
        for item in rows:
            quote = item["quote"]
            if quote["change_pct"] is None:
                self.assertEqual(quote["state"], "行情待核验")
                self.assertIsNone(quote["as_of"])
                self.assertIsNone(quote["source"])
            else:
                self.assertEqual(quote["state"], "真实行情已核验")
                self.assertTrue(quote["as_of"])
                self.assertTrue(quote["source"])

    def test_same_name_a_h_assets_keep_distinct_quotes(self) -> None:
        decision = json.loads((ROOT / "data/v2/decision-system.json").read_text())
        representative = json.loads((ROOT / "data/v2/inputs/representative-stock-quotes.json").read_text())
        montage = quote_map(decision, representative)
        self.assertIn("sh688008", montage)
        self.assertIn("hk06809", montage)
        self.assertIsNotNone(montage["sh688008"]["change_pct"])
        self.assertIsNotNone(montage["hk06809"]["change_pct"])
        self.assertNotEqual(montage["sh688008"]["change_pct"], montage["hk06809"]["change_pct"])

    def test_style_relations_are_evidence_not_asset_membership(self) -> None:
        payload = V22StockPoolBuilder(ROOT).build()
        self.assertFalse(payload["style_evidence"]["may_change_user_assets"])
        self.assertTrue(payload["style_evidence"]["microcap_is_separate"])
        self.assertFalse(payload["guardrails"]["style_pool_used_as_stock_pool"])


if __name__ == "__main__":
    unittest.main()

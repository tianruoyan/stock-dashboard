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
        for domain_id in ("fusion", "quantum"):
            if not domains[domain_id]["topic_count"] and not domains[domain_id]["stock_count"]:
                self.assertEqual(domains[domain_id]["coverage_state"], "coverage_gap")

    def test_stock_pool_deduplicates_codes_and_preserves_sources(self) -> None:
        stocks = self.stock_pool["stocks"]
        codes = [item["code"] for item in stocks]
        self.assertEqual(len(codes), len(set(codes)))
        overlapped = [item for item in stocks if len(item["source_pools"]) > 1]
        self.assertTrue(overlapped)

    def test_roles_are_not_inferred_without_explicit_tags(self) -> None:
        allowed = {"leader", "core", "high_beta", "platform", "unclassified"}
        for item in self.stock_pool["stocks"]:
            self.assertTrue(set(item["roles"]).issubset(allowed))
            if item["roles"] != ["unclassified"]:
                joined = " ".join(item["tags"])
                self.assertTrue(any(keyword in joined for keyword in ("龙头", "中军", "弹性", "平台")))

    def test_stock_contract_has_decision_bridge_fields(self) -> None:
        required = {"themes", "roles", "attention_reason", "catalysts", "trigger_conditions", "invalidation_conditions", "history_status"}
        for item in self.stock_pool["stocks"]:
            self.assertTrue(required.issubset(item))


if __name__ == "__main__":
    unittest.main()

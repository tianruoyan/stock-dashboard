from __future__ import annotations

import unittest
from pathlib import Path

from v2_platform.completion_audit import V2CompletionAuditBuilder


ROOT = Path(__file__).resolve().parents[1]


class V2CompletionAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = V2CompletionAuditBuilder(ROOT).build()

    def test_audit_covers_full_original_scope(self) -> None:
        ids = {item["id"] for item in self.report["checks"]}
        required = {
            "design_document", "migration_audit", "data_lineage_model", "phased_route_and_visual",
            "data_quality_gate", "idempotent_data_publisher", "public_data_collectors", "decision_cockpit_radar", "cross_market",
            "style_dimensions", "microcap_data", "two_sided_sentiment", "research_room", "stock_pool",
            "event_source_governance", "official_event_input", "blogger_source_manager", "blogger_accounts", "automation_routing", "immutable_replay", "outcome_prices",
            "offline_model_evaluation", "portfolio_authorization", "no_automatic_trading", "parallel_v1_v2", "v1_rollback", "production_cutover"
        }
        self.assertTrue(required.issubset(ids))

    def test_audit_does_not_claim_complete_with_external_data_gaps(self) -> None:
        if self.report["counts"]["data_pending"] or self.report["counts"]["user_confirmation"]:
            self.assertNotEqual(self.report["completion_state"], "complete")

    def test_no_internal_implementation_failure_remains(self) -> None:
        self.assertEqual(self.report["counts"]["missing"], 0)
        self.assertEqual(self.report["counts"]["failed"], 0)


if __name__ == "__main__":
    unittest.main()

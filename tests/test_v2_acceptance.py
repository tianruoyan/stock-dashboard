from __future__ import annotations

import json
import unittest
from pathlib import Path

from v2_platform.acceptance import V2AcceptanceBuilder


ROOT = Path(__file__).resolve().parents[1]


class V2AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = V2AcceptanceBuilder(ROOT).build()

    def test_shadow_platform_accepts_without_promoting_degraded_data(self) -> None:
        self.assertEqual(self.report["shadow_acceptance"], "passed")
        if self.report["quality_state"] != "usable":
            self.assertEqual(self.report["production_promotion"], "hold")
        parallel = next(item for item in self.report["checks"] if item["id"] == "parallel_operation")
        self.assertTrue(parallel["passed"])

    def test_rollback_keeps_production_v1_baseline(self) -> None:
        rollout = json.loads((ROOT / "config/v2-rollout.json").read_text(encoding="utf-8"))
        self.assertEqual(self.report["rollback_rehearsal"]["status"], "passed")
        self.assertEqual(
            self.report["rollback_rehearsal"]["baseline_commit"],
            rollout["production_v1"]["baseline_commit"],
        )
        self.assertEqual(self.report["rollback_rehearsal"]["changed_protected_paths"], [])
        protected = set(self.report["rollback_rehearsal"]["protected_paths"])
        self.assertNotIn("config/watchlist.json", protected)
        self.assertTrue({"config/alert-config.json", "config/topics-list.json"}.issubset(protected))

    def test_confirmation_list_covers_exposed_gaps(self) -> None:
        ids = {item["id"] for item in self.report["confirmation_items"]}
        self.assertTrue({"style_taxonomy", "microcap_proxy", "research_gaps", "stock_roles", "portfolio_and_outcomes", "production_promotion"}.issubset(ids))

    def test_completion_audit_has_no_internal_failure(self) -> None:
        check = next(item for item in self.report["checks"] if item["id"] == "completion_audit_internal")
        self.assertTrue(check["passed"])


if __name__ == "__main__":
    unittest.main()

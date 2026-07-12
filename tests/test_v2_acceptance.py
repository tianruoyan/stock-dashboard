from __future__ import annotations

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

    def test_rollback_keeps_production_v1_baseline(self) -> None:
        self.assertEqual(self.report["rollback_rehearsal"]["status"], "passed")
        self.assertTrue(self.report["rollback_rehearsal"]["production_head"].startswith("2e5f149"))

    def test_confirmation_list_covers_exposed_gaps(self) -> None:
        ids = {item["id"] for item in self.report["confirmation_items"]}
        self.assertTrue({"style_taxonomy", "microcap_proxy", "research_gaps", "stock_roles", "portfolio_and_outcomes", "production_promotion"}.issubset(ids))


if __name__ == "__main__":
    unittest.main()

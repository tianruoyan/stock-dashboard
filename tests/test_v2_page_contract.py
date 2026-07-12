from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class V2PageContractTests(unittest.TestCase):
    def test_required_decision_containers_are_hard_required(self) -> None:
        html = (ROOT / "v2.html").read_text(encoding="utf-8")
        ids = set(re.findall(r'id="([^"]+)"', html))
        required = {
            "data-quality-gate",
            "market-environment",
            "opportunity-risk-radar",
            "validation-queue",
            "portfolio-risk",
            "signal-review",
        }
        self.assertTrue(required.issubset(ids))

    def test_radar_precedes_secondary_modules(self) -> None:
        html = (ROOT / "v2.html").read_text(encoding="utf-8")
        self.assertLess(html.index('id="opportunity-risk-radar"'), html.index('id="style-map"'))
        self.assertLess(html.index('id="opportunity-risk-radar"'), html.index('id="research-themes"'))

    def test_generated_data_is_shadow_only(self) -> None:
        data = json.loads((ROOT / "data" / "v2" / "decision-system.json").read_text(encoding="utf-8"))
        self.assertEqual(data["system"]["mode"], "shadow_only")
        self.assertFalse(data["system"]["production_behavior_changed"])

    def test_opportunity_filter_uses_kind_and_waiting_uses_state(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn('data-radar-kind="${escapeHtml(kind)}"', code)
        self.assertIn('data-radar-state="${escapeHtml(card.state)}"', code)
        self.assertIn('activeRadarFilter === "waiting" && waiting', code)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class V22RadarContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = json.loads((ROOT / "data/v2/v22/decision-system-candidate.json").read_text(encoding="utf-8"))

    def test_every_visible_current_or_validation_case_has_complete_representatives(self) -> None:
        cards = [*self.candidate["current_cases"], *self.candidate["validation_cases"]]
        self.assertGreaterEqual(len(cards), 5)
        for card in cards:
            self.assertTrue(card["representative_stocks"])
            for stock in card["representative_stocks"]:
                for field in ("stock_code", "name", "stock_change_pct", "stock_quote_as_of", "stock_quote_source", "role", "basis"):
                    self.assertIsNotNone(stock.get(field), f"{card['title']} missing {field}")

    def test_five_sample_cards_have_judgment_basis_risk_action_and_conditions(self) -> None:
        for card in self.candidate["validation_cases"][:5]:
            self.assertTrue(card["current_judgment"])
            self.assertTrue(card["representative_stocks"])
            self.assertTrue(card["risk_factors"])
            self.assertTrue(card["action"])
            self.assertTrue(card["confirm_conditions"])
            self.assertTrue(card["invalidation_conditions"])
            self.assertTrue(card["environment_gate"])

    def test_unformed_clues_do_not_appear_as_cards(self) -> None:
        visible_ids = {item["id"] for item in [*self.candidate["current_cases"], *self.candidate["validation_cases"]]}
        cases = json.loads((ROOT / "data/v2/v22/decision-cases.json").read_text(encoding="utf-8"))
        self.assertFalse(visible_ids & set(cases["unformed_clue_ids"]))
        self.assertFalse(visible_ids & set(cases.get("parked_clue_ids") or []))


if __name__ == "__main__":
    unittest.main()

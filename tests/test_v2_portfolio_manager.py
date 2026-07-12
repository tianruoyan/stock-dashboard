from __future__ import annotations

import unittest

import server


class PortfolioManagerTests(unittest.TestCase):
    def test_normalizes_portfolio_without_trade_authorization(self) -> None:
        payload = server.validate_portfolio_payload({
            "holdings": [{"code": "600000", "name": "浦发银行", "quantity": 1000, "cost": 10.5}],
            "cash": 50000,
            "risk_budget": {"max_single_position_pct": 20, "max_theme_pct": 35, "max_total_invested_pct": 80, "max_drawdown_pct": 12},
        })
        self.assertEqual(payload["holdings"][0]["code"], "sh600000")
        self.assertFalse(payload["trade_authorization"])
        self.assertEqual(payload["risk_budget"]["max_single_position_pct"], 20.0)

    def test_rejects_duplicates_and_invalid_percentages(self) -> None:
        with self.assertRaises(ValueError):
            server.validate_portfolio_payload({"holdings": [
                {"code": "600000", "name": "a", "quantity": 1, "cost": 1},
                {"code": "sh600000", "name": "b", "quantity": 1, "cost": 1},
            ], "cash": 0, "risk_budget": {}})
        with self.assertRaises(ValueError):
            server.validate_portfolio_payload({"holdings": [], "cash": 0, "risk_budget": {"max_single_position_pct": 101}})


if __name__ == "__main__":
    unittest.main()

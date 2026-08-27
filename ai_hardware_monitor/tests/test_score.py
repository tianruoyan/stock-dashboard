from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_hardware_monitor.engine.score import evaluate_snapshot


ROOT = Path(__file__).resolve().parents[1]
CHINA_TZ = timezone(timedelta(hours=8))


def complete_snapshot(now: datetime) -> dict:
    return {
        "trade_date": now.date().isoformat(),
        "as_of": now.isoformat(timespec="seconds"),
        "source_quality": {"state": "usable", "sources": [], "missing": []},
        "sector": {
            "relative_outperformance_pct": 3.2,
            "market_rank": 2,
            "advance_ratio_pct": 75,
        },
        "leaders": {
            "outperform_count": 2,
            "outperform_ratio": 0.6667,
            "median_turnover_pace": 1.6,
            "trend_confirmed_ratio": 0.6667,
        },
        "funds": {
            "continuous_net_inflow_days": 2,
            "pool_net_inflow_yi": 8.2,
            "etf_net_inflow_yi": 1.1,
        },
        "market_environment": {
            "market_turnover_ratio": 1.12,
            "technology_advance_ratio_pct": 65,
            "limit_up_down_ratio": 4,
        },
    }


class ScoreEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.weights = json.loads((ROOT / "config" / "weights.json").read_text(encoding="utf-8"))
        cls.rules = json.loads((ROOT / "config" / "rules.json").read_text(encoding="utf-8"))
        cls.now = datetime(2026, 7, 23, 10, 30, tzinfo=CHINA_TZ)

    def evaluate(self, snapshot: dict) -> dict:
        return evaluate_snapshot(snapshot, self.weights, self.rules, now=self.now)

    def test_full_confirmation_launches(self) -> None:
        result = self.evaluate(complete_snapshot(self.now))
        self.assertEqual(100, result["score"])
        self.assertEqual("launch", result["state"]["code"])
        self.assertTrue(all(item["passed"] for item in result["launch_gates"]))

    def test_high_score_without_top_three_stays_observe(self) -> None:
        snapshot = complete_snapshot(self.now)
        snapshot["sector"]["market_rank"] = 5
        result = self.evaluate(snapshot)
        self.assertGreaterEqual(result["score"], 80)
        self.assertEqual("observe", result["state"]["code"])
        rank_gate = next(item for item in result["launch_gates"] if item["id"] == "sector_rank")
        self.assertFalse(rank_gate["passed"])

    def test_complete_weak_snapshot_is_risk(self) -> None:
        snapshot = complete_snapshot(self.now)
        snapshot["sector"].update({"relative_outperformance_pct": -2, "market_rank": 50, "advance_ratio_pct": 25})
        snapshot["leaders"].update({"outperform_count": 0, "outperform_ratio": 0, "median_turnover_pace": 0.7, "trend_confirmed_ratio": 0})
        snapshot["funds"].update({"continuous_net_inflow_days": 0, "pool_net_inflow_yi": -3, "etf_net_inflow_yi": -1})
        snapshot["market_environment"].update({"market_turnover_ratio": 0.8, "technology_advance_ratio_pct": 25, "limit_up_down_ratio": 0.5})
        result = self.evaluate(snapshot)
        self.assertEqual(0, result["score"])
        self.assertEqual("risk", result["state"]["code"])
        self.assertEqual(1.0, result["coverage_ratio"])

    def test_missing_data_does_not_become_false_risk(self) -> None:
        snapshot = complete_snapshot(self.now)
        snapshot["sector"]["market_rank"] = None
        snapshot["funds"] = {"continuous_net_inflow_days": None, "pool_net_inflow_yi": None, "etf_net_inflow_yi": None}
        snapshot["market_environment"] = {"market_turnover_ratio": None, "technology_advance_ratio_pct": None, "limit_up_down_ratio": None}
        result = self.evaluate(snapshot)
        self.assertLess(result["coverage_ratio"], 0.65)
        self.assertEqual("observe", result["state"]["code"])

    def test_stale_snapshot_is_observe(self) -> None:
        snapshot = complete_snapshot(self.now - timedelta(days=1))
        result = self.evaluate(snapshot)
        self.assertEqual("observe", result["state"]["code"])
        self.assertFalse(result["data_quality"]["usable"])


if __name__ == "__main__":
    unittest.main()

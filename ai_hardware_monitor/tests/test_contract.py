from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_hardware_monitor.engine.checkpoints import next_checkpoint, resolve_checkpoint
from ai_hardware_monitor.engine.collector import LiveSnapshotCollector


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = PROJECT_ROOT / "ai_hardware_monitor"
CHINA_TZ = timezone(timedelta(hours=8))


class ContractTest(unittest.TestCase):
    def test_three_required_checkpoints(self) -> None:
        config = json.loads((MODULE_ROOT / "config" / "checkpoints.json").read_text(encoding="utf-8"))
        self.assertEqual(["09:35", "10:30", "14:30"], [item["scheduled_at"] for item in config["checkpoints"]])
        current = datetime(2026, 7, 23, 10, 30, tzinfo=CHINA_TZ)
        self.assertEqual("morning_confirmation", resolve_checkpoint(current, config)["id"])
        self.assertEqual("late_confirmation", next_checkpoint(current, config)["id"])
        self.assertIsNone(resolve_checkpoint(datetime(2026, 7, 23, 10, 25, tzinfo=CHINA_TZ), config))

    def test_stock_pool_is_exact(self) -> None:
        config = json.loads((MODULE_ROOT / "config" / "stocks.json").read_text(encoding="utf-8"))
        names = [item["name"] for item in config["stocks"]]
        self.assertEqual(["新易盛", "中际旭创", "天孚通信", "沪电股份", "胜宏科技", "生益科技", "锐捷网络", "盛科通信"], names)
        self.assertFalse(config["proxy"]["official_index"])

    def test_dashboard_and_hub_entry_exist(self) -> None:
        page = (MODULE_ROOT / "dashboard" / "ai_hardware.html").read_text(encoding="utf-8")
        home = (PROJECT_ROOT / "v2.html").read_text(encoding="utf-8")
        research = (PROJECT_ROOT / "v2-research.html").read_text(encoding="utf-8")
        for required_id in ["total-score", "category-grid", "gate-list", "stock-rows", "alert-list", "intraday-trigger-state", "intraday-trigger-conditions"]:
            self.assertIn(f'id="{required_id}"', page)
        self.assertIn('href="v2-research.html"', home)
        self.assertIn('href="ai_hardware_monitor/dashboard/ai_hardware.html"', research)
        self.assertIn("V2 专题模块 · 版本 1.0", page)
        self.assertIn('href="../../v2.html"', page)
        self.assertIn('href="../../v2-logic.html"', page)
        self.assertIn('href="http://127.0.0.1:8877/index.html">返回 V1</a>', page)
        self.assertNotIn("查看 V1 规格", page)

    def test_total_weights_equal_one_hundred(self) -> None:
        weights = json.loads((MODULE_ROOT / "config" / "weights.json").read_text(encoding="utf-8"))
        categories = weights["categories"]
        self.assertEqual(100, sum(item["max_points"] for item in categories.values()))
        for item in categories.values():
            self.assertEqual(item["max_points"], sum(item["components"].values()))

    def test_collector_normalizes_star_market_volume_units(self) -> None:
        stock_config = json.loads((MODULE_ROOT / "config" / "stocks.json").read_text(encoding="utf-8"))
        codes = [item["code"] for item in stock_config["stocks"]] + [stock_config["benchmark"]["code"]]

        def quotes(_codes):
            return {
                code: {
                    "close": 101,
                    "previous_close": 100,
                    "volume": 1_000_000 if code.startswith("sh68") else 10_000,
                    "amount_yi": 1,
                    "as_of": "20260723093500",
                }
                for code in codes
            }

        bars = [{"day": f"2026-07-{day:02d}", "close": 100, "volume": 10_000_000} for day in range(10, 23)]
        collector = LiveSnapshotCollector(
            PROJECT_ROOT,
            quote_fetcher=quotes,
            kline_fetcher=lambda _code: bars,
            fund_flow_fetcher=lambda _codes, _day: {
                "continuous_net_inflow_days": 1,
                "pool_net_inflow_yi": 1.0,
                "etf_net_inflow_yi": None,
                "quality_state": "usable",
            },
        )
        snapshot = collector.collect(now=datetime(2026, 7, 23, 9, 35, tzinfo=CHINA_TZ))
        pace_by_code = {item["code"]: item["turnover_pace"] for item in snapshot["stocks"]}
        self.assertAlmostEqual(pace_by_code["sh688702"], pace_by_code["sz300502"], places=4)
        self.assertEqual("degraded", snapshot["source_quality"]["state"])


if __name__ == "__main__":
    unittest.main()

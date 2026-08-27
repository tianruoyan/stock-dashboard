from __future__ import annotations

import json
import unittest
from pathlib import Path

from v2_platform.cross_market import V22CrossMarketBuilder


ROOT = Path(__file__).resolve().parents[1]


class V22CrossMarketTests(unittest.TestCase):
    def test_workspace_never_treats_stale_origins_as_current(self) -> None:
        environment = json.loads((ROOT / "data/v2/v22/market-environment.json").read_text(encoding="utf-8"))
        rows = {item["mapping_id"]: item for item in V22CrossMarketBuilder(ROOT).build(environment)}
        for mapping_id in (
            "us_ai_compute_to_a_share",
            "us_memory_to_a_share",
            "hk_semiconductor_to_a_share",
            "kr_memory_to_a_share",
        ):
            row = rows[mapping_id]
            self.assertGreaterEqual(len(row["representative_securities"]), 2)
            self.assertIn(row["origin_source_state"], {"current", "missing_or_stale"})
            if row["origin_source_state"] == "current":
                self.assertIn(row["transmission_state"], {"confirmed", "divergent", "pending"})
            else:
                self.assertEqual(row["transmission_state"], "background_only")
            self.assertEqual(row["supports_g5_upgrade"], row["transmission_state"] == "confirmed")
        self.assertTrue(all(item["single_company_event_theme_upgrade"] is False for item in rows.values()))

    def test_current_origin_requires_a_share_representatives_and_direction(self) -> None:
        builder = V22CrossMarketBuilder.__new__(V22CrossMarketBuilder)
        builder.config = {"version": "test", "default_valid_windows": ["盘中"]}
        builder.origin_rows = [{"market": "US", "as_of": "2026-07-17T09:00:00+08:00", "conclusion": "美股半导体上涨走强"}]
        builder.quotes = {
            "sz000001": {"stock_change_pct": 2.0, "stock_quote_as_of": "2026-07-17T10:00:00+08:00", "stock_quote_source": "测试行情"},
            "sz000002": {"stock_change_pct": 1.5, "stock_quote_as_of": "2026-07-17T10:00:00+08:00", "stock_quote_source": "测试行情"},
        }
        mapping = {
            "mapping_id": "test",
            "origin_market": "US",
            "origin_keywords": ["半导体"],
            "representative_securities": [{"code": "sz000001", "name": "甲"}, {"code": "sz000002", "name": "乙"}],
            "invalidation_conditions": ["公司特有事件"],
        }
        row = builder._mapping(mapping, "2026-07-17")
        self.assertEqual(row["transmission_state"], "confirmed")
        self.assertTrue(row["supports_g5_upgrade"])
        builder.quotes["sz000001"]["stock_change_pct"] = -2.0
        builder.quotes["sz000002"]["stock_change_pct"] = -1.5
        divergent = builder._mapping(mapping, "2026-07-17")
        self.assertEqual(divergent["transmission_state"], "divergent")
        self.assertFalse(divergent["supports_g5_upgrade"])


if __name__ == "__main__":
    unittest.main()

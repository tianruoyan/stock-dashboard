from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_hardware_monitor.engine.intraday_trigger import active_window, evaluate_intraday_trigger


MODULE_ROOT = Path(__file__).resolve().parents[1]
CHINA_TZ = timezone(timedelta(hours=8))


def snapshot(now: datetime) -> dict:
    return {
        "trade_date": now.date().isoformat(),
        "as_of": now.isoformat(timespec="seconds"),
        "sector": {
            "market_rank": 2,
            "relative_outperformance_pct": 1.8,
            "advance_ratio_pct": 75,
        },
        "leaders": {
            "outperform_count": 2,
            "median_turnover_pace": 1.6,
        },
        "stocks": [
            {
                "code": "sz300308",
                "name": "中际旭创",
                "change_pct": 3.2,
                "quote_as_of": now.isoformat(timespec="seconds"),
            }
        ],
    }


class IntradayTriggerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((MODULE_ROOT / "config" / "intraday-trigger.json").read_text(encoding="utf-8"))
        cls.now = datetime(2026, 7, 23, 10, 12, tzinfo=CHINA_TZ)

    def test_candidate_requires_all_intraday_conditions(self) -> None:
        result = evaluate_intraday_trigger(
            snapshot(self.now),
            {"score": 72, "coverage_ratio": 0.8, "state": {"code": "observe"}},
            self.config,
        )
        self.assertTrue(result["active"])
        self.assertEqual("candidate", result["level"])
        self.assertEqual("中际旭创", result["representative_stock"]["name"])

    def test_failed_rank_suppresses_candidate(self) -> None:
        current = snapshot(self.now)
        current["sector"]["market_rank"] = 4
        result = evaluate_intraday_trigger(
            current,
            {"score": 72, "coverage_ratio": 0.8, "state": {"code": "observe"}},
            self.config,
        )
        self.assertFalse(result["active"])
        self.assertIn("代理篮子进入可比行业前三", result["failed_conditions"])

    def test_current_representative_quote_is_required(self) -> None:
        current = snapshot(self.now)
        current["stocks"][0]["quote_as_of"] = "2026-07-22T15:00:00+08:00"
        result = evaluate_intraday_trigger(
            current,
            {"score": 72, "coverage_ratio": 0.8, "state": {"code": "observe"}},
            self.config,
        )
        self.assertFalse(result["active"])
        self.assertIn("至少一只代表股具有当日实时报价", result["failed_conditions"])

    def test_trigger_windows_exclude_lunch_and_open_noise(self) -> None:
        self.assertIsNone(active_window(datetime(2026, 7, 23, 9, 35, tzinfo=CHINA_TZ), self.config))
        self.assertEqual("morning", active_window(self.now, self.config)["id"])
        self.assertIsNone(active_window(datetime(2026, 7, 23, 12, 0, tzinfo=CHINA_TZ), self.config))
        self.assertEqual("afternoon", active_window(datetime(2026, 7, 23, 14, 0, tzinfo=CHINA_TZ), self.config)["id"])


if __name__ == "__main__":
    unittest.main()

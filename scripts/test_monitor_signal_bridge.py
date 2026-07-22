import argparse
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from import_monitor_signals import TZ, convert_record, read_signal_records, should_refresh


def theme_record(timestamp: str, side: str = "up", speed: float = 1.8) -> dict:
    stock_speed = speed if side == "up" else -abs(speed)
    day_change = 10.0 if side == "up" else -10.0
    scored = {
        "metrics": {
            "tick": {"symbol": "688012", "name": "中微公司", "change_pct": day_change},
            "speed_pct": stock_speed,
            "amount_ratio": 6.2,
        },
        "score": 61.2,
    }
    return {
        "schema_version": 1,
        "timestamp": timestamp,
        "kind": "small_deng" if side == "up" else "small_deng_down",
        "key": f"small_deng:半导体设备:{side}",
        "severity": "strong" if side == "up" else "risk",
        "title": "小登提醒",
        "body": "触发规则：3分钟异动\n结论：短周期量价达到观察门槛。",
        "theme": "半导体设备",
        "side": side,
        "details": {
            "side": side,
            "trigger_rules": ["3分钟量价异动"],
            "move_context": "attack",
            "theme": {
                "name": "半导体设备",
                "speed_pct": speed if side == "up" else -abs(speed),
                "amount_ratio": 6.2,
                "amount_vs_prev_day_ratio": 1.3,
                "rising_ratio": 0.8 if side == "up" else 0.2,
                "falling_ratio": 0.2 if side == "up" else 0.8,
                "leaders": [scored],
                "laggards": [scored],
            },
        },
    }


class MonitorSignalBridgeTests(unittest.TestCase):
    def test_converts_opportunity_with_real_short_window_quote(self) -> None:
        alert = convert_record(theme_record("2026-07-22T10:01:02"))
        self.assertIsNotNone(alert)
        self.assertEqual(alert["alert_class"], "opportunity")
        self.assertEqual(alert["confirmation_level"], "candidate")
        self.assertEqual(alert["leaders"][0]["code"], "688012")
        self.assertEqual(alert["leaders"][0]["change_pct"], 1.8)
        self.assertEqual(alert["quote_audit"]["provider"], "本地盘中监控")
        self.assertFalse(alert["quote_audit"]["sanity_checks"]["cross_source_verified"])

    def test_converts_down_signal_as_risk(self) -> None:
        alert = convert_record(theme_record("2026-07-22T10:02:03", side="down", speed=1.3))
        self.assertEqual(alert["alert_class"], "risk")
        self.assertEqual(alert["signal_type"], "风险提示")
        self.assertLess(alert["leaders"][0]["change_pct"], 0)

    def test_ignores_system_and_other_trade_dates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "signals.jsonl"
            rows = [
                {"timestamp": "2026-07-22T10:00:00", "kind": "system"},
                theme_record("2026-07-21T10:00:00"),
                theme_record("2026-07-22T10:01:00"),
            ]
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
            result = read_signal_records(path, datetime(2026, 7, 22, 10, 5, tzinfo=TZ))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["timestamp"], "2026-07-22T10:01:00")

    def test_no_trigger_heartbeat_refreshes_only_after_four_minutes(self) -> None:
        previous = {"timestamp": "2026-07-22T10:00:00+08:00", "source_status": "monitor_live_no_trigger", "alerts": []}
        current = {"timestamp": "2026-07-22T10:03:00+08:00", "source_status": "monitor_live_no_trigger", "alerts": []}
        self.assertFalse(should_refresh(previous, current, datetime(2026, 7, 22, 10, 3, tzinfo=TZ)))
        self.assertTrue(should_refresh(previous, current, datetime(2026, 7, 22, 10, 4, tzinfo=TZ)))


if __name__ == "__main__":
    unittest.main()

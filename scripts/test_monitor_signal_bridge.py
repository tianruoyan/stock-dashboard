import argparse
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from import_monitor_signals import TZ, convert_record, live_payload, market_mode, preserve_quote_verifications, read_signal_records, should_refresh, unavailable_payload


def theme_record(timestamp: str, side: str = "up", speed: float = 1.8) -> dict:
    stock_speed = speed if side == "up" else -abs(speed)
    day_change = 10.0 if side == "up" else -10.0
    scored = {
        "metrics": {
            "tick": {"symbol": "688012", "name": "中微公司", "change_pct": day_change, "timestamp": timestamp},
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
        self.assertEqual(alert["leaders"][0]["quote_time"], "2026-07-22T10:01:02")
        self.assertEqual(alert["quote_audit"]["provider"], "本地盘中监控")
        self.assertFalse(alert["quote_audit"]["sanity_checks"]["cross_source_verified"])

    def test_converts_down_signal_as_risk(self) -> None:
        alert = convert_record(theme_record("2026-07-22T10:02:03", side="down", speed=1.3))
        self.assertEqual(alert["alert_class"], "risk")
        self.assertEqual(alert["signal_type"], "风险提示")
        self.assertLess(alert["leaders"][0]["change_pct"], 0)

    def test_bridge_preserves_completed_futu_verification_for_same_alert(self) -> None:
        previous_alert = convert_record(theme_record("2026-07-22T10:01:02"))
        previous_alert["quote_audit"].update({
            "provider": "本地盘中监控、富途行情（腾讯备用）",
            "secondary_source": "富途行情",
            "secondary_verification": {"state": "passed", "source": "富途行情"},
        })
        previous_alert["quote_audit"]["sanity_checks"]["cross_source_verified"] = True
        regenerated = convert_record(theme_record("2026-07-22T10:01:02"))
        merged = preserve_quote_verifications([regenerated], {"alerts": [previous_alert]})
        verification = merged[0]["quote_audit"]["secondary_verification"]
        self.assertEqual(verification["state"], "passed")
        self.assertEqual(verification["source"], "富途行情")
        self.assertTrue(merged[0]["quote_audit"]["sanity_checks"]["cross_source_verified"])

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

    def test_no_trigger_payload_does_not_claim_monitor_failure(self) -> None:
        payload = live_payload([], datetime(2026, 7, 22, 10, 4, tzinfo=TZ))
        self.assertEqual(payload["source_status"], "monitor_live_no_trigger")
        self.assertIn("监控运行正常", payload["note"])
        self.assertEqual(payload["alerts"], [])

    def test_transient_failure_preserves_same_day_valid_alerts(self) -> None:
        alert = convert_record(theme_record("2026-07-22T10:01:02"))
        previous = {
            "timestamp": "2026-07-22T10:02:00+08:00",
            "source_status": "monitor_live",
            "alerts": [alert],
            "quote_audit": {"provider": "本地盘中监控"},
        }
        payload = unavailable_payload(
            datetime(2026, 7, 22, 10, 5, tzinfo=TZ),
            "行情源最近一次刷新失败。",
            previous,
        )
        self.assertEqual(payload["source_status"], "monitor_waiting_update")
        self.assertEqual(payload["timestamp"], previous["timestamp"])
        self.assertEqual(payload["alerts"], previous["alerts"])
        self.assertIn("保留今天最近一次有效异动", payload["note"])

    def test_failure_without_same_day_valid_alerts_remains_unavailable(self) -> None:
        payload = unavailable_payload(
            datetime(2026, 7, 22, 10, 5, tzinfo=TZ),
            "行情源最近一次刷新失败。",
            {"timestamp": "2026-07-21T14:55:00+08:00", "source_status": "monitor_live", "alerts": [{}]},
        )
        self.assertEqual(payload["source_status"], "invalidated")
        self.assertEqual(payload["alerts"], [])

    def test_verified_trading_day_is_closed_after_monitor_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            calendar = Path(temp) / "calendar.json"
            calendar.write_text(json.dumps({
                "verification_state": "verified",
                "valid_from": "2026-01-01",
                "valid_to": "2026-12-31",
                "weekend_days": [5, 6],
                "holidays": [],
            }), encoding="utf-8")
            self.assertEqual(market_mode(calendar, datetime(2026, 7, 22, 15, 5, tzinfo=TZ)), "closed")
            self.assertEqual(market_mode(calendar, datetime(2026, 7, 22, 14, 59, tzinfo=TZ)), "active")


if __name__ == "__main__":
    unittest.main()

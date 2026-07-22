from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from intraday_recovery import TZ, assess_freshness, is_trading_day, recover, retry_delay_seconds
from update_intraday_market import merge_index_rows, parse_quote_time


def payload(quote_time: str) -> dict:
    return {"indices": [{"code": "sh000001", "quote_time": quote_time}]}


def write_calendar(root: Path) -> None:
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "cn-market-calendar.json").write_text(
        json.dumps({
            "verification_state": "verified",
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
            "weekend_days": [5, 6],
            "holidays": ["2026-10-01"],
            "extra_open_days": [],
        }),
        encoding="utf-8",
    )


class IntradayRecoveryTests(unittest.TestCase):
    def test_live_quote_within_twenty_minutes_is_fresh(self) -> None:
        decision = assess_freshness(payload("20260722100000"), datetime(2026, 7, 22, 10, 19, tzinfo=TZ))
        self.assertTrue(decision.active)
        self.assertTrue(decision.fresh)

    def test_previous_day_quote_is_stale(self) -> None:
        decision = assess_freshness(payload("20260721150000"), datetime(2026, 7, 22, 10, 0, tzinfo=TZ))
        self.assertFalse(decision.fresh)
        self.assertIn("当日", decision.reason)

    def test_lunch_accepts_verified_morning_close(self) -> None:
        decision = assess_freshness(payload("20260722113000"), datetime(2026, 7, 22, 12, 20, tzinfo=TZ))
        self.assertTrue(decision.fresh)

    def test_close_recovery_requires_close_quote(self) -> None:
        decision = assess_freshness(payload("20260722143000"), datetime(2026, 7, 22, 15, 20, tzinfo=TZ))
        self.assertFalse(decision.fresh)
        decision = assess_freshness(payload("20260722150000"), datetime(2026, 7, 22, 15, 20, tzinfo=TZ))
        self.assertTrue(decision.fresh)

    def test_retry_backoff_is_bounded(self) -> None:
        self.assertEqual([retry_delay_seconds(i) for i in range(1, 7)], [60, 120, 300, 600, 600, 600])

    def test_merge_replaces_stale_change_pct(self) -> None:
        existing = [{"code": "sh000001", "change_pct": 9.9}]
        fresh = [{"code": "sh000001", "pct": 0.5, "change_pct": 0.5}]
        self.assertEqual(merge_index_rows(existing, fresh)[0]["change_pct"], 0.5)

    def test_quote_time_parser(self) -> None:
        self.assertEqual(parse_quote_time("20260722103015").strftime("%F %T"), "2026-07-22 10:30:15")

    def test_verified_calendar_stops_holiday_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_calendar(root)
            self.assertFalse(is_trading_day(root, datetime(2026, 10, 1, 10, 0, tzinfo=TZ)))
            self.assertTrue(is_trading_day(root, datetime(2026, 7, 22, 10, 0, tzinfo=TZ)))

    def test_offline_then_network_recovery_updates_and_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "scripts").mkdir()
            write_calendar(root)
            intraday = root / "data" / "intraday.json"
            intraday.write_text(json.dumps(payload("20260721150000")), encoding="utf-8")
            for name in ("update_intraday_market.py", "publish_dashboard.sh"):
                script = root / "scripts" / name
                script.write_text("", encoding="utf-8")
                script.chmod(0o755)
            now = datetime(2026, 7, 22, 10, 0, tzinfo=TZ)

            class Result:
                returncode = 1
                stdout = "网络不可用"
                stderr = ""

            with patch("intraday_recovery.run_command", return_value=Result()):
                failed = recover(root, now)
            self.assertEqual(failed["state"], "网络或行情源待恢复")
            self.assertEqual(failed["failure_count"], 1)

            def recovered_run(command, cwd):
                result = Result()
                result.returncode = 0
                result.stdout = "ok"
                if command[0].endswith("update_intraday_market.py"):
                    intraday.write_text(json.dumps(payload("20260722100100")), encoding="utf-8")
                return result

            with patch("intraday_recovery.run_command", side_effect=recovered_run) as runner:
                recovered = recover(root, datetime(2026, 7, 22, 10, 2, tzinfo=TZ))
            self.assertEqual(recovered["state"], "已自动补充最新行情")
            self.assertEqual(runner.call_count, 2)


if __name__ == "__main__":
    unittest.main()

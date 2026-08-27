from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from v2_platform.environment_evidence import canonical_hash
from v2_platform.v22_outcome_collector import V22OutcomePriceCollector


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def prepare(root: Path) -> None:
    write(root / "config/v2-market-calendar.json", {
        "calendars": [{"market": "CN", "version": "test", "valid_from": "2026-01-01", "valid_to": "2026-12-31", "holidays": [], "extra_open_days": [], "verification_state": "verified"}]
    })
    snapshot = {
        "snapshot_id": "trigger1", "case_id": "case1", "state_hash": "state1", "kind": "opportunity",
        "trade_date": "2026-07-17", "state_observed_at": "2026-07-17T14:50:00+08:00",
        "case_content_hash": "casehash",
        "representative_quotes": [{
            "code": "sh600000", "name": "测试股份", "market": "CN", "trigger_price": 10.0,
            "quote_time": "2026-07-17T14:49:30+08:00", "source_id": "quote", "source_label": "真实行情测试源", "collected_at": "2026-07-17T14:50:00+08:00",
        }],
    }
    snapshot["immutable_hash"] = canonical_hash({k: v for k, v in snapshot.items() if k != "immutable_hash"})
    path = root / "data/v2/v22/trigger-quote-snapshots/2026-07-17/trigger1.json"
    write(path, snapshot)
    write(root / "data/v2/v22/trigger-quote-index.json", {"snapshots": [{"relative_path": str(path.relative_to(root)), "immutable_hash": snapshot["immutable_hash"]}]})


class V22OutcomeCollectorTests(unittest.TestCase):
    def test_public_history_fetch_retries_transient_network_error(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b"[]"

        with patch(
            "v2_platform.v22_outcome_collector.urlopen",
            side_effect=[URLError("temporary ssl failure"), Response()],
        ) as mocked, patch("v2_platform.v22_outcome_collector.time_module.sleep") as sleep:
            payload = V22OutcomePriceCollector._fetch("https://example.test/history")
        self.assertEqual(payload, b"[]")
        self.assertEqual(mocked.call_count, 2)
        sleep.assert_called_once()

    def test_only_due_windows_are_filled_and_build_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare(root)
            bars = json.dumps([
                {"day": "2026-07-17", "close": "10.1", "high": "10.2", "low": "9.9"},
                {"day": "2026-07-20", "close": "10.5", "high": "10.7", "low": "10.0"},
                {"day": "2026-07-22", "close": "11.0", "high": "11.2", "low": "10.8"},
            ]).encode()
            collector = V22OutcomePriceCollector(root, fetcher=lambda _: bars, as_of=datetime.fromisoformat("2026-07-20T16:00:00+08:00"))
            first = collector.collect()
            before = (root / "data/v2/v22/outcome-prices.json").read_bytes()
            second = collector.collect()
            after = (root / "data/v2/v22/outcome-prices.json").read_bytes()
            observation = json.loads(after)["observations"][0]
            self.assertEqual(first["completed_window_count"], 2)
            self.assertEqual(second["state"], "current")
            self.assertEqual(before, after)
            self.assertEqual(set(observation["windows"]), {"收盘", "T+1"})
            self.assertNotIn("T+3", observation["windows"])

    def test_missing_or_suspended_price_is_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare(root)
            bars = json.dumps([{"day": "2026-07-17", "close": "10.1", "high": "10.2", "low": "9.9"}]).encode()
            V22OutcomePriceCollector(root, fetcher=lambda _: bars, as_of=datetime.fromisoformat("2026-07-20T16:00:00+08:00")).collect()
            observation = json.loads((root / "data/v2/v22/outcome-prices.json").read_text())["observations"][0]
            self.assertNotIn("T+1", observation["windows"])
            self.assertEqual(observation["missing_windows"][0]["window"], "T+1")
            self.assertIn("未按零涨跌处理", observation["missing_windows"][0]["status"])

    def test_verified_result_is_not_overwritten_by_later_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare(root)
            first_bars = json.dumps([{"day": "2026-07-17", "close": "10.1"}, {"day": "2026-07-20", "close": "10.5"}]).encode()
            second_bars = json.dumps([{"day": "2026-07-17", "close": "10.2"}, {"day": "2026-07-20", "close": "10.8"}]).encode()
            as_of = datetime.fromisoformat("2026-07-20T16:00:00+08:00")
            V22OutcomePriceCollector(root, fetcher=lambda _: first_bars, as_of=as_of).collect()
            report = V22OutcomePriceCollector(root, fetcher=lambda _: second_bars, as_of=as_of).collect()
            observation = json.loads((root / "data/v2/v22/outcome-prices.json").read_text())["observations"][0]
            self.assertEqual(observation["windows"]["T+1"]["price"], 10.5)
            self.assertGreater(report["conflict_count"], 0)

    def test_holiday_is_skipped_by_verified_exchange_calendar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare(root)
            calendar_path = root / "config/v2-market-calendar.json"
            calendar = json.loads(calendar_path.read_text())
            calendar["calendars"][0]["holidays"] = ["2026-07-20"]
            write(calendar_path, calendar)
            bars = json.dumps([{"day": "2026-07-17", "close": "10.1"}, {"day": "2026-07-21", "close": "10.6"}]).encode()
            V22OutcomePriceCollector(root, fetcher=lambda _: bars, as_of=datetime.fromisoformat("2026-07-21T16:00:00+08:00")).collect()
            observation = json.loads((root / "data/v2/v22/outcome-prices.json").read_text())["observations"][0]
            self.assertEqual(observation["windows"]["T+1"]["quote_time"], "2026-07-21T15:00:00+08:00")

    def test_same_day_close_is_not_filled_before_market_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare(root)
            bars = json.dumps([{"day": "2026-07-17", "close": "10.1"}]).encode()
            report = V22OutcomePriceCollector(root, fetcher=lambda _: bars, as_of=datetime.fromisoformat("2026-07-17T14:00:00+08:00")).collect()
            observation = json.loads((root / "data/v2/v22/outcome-prices.json").read_text())["observations"][0]
            self.assertEqual(report["completed_window_count"], 0)
            self.assertEqual(observation["windows"], {})


if __name__ == "__main__":
    unittest.main()

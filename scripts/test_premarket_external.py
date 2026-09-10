from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from premarket_external import TZ, apply_facts, chart_row, refresh, tencent_row
from stage_fallback import premarket_skeleton, read_json, write_json_atomic

NOW = datetime(2026, 9, 10, 10, 30, tzinfo=TZ)


def raw(code="usIXIC", stamp="2026-09-09 16:00:00"):
    fields = [""] * 38
    for i, value in {3: "102", 4: "100", 30: stamp, 32: "2.0"}.items():
        fields[i] = value
    return {"query_code": code, "fields": fields}


def chart():
    stamp = lambda hour, minute: int(NOW.replace(hour=hour, minute=minute).timestamp())
    return {"meta": {"symbol": "^N225", "regularMarketTime": stamp(10, 20), "previousClose": 100},
            "timestamp": [stamp(9, 24), stamp(9, 25), stamp(10, 20)],
            "indicators": {"quote": [{"close": [102, 103, 104]}]}}


class PremarketExternalTests(unittest.TestCase):
    def test_us_timezone_and_real_availability(self):
        row = tencent_row(raw(), NOW)
        self.assertEqual(row["quote_time"], "2026-09-10T04:00:00+08:00")
        self.assertEqual(row["available_at"], NOW.isoformat())
        self.assertEqual(row["change_pct"], 2)

    def test_us_previous_session_rejected(self):
        with self.assertRaises(ValueError):
            tencent_row(raw(stamp="2026-09-08 16:00:00"), NOW)

    def test_future_and_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            tencent_row(raw("hkHSI", "2026/09/10 11:00:00"), NOW)
        item = raw()
        item["fields"][32] = "nan"
        with self.assertRaises(ValueError):
            tencent_row(item, NOW)

    def test_hk_previous_day_and_auction_last_trade_rejected(self):
        for stamp in ["2026/09/09 16:00:00", "2026/09/10 09:20:00", "2026/09/10 09:40:00"]:
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                tencent_row(raw("hkHSI", stamp), NOW)

    def test_delayed_hk_quote_is_explicit(self):
        row = tencent_row(raw("hkHSI", "2026/09/10 10:15:00"), NOW)
        self.assertIn("延时", row["note"])

    def test_recovered_asia_uses_completed_preopen_bar(self):
        row = chart_row("^N225", chart(), NOW)
        self.assertEqual(row["quote_time"], "2026-09-10T09:25:00+08:00")
        self.assertEqual(row["change_pct"], 2)
        self.assertTrue(row["historical_backfill"])
        self.assertIn("10:30补采", row["note"])

    def test_asia_rejects_wrong_day_symbol_and_missing_previous_close(self):
        for key, value in [("regularMarketTime", int((NOW-timedelta(days=1)).timestamp())), ("symbol", "wrong"), ("previousClose", None)]:
            item = chart()
            item["meta"][key] = value
            with self.subTest(key=key), self.assertRaises((ValueError, TypeError)):
                chart_row("^N225", item, NOW)

    def test_asia_live_capture_does_not_use_later_bar(self):
        now = NOW.replace(hour=9, minute=25)
        item = chart()
        item["meta"]["regularMarketTime"] = int(now.timestamp())
        row = chart_row("^N225", item, now)
        self.assertEqual(row["change_pct"], 2)
        self.assertFalse(row["historical_backfill"])

    def test_merge_preserves_analysis_timestamp_and_does_not_create_auction(self):
        payload = premarket_skeleton(NOW.replace(hour=8, minute=30), "08:30")
        before = copy.deepcopy(payload)
        rows = {"usIXIC": tencent_row(raw(), NOW), "hkHSI": tencent_row(raw("hkHSI", "2026/09/10 10:15:00"), NOW)}
        result = apply_facts(payload, rows, NOW)
        self.assertEqual(payload, before)
        self.assertEqual(result["analysis_time"], before["analysis_time"])
        self.assertEqual(result["timestamp"], before["timestamp"])
        self.assertEqual(result["hk_auction"]["indices"], [])
        self.assertEqual(len(result["hk_followup"]["indices"]), 1)
        self.assertEqual(result["us_overnight"]["indices"][0]["code"], "usIXIC")

    def test_failure_retains_verified_rows_and_is_idempotent(self):
        payload = premarket_skeleton(NOW, "09:00")
        rows = {"usIXIC": tencent_row(raw(), NOW)}
        first = apply_facts(payload, rows, NOW)
        second = apply_facts(first, {}, NOW + timedelta(minutes=15))
        self.assertEqual(first, second)
        rows["usIXIC"]["collected_at"] = (NOW+timedelta(minutes=15)).isoformat()
        self.assertEqual(first, apply_facts(first, rows, NOW+timedelta(minutes=15)))

    def test_manual_analysis_not_overwritten(self):
        payload = {"generation_mode": "codex", "summary": "人工结论", "strategy": [{"action": "观察"}]}
        result = apply_facts(payload, {"usIXIC": tencent_row(raw(), NOW)}, NOW)
        self.assertEqual(result["summary"], "人工结论")
        self.assertEqual(result["strategy"], payload["strategy"])

    def test_current_file_does_not_rescue_previous_day_quotes(self):
        payload = premarket_skeleton(NOW, "09:00")
        old = chart_row("^N225", chart(), NOW)
        old["quote_time"] = "2026-09-09T09:25:00+08:00"
        payload["us_overnight"]["japan_korea"]["indices"] = [old]
        result = apply_facts(payload, {}, NOW)
        self.assertEqual(result["us_overnight"]["japan_korea"]["indices"], [])
        self.assertIn("日经225", result["external_data_notice"])

    def test_source_failure_visible_even_with_previous_valid_quote(self):
        payload = premarket_skeleton(NOW, "09:00")
        first = apply_facts(payload, {"usIXIC": tencent_row(raw(), NOW)}, NOW, {})
        failed = apply_facts(first, {}, NOW + timedelta(minutes=15), {"usIXIC": "timeout"})
        self.assertIn("纳斯达克", failed["external_refresh_notice"])
        self.assertEqual(first["us_overnight"]["indices"], failed["us_overnight"]["indices"])

    def test_retry_throttle_and_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_atomic(root / "data/premarket.json", premarket_skeleton(NOW, "09:00"))
            with patch("premarket_external.collect", return_value=({}, {"^N225": "network"})) as collector:
                self.assertTrue(refresh(root, NOW))
                self.assertFalse(refresh(root, NOW+timedelta(seconds=60)))
                self.assertEqual(collector.call_count, 1)
                refresh(root, NOW+timedelta(minutes=15))
                self.assertEqual(collector.call_count, 2)
            status = read_json(root / "logs/premarket-external-status.json")
            self.assertIn("^N225", status["errors"])
            self.assertEqual(len(list((root / "logs/premarket-external-snapshots").rglob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()

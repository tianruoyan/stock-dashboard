"""Plan target dates must not stand in for actual market/analysis timestamps."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import audit_dashboard_data as audit
import build_data_trust as trust
from data_validity import TZ, premarket_timing

SUNDAY = datetime(2026, 10, 11, 21, 0, tzinfo=TZ)
MONDAY = datetime(2026, 10, 12, 8, 45, tzinfo=TZ)
SPEC = next(item for item in trust.CORE_FILES if item["file"] == "data/premarket.json")


def sunday_plan():
    return {
        "trade_date": "2026-10-12",
        "date": "2026-10-12",
        "timestamp": "2026-10-11T20:05:42+08:00",
        "analysis_time": "2026-10-11T20:05:42+08:00",
        "status": "waiting_monday_preopen_validation",
        "data_status": "hk_auction_and_japan_korea_not_started",
        "summary": "周一盘前预案，等待竞价确认",
        "us_overnight": {"indices": [{"quote_time": "2026-10-09T16:00:00-04:00", "change_pct": 0.63}]},
        "hk_auction": {"status": "not_started", "indices": []},
        "overnight_news": [],
    }


def monday_premarket():
    data = sunday_plan()
    data.update(timestamp="2026-10-12T08:30:00+08:00", analysis_time="2026-10-12T08:30:00+08:00",
                status="premarket_analysis", data_status="analysis_available", market_context={"summary": "盘前资料已更新"})
    return data


class PremarketPlanDateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()

    def row(self, data, now=SUNDAY, current_date="2026-10-09"):
        (self.root / "data/premarket.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with patch.object(trust, "ROOT", self.root):
            return trust.trust_row(SPEC, data, current_date, [], [], trust.trading_phase(now), now)

    def timestamp_issues(self, data, now=SUNDAY, current_date="2026-10-09"):
        issues = []
        audit.validate_file_timestamp("premarket.json", data, current_date, issues, now)
        audit.scan_timestamp_fields("premarket.json", data, issues, now)
        return issues

    def contract_issues(self, data, now=SUNDAY):
        issues = []
        audit.validate_core_file_contracts({"premarket.json": data}, issues, now)
        return issues

    def test_sunday_plan_is_upcoming_unconfirmed_and_preserves_real_times(self):
        data = sunday_plan()
        original = copy.deepcopy(data)
        row = self.row(data)
        self.assertEqual(row["signal_date"], "2026-10-12")
        self.assertEqual(row["target_trade_date"], "2026-10-12")
        self.assertEqual(row["session_relevance"], "upcoming")
        self.assertEqual(row["freshness_status"], "pending")
        self.assertFalse(row["usable"])
        self.assertIn("等待确认", row["use_action"])
        self.assertEqual(row["timestamp"], original["timestamp"])
        self.assertEqual(row["age_minutes"], 54)
        self.assertEqual(data, original)
        self.assertFalse(self.timestamp_issues(data))

    def test_plan_creation_and_target_dates_do_not_advance_actual_evidence_date(self):
        files = {"premarket.json": sunday_plan(), "postmarket.json": {"timestamp": "2026-10-09T16:00:00+08:00"}}
        for now in (SUNDAY, MONDAY, MONDAY.replace(hour=13)):
            with self.subTest(now=now):
                self.assertEqual(audit.latest_signal_date(files, now), "2026-10-09")
                self.assertEqual(trust.latest_signal_date({"data/" + k: v for k, v in files.items()}, now), "2026-10-09")

    def test_absent_context_before_auction_is_waiting_not_contract_alarm(self):
        issues = self.contract_issues(sunday_plan())
        self.assertEqual([item["code"] for item in issues], ["premarket_auction_pending"])
        self.assertEqual(issues[0]["severity"], "info")
        self.assertIn("等待", issues[0]["message"])

    def test_same_day_new_premarket_keeps_existing_current_analysis_semantics(self):
        data = monday_premarket()
        row = self.row(data, MONDAY, "2026-10-12")
        self.assertEqual(row["session_relevance"], "current")
        self.assertEqual(row["freshness_status"], "fresh")
        self.assertEqual(row["age_minutes"], 15)
        self.assertTrue(row["usable"])
        self.assertEqual(row["timestamp"], "2026-10-12T08:30:00+08:00")
        self.assertEqual(data["us_overnight"]["indices"][0]["quote_time"], "2026-10-09T16:00:00-04:00")
        self.assertEqual(audit.latest_signal_date({"premarket.json": data}, MONDAY), "2026-10-12")
        self.assertFalse(self.contract_issues(data, MONDAY))

    def test_clock_reaching_monday_does_not_confirm_sunday_plan(self):
        row = self.row(sunday_plan(), MONDAY)
        self.assertEqual(row["plan_state"], "awaiting_confirmation")
        self.assertEqual(row["session_relevance"], "upcoming")
        self.assertEqual(row["freshness_status"], "pending")
        self.assertGreater(row["age_minutes"], 700)
        self.assertFalse(row["usable"])
        self.assertFalse(self.timestamp_issues(sunday_plan(), MONDAY))

    def test_explicit_waiting_status_never_becomes_current_confirmed_analysis(self):
        data = monday_premarket()
        data["status"] = "waiting_preopen_validation"
        row = self.row(data, MONDAY, "2026-10-12")
        self.assertEqual(row["plan_state"], "awaiting_confirmation")
        self.assertFalse(row["usable"])

    def test_context_is_required_once_auction_results_are_due(self):
        data = sunday_plan()
        before = MONDAY.replace(hour=9, minute=24, second=59)
        due = MONDAY.replace(hour=9, minute=25)
        self.assertEqual(self.contract_issues(data, before)[0]["code"], "premarket_auction_pending")
        issues = self.contract_issues(data, due)
        self.assertTrue(any(item["code"] == "schema_contract_missing" and item["path"] == "market_context" for item in issues))
        self.assertFalse(any(item["code"] == "premarket_auction_pending" for item in issues))
        self.assertFalse(self.row(data, due)["usable"])

    def test_expired_plan_is_historical_in_later_phase_and_next_day(self):
        for now in (MONDAY.replace(hour=11, minute=30), MONDAY.replace(hour=15), MONDAY.replace(day=13)):
            row = self.row(sunday_plan(), now, now.date().isoformat())
            self.assertEqual(row["session_relevance"], "historical")
            self.assertEqual(row["freshness_status"], "phase_expired")
            self.assertFalse(row["usable"])
            self.assertEqual(row["use_action"], "仅作历史背景")
        self.assertEqual(self.row(monday_premarket(), MONDAY.replace(hour=13), "2026-10-12")["session_relevance"], "historical")

    def test_future_root_timestamp_stays_invalid_even_with_future_target_date(self):
        data = sunday_plan()
        data["timestamp"] = "2026-10-12T08:30:00+08:00"
        row = self.row(data)
        self.assertEqual(row["freshness_status"], "future")
        self.assertFalse(row["usable"])
        self.assertTrue(any(item["code"] == "future_timestamp" for item in self.timestamp_issues(data)))
        self.assertTrue(any(item["code"] == "schema_contract_missing" for item in self.contract_issues(data)))

    def test_future_nested_quote_timestamp_still_warns_for_pending_plan(self):
        data = sunday_plan()
        data["hk_auction"]["indices"] = [{"quote_time": "2026-10-12T09:25:00+08:00", "change_pct": 1.0}]
        issues = self.timestamp_issues(data)
        self.assertTrue(any(item["code"] == "future_timestamp" and item["path"] == "hk_auction.indices[0].quote_time" for item in issues))
        self.assertFalse(self.row(data)["usable"])

    def test_invalid_dates_cannot_hide_behind_timestamp_or_date_alias(self):
        for target in ("", None, 20261012, "2026-02-30", "tomorrow", "2026-10-12T00:00:00+08:00", "2026-10-13"):
            data = sunday_plan()
            data["trade_date"] = target
            with self.subTest(target=target):
                row = self.row(data)
                self.assertEqual(row["plan_state"], "invalid_date")
                self.assertEqual(row["session_relevance"], "blocked")
                self.assertFalse(row["usable"])
                self.assertTrue(any(item["code"] == "invalid_trade_date" for item in self.timestamp_issues(data)))
                self.assertTrue(any(item["code"] == "schema_contract_missing" for item in self.contract_issues(data)))

    def test_missing_or_invalid_analysis_timestamp_cannot_confirm_plan(self):
        for timestamp in (None, "not a time", "2026-02-30T20:00:00+08:00"):
            data = sunday_plan()
            data["timestamp"] = timestamp
            with self.subTest(timestamp=timestamp):
                row = self.row(data)
                self.assertEqual(row["plan_state"], "invalid_timestamp")
                self.assertFalse(row["usable"])
                self.assertTrue(any(item["code"] in {"missing_timestamp", "invalid_timestamp"} for item in self.timestamp_issues(data)))
                self.assertTrue(any(item["code"] == "schema_contract_missing" for item in self.contract_issues(data)))

    def test_missing_other_fields_and_wrong_context_type_are_not_suppressed(self):
        data = sunday_plan()
        del data["summary"]
        data["market_context"] = "waiting"
        issues = self.contract_issues(data)
        self.assertTrue(any(item["path"] == "summary" and item["code"] == "schema_contract_missing" for item in issues))
        self.assertTrue(any(item["path"] == "market_context" and item["code"] == "schema_contract_type" for item in issues))

    def test_legacy_no_target_date_keeps_timestamp_based_behavior(self):
        data = monday_premarket()
        del data["trade_date"]
        del data["date"]
        row = self.row(data, MONDAY, "2026-10-12")
        self.assertEqual(row["signal_date"], "2026-10-12")
        self.assertEqual(row["plan_state"], "")
        self.assertEqual(row["freshness_status"], "fresh")
        self.assertTrue(row["usable"])
        data["timestamp"] = "2026-10-09T09:00:00+08:00"
        self.assertEqual(self.row(data, MONDAY, "2026-10-12")["status"], "stale")

    def test_date_alias_is_supported_only_when_trade_date_is_absent(self):
        data = sunday_plan()
        del data["trade_date"]
        self.assertEqual(premarket_timing(data, SUNDAY)["state"], "upcoming")
        self.assertEqual(self.row(data)["signal_date"], "2026-10-12")

    def test_invalidated_plan_keeps_blocking_precedence(self):
        data = sunday_plan()
        data["source_status"] = "invalidated"
        row = self.row(data)
        self.assertEqual(row["status"], "invalidated")
        self.assertEqual(row["session_relevance"], "blocked")
        self.assertEqual(row["freshness_status"], "blocked")
        self.assertEqual(row["use_action"], "等待重产")
        self.assertFalse(row["usable"])

    def test_legacy_stale_timestamp_severity_is_preserved(self):
        for name, severity in (("evening-sentiment.json", "info"), ("requirements.json", "info"),
                               ("intraday.json", "warning"), ("premarket.json", "warning")):
            issues = []
            audit.validate_file_timestamp(name, {"timestamp": "2026-10-09T16:00:00+08:00"},
                                          "2026-10-12", issues, MONDAY)
            with self.subTest(file=name):
                self.assertEqual(len(issues), 1)
                self.assertEqual(issues[0]["code"], "stale_timestamp")
                self.assertEqual(issues[0]["severity"], severity)

    def test_audit_contract_accepts_pending_freshness_state(self):
        row = self.row(sunday_plan())
        issues = []
        audit.validate_data_trust({"current_signal_date": "2026-10-09", "files": [row]}, issues, "2026-10-09")
        self.assertFalse(issues)


if __name__ == "__main__":
    unittest.main()

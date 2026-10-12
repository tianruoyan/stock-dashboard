"""Deterministic regressions; no collector, OpenD, or repository data writes."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from alert_validity import TZ, alert_cross_verified, alert_time_state
from audit_dashboard_data import (
    alert_requires_trade_gate, has_polluted_quote_source, validate_alert,
    validate_core_file_contracts, validate_source_health,
)
from build_alert_recovery_readiness import build_report, trusted_source_rows
from smoke_dashboard_static import alert_requires_trade_gate as smoke_trade_gate
from verify_alert_quotes import VERIFIER_VERSION, prepare_source_health_update

NOW = datetime(2026, 10, 12, 10, 5, tzinfo=TZ)


def audit(verified=False):
    return {"provider": "腾讯行情", "quote_time": (NOW - timedelta(minutes=1)).isoformat(),
            "pct_field": "3分钟涨跌幅", "board_3m_change_pct": 2,
            "sanity_checks": {"sample_count": 1, "max_abs_leader_change_pct": 2,
                              "cross_source_verified": verified, "price_move_valid": True,
                              "volume_valid": True, "direction_ratio_valid": True}}


def row(**updates):
    result = {"id": "monitor-20261012-100400-fixture", "time": (NOW - timedelta(minutes=1)).isoformat(),
              "valid_until": (NOW + timedelta(minutes=4)).isoformat(),
              "sector": "测试题材", "type": "风格观察", "signal_type": "风格观察", "alert_class": "style",
              "confirmation_level": "candidate", "quote_audit": audit(),
              "leaders": [{"name": "测试公司", "change_pct": 2}], "source": "tencent_http"}
    result.update(updates)
    return result


def payload(rows=None, **updates):
    result = {"timestamp": NOW.isoformat(), "alerts": rows if rows is not None else [row()], "quote_audit": audit()}
    result.update(updates)
    return result


class AlertTimingContracts(unittest.TestCase):
    def state(self, item, data=None, now=NOW):
        return alert_time_state(item, data or payload([item]), now)

    def test_fresh_deadline_is_current(self):
        self.assertEqual(self.state(row()), "current")

    def test_deadline_boundary_is_expired(self):
        item = row(valid_until=NOW.isoformat())
        self.assertEqual(self.state(item), "expired")

    def test_missing_invalid_naive_or_date_only_deadline_is_unknown(self):
        for value in (None, "", "bad", "2026-10-12", "2026-10-12T10:10:00", {}, []):
            with self.subTest(value=value):
                self.assertEqual(self.state(row(valid_until=value)), "unknown")

    def test_extended_deadline_does_not_extend_five_minute_window(self):
        item = row(time=(NOW - timedelta(minutes=5, seconds=1)).isoformat())
        self.assertEqual(self.state(item), "expired")
        item["time"] = (NOW - timedelta(minutes=5)).isoformat()
        self.assertEqual(self.state(item), "current")

    def test_sustained_observation_keeps_existing_fifteen_minute_window(self):
        item = row(time=(NOW - timedelta(minutes=15)).isoformat(), signal_type="持续走强观察")
        self.assertEqual(self.state(item), "current")
        item["time"] = (NOW - timedelta(minutes=15, seconds=1)).isoformat()
        self.assertEqual(self.state(item), "expired")

    def test_future_time_tolerance_is_one_minute(self):
        self.assertEqual(self.state(row(time=(NOW + timedelta(seconds=60)).isoformat())), "current")
        self.assertEqual(self.state(row(time=(NOW + timedelta(seconds=61)).isoformat())), "unknown")

    def test_deadline_before_event_is_unknown(self):
        self.assertEqual(self.state(row(valid_until=(NOW - timedelta(minutes=2)).isoformat())), "unknown")

    def test_refreshing_batch_does_not_renew_old_event(self):
        item = row(time="2026-10-09T10:04:00+08:00", valid_until="2026-10-09T10:09:00+08:00")
        self.assertEqual(self.state(item), "expired")

    def test_legacy_event_id_prevents_new_batch_redating(self):
        item = row(id="20261009-fixture", time="10:04:00", valid_until="2026-10-09T10:09:00+08:00")
        self.assertEqual(self.state(item), "expired")

    def test_session_closed_and_invalidated_never_current(self):
        item = row()
        self.assertEqual(self.state(item, payload([item], source_status="monitor_session_closed")), "closed")
        self.assertEqual(self.state(item, payload([item], source_status="invalidated")), "invalidated")
        self.assertEqual(self.state(row(confirmation_level="invalidated")), "invalidated")

    def test_unknown_event_cannot_use_batch_generation_time(self):
        self.assertEqual(self.state(row(time=None)), "unknown")
        self.assertEqual(self.state(row(time="25:00:00")), "unknown")
        self.assertEqual(self.state(row(time="2026-10-12T10:04:00")), "unknown")
        self.assertEqual(self.state(row(source_status="monitor_session_closed")), "closed")


class ReadinessContracts(unittest.TestCase):
    def test_closed_twelve_expired_rows_keep_history_and_zero_active(self):
        rows = [row(id=str(i), time="2026-10-12T09:33:00+08:00", valid_until="2026-10-12T09:38:00+08:00") for i in range(12)]
        data = payload(rows, source_status="monitor_session_closed")
        original = copy.deepcopy(data)
        report = build_report({}, data, {}, NOW)
        self.assertEqual(report["status"], "session_closed")
        state = report["alert_state"]
        self.assertEqual((state["total_count"], state["active_count"], state["expired_count"]), (12, 0, 12))
        self.assertEqual(data, original)

    def test_current_counts_and_cross_verification_are_separate(self):
        rows = [row(quote_audit=audit(True)), row(), row(valid_until=NOW.isoformat()), row(valid_until=None)]
        report = build_report({}, payload(rows), {}, NOW)
        state = report["alert_state"]
        self.assertEqual((state["current_count"], state["expired_count"], state["time_unverified_count"]), (2, 1, 1))
        self.assertEqual((state["verified_count"], state["unverified_count"]), (1, 1))
        self.assertEqual(report["status"], "candidate_visible")
        self.assertEqual(state["total_count"], sum(state[key] for key in ("current_count", "expired_count", "closed_count", "invalidated_count", "time_unverified_count")))

    def test_expired_confirmed_cannot_certify_current_candidate(self):
        rows = [row(confirmation_level="confirmed", quote_audit=audit(True), valid_until=NOW.isoformat()), row()]
        report = build_report({}, payload(rows, quote_audit=audit(True)), {}, NOW)
        self.assertEqual(report["status"], "candidate_visible")
        self.assertEqual(report["alert_state"]["verified_count"], 0)

    def test_current_confirmed_cannot_inherit_verified_batch_over_own_false(self):
        report = build_report({}, payload([row(confirmation_level="confirmed")], quote_audit=audit(True)), {}, NOW)
        self.assertEqual(report["status"], "active_needs_review")

    def test_confirmed_requires_passed_secondary_when_present(self):
        for state in ("mismatch", "pending", "insufficient_precision", "failed"):
            value = audit(True)
            value["secondary_verification"] = {"state": state}
            with self.subTest(state=state):
                self.assertFalse(alert_cross_verified(value))
                self.assertEqual(build_report({}, payload([row(confirmation_level="confirmed", quote_audit=value)]), {}, NOW)["status"], "active_needs_review")

    def test_current_confirmed_does_not_inherit_old_batch_unverified(self):
        rows = [row(confirmation_level="confirmed", quote_audit=audit(True)), row(valid_until=NOW.isoformat())]
        report = build_report({}, payload(rows), {}, NOW)
        self.assertEqual(report["status"], "active_verified")

    def test_missing_deadline_or_expired_batch_is_never_candidate_visible(self):
        for value, expected in ((None, "waiting_review"), (NOW.isoformat(), "historical_only")):
            self.assertEqual(build_report({}, payload([row(valid_until=value)]), {}, NOW)["status"], expected)

    def test_old_ok_source_does_not_prove_recovery(self):
        health = {"timestamp": NOW.isoformat(), "sources": {"tencent_http": {"status": "ok", "last_check": "2026-07-27T10:00:00+08:00"}}}
        report = build_report(health, payload([], source_status="invalidated"), {}, NOW)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["trusted_sources"], [])
        self.assertEqual(report["source_counts"]["historical"], 1)
        self.assertEqual(report["historical_sources"][0]["status"], "ok")

    def test_current_source_can_prove_recovery_but_unknown_cannot(self):
        sources = {"tencent_http": {"status": "ok", "last_check": NOW.isoformat()}, "tencent_minute": {"status": "ok"}}
        self.assertEqual(len(trusted_source_rows(sources, NOW)), 1)
        report = build_report({"sources": sources}, payload([], source_status="invalidated"), {}, NOW)
        self.assertEqual(report["status"], "ready_to_recover")
        self.assertEqual(report["source_counts"], {"current": 1, "historical": 0, "unverified": 1})

    def test_old_failed_source_is_preserved_not_assumed_recovered(self):
        source_id = "ths_sina_or_akshare_quote_decode"
        health = {"sources": {source_id: {"status": "degraded", "checked_at": "2026-07-07T15:00:00+08:00"}}}
        value = audit()
        value["provider"] = source_id
        report = build_report(health, payload([row(quote_audit=value)]), {}, NOW)
        self.assertEqual(report["forbidden_sources"], [])
        self.assertEqual(report["historical_sources"][0]["status"], "degraded")
        self.assertEqual(report["status"], "active_needs_review")

    def test_old_no_trigger_document_does_not_claim_live_monitor(self):
        report = build_report({}, payload([], timestamp="2026-07-27T10:00:00+08:00", source_status="monitor_live_no_trigger"), {}, NOW)
        self.assertEqual(report["status"], "waiting")

    def test_no_trigger_file_time_is_not_proof_of_current_monitor_health(self):
        # Includes yesterday's document just inside the source-health 24h window.
        cases = [
            ("2026-10-12T10:05:00+08:00", datetime(2026, 10, 13, 10, 0, tzinfo=TZ)),
            ((NOW - timedelta(minutes=5)).isoformat(), NOW),
            ((NOW + timedelta(minutes=5)).isoformat(), NOW),
            (NOW.isoformat(), NOW),
            (None, NOW),
            ("bad", NOW),
        ]
        for stamp, now in cases:
            with self.subTest(stamp=stamp, now=now):
                report = build_report({}, payload([], timestamp=stamp, source_status="monitor_live_no_trigger"), {}, now)
                self.assertEqual(report["status"], "waiting")
                self.assertIn("上次记录", report["summary"])
                self.assertIn("需由心跳和行情刷新确认", report["summary"])
                self.assertNotIn("当前没有", report["summary"])
                self.assertEqual(report["alert_state"]["current_count"], 0)


class AuditContracts(unittest.TestCase):
    def test_historical_and_unknown_pollution_are_not_current_outages(self):
        for stamp in ("2026-07-07T15:00:00+08:00", None, "bad", (NOW + timedelta(minutes=3)).isoformat()):
            health = {"timestamp": NOW.isoformat(), "sources": {"akshare": {"status": "degraded", "checked_at": stamp, "note": "decode 污染"}}}
            with self.subTest(stamp=stamp):
                original = copy.deepcopy(health)
                self.assertFalse(has_polluted_quote_source(health, NOW))
                issues = []
                validate_source_health(health, issues, NOW)
                self.assertEqual([i["code"] for i in issues], ["source_history_separated"])
                self.assertIn("未认定这些来源已恢复", issues[0]["message"])
                self.assertEqual(health, original)

    def test_current_pollution_remains_warning(self):
        health = {"sources": {"akshare": {"status": "failed", "last_check": NOW.isoformat(), "detail": "decode 污染"}}}
        self.assertTrue(has_polluted_quote_source(health, NOW))
        issues = []
        validate_source_health(health, issues, NOW)
        self.assertEqual([i["code"] for i in issues], ["source_failed"])

    def test_trade_gate_and_static_smoke_agree_on_expiry_and_closure(self):
        for changes, updates, expected in (({}, {}, True), ({"valid_until": NOW.isoformat()}, {}, False), ({"valid_until": None}, {}, False), ({}, {"source_status": "monitor_session_closed"}, False), ({"confirmation_level": "candidate"}, {}, False), ({"confirmation_level": None}, {}, False)):
            item = row(confirmation_level="confirmed")
            item.update(changes)
            data = payload([item], **updates)
            with self.subTest(changes=changes, updates=updates):
                self.assertEqual(alert_requires_trade_gate(data, data["alerts"], NOW, "morning"), expected)
                self.assertEqual(smoke_trade_gate(data, data["alerts"], NOW), expected)

    def test_current_confirmed_unverified_is_blocked_even_without_pollution(self):
        issues = []
        validate_alert(payload([row(confirmation_level="confirmed")]), {}, issues, NOW, "morning")
        self.assertTrue(any(i["code"] == "alert_quote_not_cross_verified" and i["severity"] == "critical" for i in issues))

    def test_expired_unverified_alert_does_not_block_current_confirmed(self):
        rows = [row(confirmation_level="confirmed", quote_audit=audit(True)), row(valid_until=NOW.isoformat())]
        issues = []
        validate_alert(payload(rows), {}, issues, NOW, "morning")
        self.assertFalse(any(i["severity"] == "critical" for i in issues), issues)

    def test_midday_text_and_string_list_pass_but_object_and_bad_list_fail(self):
        for risk, expected in (("风险仍待确认", False), (["风险一", "风险二"], False), ([], False), ({"text": "风险"}, True), ([{"text": "风险"}], True), (12, True)):
            issues = []
            midday = {"morning_snapshot": {}, "morning_review": {"one_sentence": "上午复盘"}, "afternoon_watch": [], "risk": risk}
            validate_core_file_contracts({"midday.json": midday}, issues, NOW)
            with self.subTest(risk=risk):
                self.assertEqual(any(i["code"] == "schema_contract_type" for i in issues), expected, issues)


class SourceHealthMetadataContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "source-health.json"
        self.health = {"timestamp": "2026-08-28T09:43:29+08:00", "sources": {
            "tencent_http": {"status": "ok", "last_check": "2026-07-27T10:00:00+08:00"},
            "tencent_minute_alert_verifier": {"status": "degraded", "last_check": "2026-07-20T10:00:00+08:00"}}}
        self.path.write_text(json.dumps(self.health), encoding="utf-8")

    def evidence(self, checked_at=None):
        verification = {"state": "passed", "source": "富途行情", "verifier_version": VERIFIER_VERSION,
                        "checked_at": checked_at or (NOW - timedelta(seconds=10)).isoformat(),
                        "representatives": [{"富途涨跌幅": 2}]}
        return payload([row(quote_audit={"secondary_verification": verification})])

    def test_generation_updates_document_only_and_preserves_other_sources(self):
        original = self.path.read_bytes()
        raw, result, changed = prepare_source_health_update(self.path, self.evidence(), NOW)
        self.assertTrue(changed)
        self.assertEqual(raw, original)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(result["timestamp"], NOW.isoformat())
        for key, value in self.health["sources"].items():
            self.assertEqual(result["sources"][key], value)
        self.assertEqual(result["sources"]["futu_minute_alert_verifier"]["last_check"], (NOW - timedelta(seconds=10)).isoformat())

    def test_identical_evidence_is_noop_not_timestamp_refresh(self):
        _, result, _ = prepare_source_health_update(self.path, self.evidence(), NOW)
        self.path.write_text(json.dumps(result), encoding="utf-8")
        _, repeated, changed = prepare_source_health_update(self.path, self.evidence(), NOW + timedelta(hours=1))
        self.assertFalse(changed)
        self.assertEqual(repeated, result)

    def test_old_evidence_cannot_replace_newer_source_check(self):
        _, result, _ = prepare_source_health_update(self.path, self.evidence(), NOW)
        self.path.write_text(json.dumps(result), encoding="utf-8")
        _, repeated, changed = prepare_source_health_update(self.path, self.evidence("2026-07-27T10:00:00+08:00"), NOW)
        self.assertFalse(changed)
        self.assertEqual(repeated, result)

    def test_no_verification_or_invalid_future_check_leaves_document_untouched(self):
        for data in (payload([]), self.evidence("bad"), self.evidence((NOW + timedelta(minutes=3)).isoformat())):
            _, result, changed = prepare_source_health_update(self.path, data, NOW)
            self.assertFalse(changed)
            self.assertEqual(result, self.health)

    def test_latest_check_compares_instants_not_offset_strings(self):
        data = self.evidence("2026-10-12T02:04:50Z")
        data["alerts"].extend(self.evidence("2026-10-12T10:04:40+08:00")["alerts"])
        _, result, _ = prepare_source_health_update(self.path, data, NOW)
        self.assertEqual(result["sources"]["futu_minute_alert_verifier"]["last_check"], "2026-10-12T02:04:50Z")

    def test_unexpected_source_container_is_preserved(self):
        for sources in ([{"id": "historical", "status": "degraded"}], "malformed"):
            document = {"timestamp": self.health["timestamp"], "sources": sources}
            self.path.write_text(json.dumps(document), encoding="utf-8")
            _, result, changed = prepare_source_health_update(self.path, self.evidence(), NOW)
            self.assertFalse(changed)
            self.assertEqual(result, document)


if __name__ == "__main__":
    unittest.main()

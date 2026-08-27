from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from verify_alert_quotes import (
    alert_needs_live_quotes,
    assess_change_consistency,
    enrich_payload,
    futu_endpoint_ready,
    minute_change,
    normalize_user_facing_text,
    remove_cross_source_missing,
    rewrite_verified_alert_reason,
    tick_change,
)


TZ = timezone(timedelta(hours=8))


class AlertQuoteVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 20, 10, 7, tzinfo=TZ)
        self.identity = {"甲公司": "sh600001", "乙公司": "sz000002", "丙公司": "sz300003"}
        self.minutes = {
            "sh600001": rows(("1002", 10.0), ("1005", 10.2)),
            "sz000002": rows(("1002", 20.0), ("1005", 20.3)),
            "sz300003": rows(("1002", 30.0), ("1005", 29.4)),
        }

    def loader(self, code: str):
        return self.minutes.get(code, [])

    def test_minute_change_uses_event_window(self) -> None:
        result = minute_change(self.minutes["sh600001"], datetime(2026, 7, 20, 10, 5, tzinfo=TZ), 3)
        self.assertEqual(result["start_minute"], "1002")
        self.assertEqual(result["end_minute"], "1005")
        self.assertAlmostEqual(result["change_pct"], 2.0)

    def test_tick_change_aligns_to_the_same_second_window(self) -> None:
        result = tick_change(
            tick_rows(
                ("2026-07-20T10:02:04+08:00", 10.0),
                ("2026-07-20T10:02:06+08:00", 10.01),
                ("2026-07-20T10:05:04+08:00", 10.2),
                ("2026-07-20T10:05:06+08:00", 10.21),
            ),
            datetime(2026, 7, 20, 10, 5, 5, tzinfo=TZ),
            3,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["alignment_method"], "tick_aligned")
        self.assertLessEqual(result["max_time_gap_seconds"], 1)
        self.assertTrue(assess_change_consistency(2.0, result)["magnitude_match"])

    def test_two_independent_representatives_can_pass_without_promoting_signal(self) -> None:
        payload = sample_payload([("甲公司", 2.0), ("乙公司", 1.5)])
        result = enrich_payload(payload, self.identity, self.loader, self.now)
        alert = result["alerts"][0]
        self.assertTrue(alert["quote_audit"]["sanity_checks"]["cross_source_verified"])
        self.assertEqual(alert["quote_audit"]["secondary_verification"]["state"], "passed")
        self.assertEqual(alert["confirmation_level"], "candidate")
        self.assertTrue(result["quote_audit"]["sanity_checks"]["cross_source_verified"])

    def test_direction_or_magnitude_mismatch_stays_unverified(self) -> None:
        payload = sample_payload([("甲公司", -2.0), ("乙公司", -1.5)])
        result = enrich_payload(payload, self.identity, self.loader, self.now)
        verification = result["alerts"][0]["quote_audit"]["secondary_verification"]
        self.assertEqual(verification["state"], "mismatch")
        self.assertFalse(result["alerts"][0]["quote_audit"]["sanity_checks"]["cross_source_verified"])

    def test_old_alert_is_not_backfilled(self) -> None:
        payload = sample_payload([("甲公司", 2.0), ("乙公司", 1.5)], event="2026-07-20T09:30:00+08:00")
        result = enrich_payload(payload, self.identity, self.loader, self.now)
        verification = result["alerts"][0]["quote_audit"]["secondary_verification"]
        self.assertEqual(verification["state"], "too_late_no_backfill")
        self.assertFalse(result["quote_audit"]["sanity_checks"]["cross_source_verified"])

    def test_fewer_than_two_resolved_quotes_cannot_pass(self) -> None:
        payload = sample_payload([("甲公司", 2.0), ("未知公司", 1.5)])
        result = enrich_payload(payload, self.identity, self.loader, self.now)
        verification = result["alerts"][0]["quote_audit"]["secondary_verification"]
        self.assertEqual(verification["state"], "insufficient_identity")

    def test_completed_fingerprint_does_not_fetch_again(self) -> None:
        payload = sample_payload([("甲公司", 2.0), ("乙公司", 1.5)])
        first = enrich_payload(payload, self.identity, self.loader, self.now)
        self.assertFalse(alert_needs_live_quotes(first["alerts"][0], self.now + timedelta(minutes=1)))

    def test_futu_is_formal_second_source_and_small_error_is_allowed(self) -> None:
        futu = {
            "sh600001": rows(("1002", 10.0), ("1005", 10.19)),
            "sz000002": rows(("1002", 20.0), ("1005", 20.29)),
        }
        payload = sample_payload([("甲公司", 2.0), ("乙公司", 1.5)])
        result = enrich_payload(payload, self.identity, self.loader, self.now, formal_minute_loader=lambda code: futu.get(code, []))
        verification = result["alerts"][0]["quote_audit"]["secondary_verification"]
        self.assertEqual(verification["state"], "passed")
        self.assertEqual(verification["source"], "富途行情")
        self.assertTrue(result["quote_audit"]["sanity_checks"]["cross_source_verified"])

    def test_futu_preflight_fails_fast_when_opend_is_unavailable(self) -> None:
        with patch("verify_alert_quotes.socket.create_connection", side_effect=ConnectionRefusedError):
            self.assertFalse(futu_endpoint_ready(timeout=0.01))

    def test_futu_preflight_accepts_a_ready_endpoint(self) -> None:
        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch("verify_alert_quotes.socket.create_connection", return_value=Connection()):
            self.assertTrue(futu_endpoint_ready(timeout=0.01))

    def test_exact_tick_alignment_wins_over_shifted_minute_closes(self) -> None:
        shifted_minutes = {
            "sh600001": rows(("1002", 10.0), ("1005", 10.05)),
            "sz000002": rows(("1002", 20.0), ("1005", 20.1)),
        }
        aligned_ticks = {
            "sh600001": tick_rows(
                ("2026-07-20T10:02:00+08:00", 10.0),
                ("2026-07-20T10:05:00+08:00", 10.2),
            ),
            "sz000002": tick_rows(
                ("2026-07-20T10:02:00+08:00", 20.0),
                ("2026-07-20T10:05:00+08:00", 20.3),
            ),
        }
        payload = sample_payload([("甲公司", 2.0), ("乙公司", 1.5)])
        result = enrich_payload(
            payload,
            self.identity,
            self.loader,
            self.now,
            formal_minute_loader=lambda code: shifted_minutes.get(code, []),
            formal_tick_loader=lambda code: aligned_ticks.get(code, []),
        )
        verification = result["alerts"][0]["quote_audit"]["secondary_verification"]
        self.assertEqual(verification["state"], "passed")
        self.assertTrue(all(row["对齐方式"] == "逐笔行情同一时点对齐" for row in verification["representatives"]))

    def test_aligned_tick_direction_conflict_remains_blocked(self) -> None:
        conflicting_ticks = {
            "sh600001": tick_rows(
                ("2026-07-20T10:02:00+08:00", 10.0),
                ("2026-07-20T10:05:00+08:00", 9.8),
            ),
            "sz000002": tick_rows(
                ("2026-07-20T10:02:00+08:00", 20.0),
                ("2026-07-20T10:05:00+08:00", 19.7),
            ),
        }
        payload = sample_payload([("甲公司", 2.0), ("乙公司", 1.5)])
        result = enrich_payload(
            payload,
            self.identity,
            self.loader,
            self.now,
            formal_minute_loader=self.loader,
            formal_tick_loader=lambda code: conflicting_ticks.get(code, []),
        )
        verification = result["alerts"][0]["quote_audit"]["secondary_verification"]
        self.assertEqual(verification["state"], "mismatch")
        self.assertTrue(all(row["复核结论"] == "明显冲突" for row in verification["representatives"]))

    def test_minute_ohlc_range_can_confirm_boundary_compatible_move(self) -> None:
        secondary = minute_change(
            [
                {"hhmm": "1002", "price": 10.02, "low": 10.0, "high": 10.04},
                {"hhmm": "1005", "price": 10.11, "low": 10.08, "high": 10.14},
            ],
            datetime(2026, 7, 20, 10, 5, tzinfo=TZ),
            3,
        )
        assessment = assess_change_consistency(1.0, secondary)
        self.assertEqual(assessment["label"], "一致")

    def test_wide_minute_range_is_insufficient_instead_of_false_conflict(self) -> None:
        secondary = minute_change(
            [
                {"hhmm": "1002", "price": 10.0, "low": 9.8, "high": 10.2},
                {"hhmm": "1005", "price": 10.1, "low": 9.9, "high": 10.4},
            ],
            datetime(2026, 7, 20, 10, 5, tzinfo=TZ),
            3,
        )
        assessment = assess_change_consistency(1.0, secondary)
        self.assertEqual(assessment["label"], "行情精度不足")

    def test_futu_missing_cannot_be_replaced_by_tencent_backup(self) -> None:
        payload = sample_payload([("甲公司", 2.0), ("乙公司", 1.5)])
        result = enrich_payload(payload, self.identity, self.loader, self.now, formal_minute_loader=lambda code: [])
        verification = result["alerts"][0]["quote_audit"]["secondary_verification"]
        self.assertEqual(verification["state"], "insufficient_precision")
        self.assertFalse(result["quote_audit"]["sanity_checks"]["cross_source_verified"])
        self.assertTrue(alert_needs_live_quotes(result["alerts"][0], self.now + timedelta(minutes=1)))

    def test_insufficient_precision_retries_live_but_is_not_overwritten_after_window(self) -> None:
        payload = sample_payload([("甲公司", 2.0), ("乙公司", 1.5)])
        first = enrich_payload(payload, self.identity, self.loader, self.now, formal_minute_loader=lambda code: [])
        later = enrich_payload(
            first,
            self.identity,
            self.loader,
            self.now + timedelta(minutes=10),
            formal_minute_loader=lambda code: [],
        )
        verification = later["alerts"][0]["quote_audit"]["secondary_verification"]
        self.assertEqual(verification["state"], "insufficient_precision")

    def test_completed_historical_verification_survives_non_semantic_metadata_upgrade(self) -> None:
        payload = sample_payload([("甲公司", 2.0), ("乙公司", 1.5)], event="2026-07-20T09:30:00+08:00")
        from verify_alert_quotes import alert_fingerprint
        payload["alerts"][0]["quote_audit"]["secondary_verification"] = {
            "state": "mismatch",
            "source": "富途行情",
            "fingerprint": alert_fingerprint(payload["alerts"][0]),
            "verifier_version": "futu-opend-2026-07-27.1",
        }
        payload["alerts"][0]["leaders"][0]["quote_time"] = "2026-07-20T09:29:58+08:00"
        result = enrich_payload(
            payload,
            self.identity,
            self.loader,
            self.now,
            formal_minute_loader=lambda code: [],
        )
        verification = result["alerts"][0]["quote_audit"]["secondary_verification"]
        self.assertEqual(verification["state"], "mismatch")
        self.assertEqual(verification["verifier_version"], "futu-opend-2026-07-27.1")

    def test_historical_tencent_verification_is_not_rewritten_as_futu(self) -> None:
        payload = sample_payload([("甲公司", 2.0), ("乙公司", 1.5)], event="2026-07-19T10:05:00+08:00")
        payload["alerts"][0]["quote_audit"]["secondary_verification"] = {
            "state": "passed",
            "source": "腾讯分钟行情",
            "fingerprint": "placeholder",
        }
        from verify_alert_quotes import alert_fingerprint
        payload["alerts"][0]["quote_audit"]["secondary_verification"]["fingerprint"] = alert_fingerprint(payload["alerts"][0])
        result = enrich_payload(payload, self.identity, self.loader, self.now, formal_minute_loader=lambda code: [])
        verification = result["alerts"][0]["quote_audit"]["secondary_verification"]
        self.assertEqual(verification["state"], "passed")
        self.assertEqual(verification["source"], "腾讯分钟行情")

    def test_passed_verification_removes_second_source_from_remaining_conditions(self) -> None:
        payload = sample_payload([("甲公司", 2.0), ("乙公司", 1.5)])
        first = enrich_payload(payload, self.identity, self.loader, self.now)
        first["alerts"][0]["quote_audit"]["missing_confirmation"] = "还差第二行情源交叉验证，或结构化封板>=2；继续观察扩散。"
        first["alerts"][0]["reason"] = "已满足risk candidate门槛，但缺第二行情源验证，暂为待确认风险。"
        result = enrich_payload(first, self.identity, self.loader, self.now + timedelta(minutes=1))
        remaining = result["alerts"][0]["quote_audit"]["missing_confirmation"]
        self.assertNotIn("第二行情源", remaining)
        self.assertIn("结构化封板", remaining)
        reason = result["alerts"][0]["reason"]
        self.assertIn("第二行情源已核验", reason)
        self.assertIn("风险候选", reason)
        self.assertNotIn("缺第二行情源", reason)

    def test_cross_source_missing_text_supports_both_phrasings(self) -> None:
        self.assertEqual(remove_cross_source_missing("还差第二行情源交叉验证，或结构化封板>=2。"), "还需结构化封板>=2。")
        self.assertEqual(remove_cross_source_missing("还差成交扩散；也缺少第二行情源交叉验证。"), "还差成交扩散")

    def test_verified_reason_no_longer_claims_second_source_is_missing(self) -> None:
        result = rewrite_verified_alert_reason("已满足risk candidate门槛，但缺第二行情源验证，暂为待确认风险。")
        self.assertEqual(result, "已满足风险候选门槛，第二行情源已核验；仍需满足其余交易条件，暂为待确认风险。")

    def test_user_facing_text_hides_engineering_status_names(self) -> None:
        result = normalize_user_facing_text("不满足risk candidate，写为invalidated；还需结构化limit_down_count>=2。")
        self.assertEqual(result, "不满足风险候选，判为失效；还需至少2只跌停的结构化板块证据。")


def rows(*values):
    return [{"hhmm": hhmm, "price": price} for hhmm, price in values]


def tick_rows(*values):
    return [{"time": timestamp, "price": price} for timestamp, price in values]


def sample_payload(leaders, event="2026-07-20T10:05:00+08:00"):
    return {
        "timestamp": "2026-07-20T10:05:10+08:00",
        "alerts": [{
            "id": "sample-alert",
            "time": event,
            "sector": "样例题材",
            "confirmation_level": "candidate",
            "leaders": [{"name": name, "change_pct": change} for name, change in leaders],
            "quote_audit": {
                "provider": "local_monitor_log",
                "quote_time": event,
                "pct_field": "3分钟涨跌幅",
                "sanity_checks": {"sample_count": len(leaders), "max_abs_leader_change_pct": 2.0, "cross_source_verified": False},
                "missing_confirmation": "还差成交扩散；也缺少第二行情源交叉验证。",
            },
        }],
    }


if __name__ == "__main__":
    unittest.main()

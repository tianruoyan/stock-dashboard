from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from verify_alert_quotes import alert_needs_live_quotes, enrich_payload, minute_change, remove_cross_source_missing


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

    def test_passed_verification_removes_second_source_from_remaining_conditions(self) -> None:
        payload = sample_payload([("甲公司", 2.0), ("乙公司", 1.5)])
        first = enrich_payload(payload, self.identity, self.loader, self.now)
        first["alerts"][0]["quote_audit"]["missing_confirmation"] = "还差第二行情源交叉验证，或结构化封板>=2；继续观察扩散。"
        result = enrich_payload(first, self.identity, self.loader, self.now + timedelta(minutes=1))
        remaining = result["alerts"][0]["quote_audit"]["missing_confirmation"]
        self.assertNotIn("第二行情源", remaining)
        self.assertIn("结构化封板", remaining)

    def test_cross_source_missing_text_supports_both_phrasings(self) -> None:
        self.assertEqual(remove_cross_source_missing("还差第二行情源交叉验证，或结构化封板>=2。"), "还需结构化封板>=2。")
        self.assertEqual(remove_cross_source_missing("还差成交扩散；也缺少第二行情源交叉验证。"), "还差成交扩散")


def rows(*values):
    return [{"hhmm": hhmm, "price": price} for hhmm, price in values]


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

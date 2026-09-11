import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from market_sentiment import sentiment_payload, number
from data_validity import TZ, risk_line, source_window, topic_current
from audit_dashboard_data import validate_source_health
from build_automation_health import monitor_health_row
from build_opportunity_watch import items_from_topics


class ReviewOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 11, 10, 30, tzinfo=TZ)
        self.indices = [{"name": str(i), "change_pct": 1} for i in range(5)]
        self.breadth = {"effective_limit_up_count": 60, "limit_down_count": 20,
                        "broken_board_count": 20, "up5_count": 150, "total_count": 5000}

    def test_score_matches_five_factor_weights(self):
        result = sentiment_payload(self.indices, self.breadth)
        self.assertEqual(result["score"], 70.67)
        self.assertEqual(result["level"], "偏暖")
        self.assertEqual(sum(x["weight_pct"] for x in result["components"]), 100)
        self.assertEqual(result["components"][3]["score"], 50)

    def test_missing_component_has_no_total_or_imputed_score(self):
        for field in self.breadth:
            row = dict(self.breadth)
            row[field] = None
            with self.subTest(field=field):
                result = sentiment_payload(self.indices, row)
                self.assertIsNone(result["score"])
                self.assertTrue(result["missing_components"])

    def test_zero_decliners_is_valid_not_missing(self):
        result = sentiment_payload(self.indices, {**self.breadth, "limit_down_count": 0})
        self.assertIsNotNone(result["score"])
        self.assertEqual(result["components"][1]["score"], 100)

    def test_empty_limit_pools_do_not_fabricate_a_ratio(self):
        result = sentiment_payload(self.indices, {**self.breadth, "effective_limit_up_count": 0, "limit_down_count": 0})
        self.assertIsNone(result["score"])

    def test_incomplete_indices_prevent_score(self):
        self.assertIsNone(sentiment_payload(self.indices[:4], self.breadth)["score"])
        self.assertIsNone(sentiment_payload([{"change_pct": None}] * 5, self.breadth)["score"])

    def test_invalid_counts_and_non_finite_values(self):
        for value in (True, "", "NaN", "Infinity", None):
            self.assertIsNone(number(value))
        self.assertIsNone(sentiment_payload(self.indices, {**self.breadth, "up5_count": 6000})["score"])

    def test_risk_type_beats_keyword_location(self):
        self.assertTrue(risk_line({"type": "risk_line", "status": "行业排名居后"}))
        self.assertTrue(risk_line({"name": "行业相对弱势：农业"}))
        self.assertFalse(risk_line({"type": "watch_line", "risk": "若下跌则失效"}))

    def test_source_history_is_not_current_or_recovered(self):
        for age, expected in ((timedelta(minutes=5), "current"), (timedelta(days=2), "history"), (timedelta(minutes=-5), "unknown")):
            self.assertEqual(source_window({"last_check": (self.now - age).isoformat(), "status": "failed"}, self.now), expected)
        self.assertEqual(source_window({"status": "failed"}, self.now), "unknown")

    def test_audit_preserves_current_failure_and_summarizes_history(self):
        now = datetime.now(TZ)
        issues = []
        validate_source_health({"sources": {"old": {"status": "failed", "last_check": "2026-07-01T10:00:00+08:00"},
                                             "current": {"status": "failed", "last_check": now.isoformat()}}}, issues)
        self.assertEqual(sum(x["code"] == "source_failed" for x in issues), 1)
        self.assertEqual(sum(x["code"] == "source_history_separated" for x in issues), 1)

    def test_old_topic_cannot_reenter_opportunity_queue(self):
        topic = {"name": "半导体设备", "updated_at": "2026-09-06T15:00:00+08:00", "conclusion": "强势"}
        self.assertFalse(topic_current(topic, "2026-09-11"))
        self.assertEqual(items_from_topics({"timestamp": "2026-09-11T11:00:00+08:00", "topics": [topic]}), [])

    def monitor(self, healthy, stale=False):
        stamp = (self.now - timedelta(minutes=10 if stale else 1)).isoformat()
        value = {"checked_at": stamp, "monitor": {"healthy": healthy, "heartbeat_at": stamp}}
        with patch("build_automation_health.load_json", return_value=value), patch("intraday_recovery.is_trading_day", return_value=True):
            return monitor_health_row({"id": "alerts"}, self.now, "2026-09-11")

    def test_monitor_healthy_without_signal_is_running(self):
        self.assertEqual(self.monitor(True)["status"], "ok")

    def test_monitor_failed_or_stale_is_not_waiting_until_close(self):
        self.assertEqual(self.monitor(False)["status"], "late")
        self.assertEqual(self.monitor(True, stale=True)["status"], "late")


if __name__ == "__main__":
    unittest.main()

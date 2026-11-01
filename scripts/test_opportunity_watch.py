"""Deterministic synthetic fixtures: never write test quotes into public data."""
import copy
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import build_opportunity_watch as watch
import build_decision_feed as feed


class WatchRevalidationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-10-22T10:10:00+08:00")
        self.topic = {"name": "光模块/高速互联", "updated_at": "2026-10-22T08:30:00+08:00",
                      "status": "等待扩散", "action": "先看中际旭创、新易盛共振；未扩散时按兑现风险处理。"}
        self.quotes = {"stocks": [
            {"code": "sz300502", "name": "新易盛", "price": 90, "open": 100, "change_pct": -9,
             "quote_time": "20261022100603", "source": "测试行情"},
            {"code": "sz300308", "name": "中际旭创", "price": 94, "open": 101, "change_pct": -6,
             "quote_time": "20261022100604", "source": "测试行情"}]}

    def report(self, topics=None, quotes=None, premarket=None, evening=None, now=None):
        return watch.build_report(premarket or {}, evening or {}, {"topics": topics or []},
                                  quotes if quotes is not None else self.quotes, now or self.now)

    def cpo(self, report):
        return next(row for row in report["items"] if row["theme"] == "CPO/光模块")

    def test_conditional_positive_words_never_create_high_priority(self):
        row = watch.items_from_topics({"topics": [self.topic]}, now=self.now)[0]
        self.assertEqual(row["priority"], "medium")
        self.assertEqual(watch.make_item("CPO/光模块", "晚间P0", "优先受益", "high")["priority"], "medium")

    def test_old_file_cannot_validate_itself_as_today(self):
        old = dict(self.topic, updated_at="2026-10-19T08:30:00+08:00")
        self.assertEqual(watch.items_from_topics({"trade_date": "2026-10-19", "topics": [old]}, now=self.now), [])
        self.assertEqual(self.report(topics=[old], quotes={})["items"], [])

    def test_current_risk_survives_expired_research_without_reusing_it(self):
        old = dict(self.topic, updated_at="2026-10-19T08:30:00+08:00", conclusion="旧日海外大跌")
        row = self.cpo(self.report(topics=[old]))
        self.assertEqual(row["status"], "risk_observation")
        self.assertEqual(row["source_phase"], "盘中行情")
        self.assertNotIn("旧日海外", str(row))
        self.assertNotIn("source_as_of", row)
        self.assertEqual(len(row["representative_quotes"]), 2)

    def test_actual_declines_override_current_plan(self):
        row = self.cpo(self.report(topics=[self.topic]))
        self.assertEqual(row["status"], "risk_observation")
        self.assertIn("暂不列为优先机会", row["assessment"])
        self.assertIn("300502", row["evidence"][0])
        self.assertIn("10:06:03", row["evidence"][0])
        self.assertIn("测试行情", row["evidence"][0])

    def test_small_declines_and_rebound_do_not_auto_confirm(self):
        for pct, price in [(-0.1, 99), (4, 104)]:
            quotes = copy.deepcopy(self.quotes)
            for row in quotes["stocks"]:
                row.update(change_pct=pct, price=price)
            item = self.cpo(self.report(topics=[self.topic], quotes=quotes))
            self.assertEqual(item["status"], "waiting")
            self.assertNotEqual(item["priority"], "high")

    def test_single_stock_or_duplicate_is_not_a_majority(self):
        for stocks in [self.quotes["stocks"][:1], [self.quotes["stocks"][0]] * 3]:
            row = self.cpo(self.report(topics=[self.topic], quotes={"stocks": stocks}))
            self.assertEqual(row["status"], "waiting")

    def test_bad_quote_metadata_prices_and_time_do_not_confirm_risk(self):
        for change in [{"quote_time": ""}, {"source": ""}, {"open": None}, {"price": 0},
                       {"change_pct": "NaN"}, {"code": ""}, {"quote_time": "20261021100603"},
                       {"quote_time": "20261022101100"}, {"quote_time": "2026-10-22T10:06:03"},
                       {"quote_time": "20261022094959"}]:
            quotes = copy.deepcopy(self.quotes)
            for quote in quotes["stocks"]:
                quote.update(change)
            with self.subTest(change=change):
                row = self.cpo(self.report(topics=[self.topic], quotes=quotes))
                self.assertEqual(row["status"], "waiting")
                self.assertEqual(row["evidence"], [])

    def test_old_and_new_sampling_windows_not_merged(self):
        quotes = copy.deepcopy(self.quotes)
        quotes["stocks"][0]["quote_time"] = "20261022100000"
        self.assertEqual(self.cpo(self.report(topics=[self.topic], quotes=quotes))["status"], "waiting")

    def test_lunch_holds_close_snapshot_but_afternoon_expires_it(self):
        quotes = copy.deepcopy(self.quotes)
        for row in quotes["stocks"]:
            row["quote_time"] = "20261022113000"
        lunch = self.now.replace(hour=12)
        self.assertEqual(self.cpo(self.report(topics=[self.topic], quotes=quotes, now=lunch))["status"], "risk_observation")
        afternoon = self.now.replace(hour=13)
        self.assertEqual(self.cpo(self.report(topics=[self.topic], quotes=quotes, now=afternoon))["status"], "waiting")

    def test_calendar_and_close_do_not_claim_live_opportunities(self):
        self.assertEqual(self.report(now=self.now + timedelta(days=2))["items"], [])
        row = self.cpo(self.report(topics=[self.topic], now=self.now.replace(hour=15)))
        self.assertEqual(row["status"], "session_closed")

    def test_premarket_target_and_evening_trade_date_not_rejuvenated(self):
        plan = {"trade_date": "2026-10-21", "timestamp": "2026-10-22T08:30:00+08:00",
                "market_context": {"benefit_themes": ["CPO/光模块"]}}
        self.assertEqual(self.report(quotes={}, premarket=plan)["items"], [])
        plan["trade_date"] = "2026-10-22"
        self.assertEqual(self.cpo(self.report(quotes={}, premarket=plan))["status"], "waiting")
        evening = {"trade_date": "2026-10-20", "timestamp": "2026-10-21T07:44:00+08:00",
                   "news": [{"text": "CPO共振"}]}
        self.assertEqual(self.report(quotes={}, evening=evening)["items"], [])
        evening.update(trade_date="2026-10-21", timestamp="2026-10-21T20:00:00+08:00")
        self.assertEqual(self.cpo(self.report(quotes={}, evening=evening))["status"], "waiting")

    def test_risk_is_not_reintroduced_into_opportunities_or_verifications(self):
        report = self.report(topics=[self.topic])
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return self.now
        files = {"opportunity-watch.json": report}
        with patch.object(feed, "datetime", Clock):
            self.assertEqual(feed.opportunity_watch_candidates(files), [])
            self.assertTrue(feed.opportunity_watch_candidates(files, {"risk_observation"}))
            self.assertEqual(feed.build_opportunities(files, "2026-10-22"), [])
            self.assertTrue(any(row["type"] == "representative_risk" for row in feed.build_risks(files, "2026-10-22")))
            self.assertFalse(any(row.get("type") == "opportunity_watch" for row in feed.build_verifications(files, "2026-10-22")))


if __name__ == "__main__":
    unittest.main()

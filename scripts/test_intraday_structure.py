import copy
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from pathlib import Path

from intraday_structure import CN, apply_facts, collect, current_breadth, validate_pool


class MarketStructureTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 11, 11, 0, tzinfo=CN)
        self.row = {"trade_date": "2026-09-11", "as_of": self.now.isoformat(),
                    "advance_count": 300, "decline_count": 5100, "flat_count": 100,
                    "total_count": 5500, "missing_quote_count": 5,
                    "source_name": "新浪", "source_url": "https://example.com", "scope": "沪深京",
                    "quality_state": "degraded"}

    def test_partial_quotes_are_explicit(self):
        self.assertEqual(current_breadth(self.row, self.now)["missing_quote_count"], 5)

    def test_wrong_day_stale_future_and_naive_rejected(self):
        for stamp in (self.now - timedelta(days=1), self.now - timedelta(minutes=21),
                      self.now + timedelta(minutes=3), self.now.replace(tzinfo=None)):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                current_breadth({**self.row, "as_of": stamp.isoformat()}, self.now)

    def test_bad_counts_rejected(self):
        for change in ({"total_count": 5600}, {"advance_count": -1}, {"flat_count": None},
                       {"decline_count": True}, {"missing_quote_count": -1}, {"source_url": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                current_breadth({**self.row, **change}, self.now)

    def test_empty_complete_pool_is_zero(self):
        self.assertEqual(validate_pool({"rc": 0, "data": {"qdate": 20260911, "tc": 0, "pool": []}}, "2026-09-11"), 0)

    def test_pool_partial_wrong_date_and_duplicate_rejected(self):
        for data in ({"qdate": 20260911, "tc": 12, "pool": []},
                     {"qdate": 20260910, "tc": 0, "pool": []},
                     {"qdate": 20260911, "tc": 2, "pool": [{"c": "1"}, {"c": "1"}]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_pool({"rc": 0, "data": data}, "2026-09-11")

    def test_failure_is_not_zero_and_analysis_unchanged(self):
        payload = {"timestamp": "original", "sentiment": {"judgement": "原判断", "limit_down_count": 12},
                   "main_trends": [{"name": "原主线"}]}
        before = copy.deepcopy(payload)
        apply_facts(payload, {"breadth": self.row, "pools": {"limit_up": {"count": 25}},
                              "errors": {"limit_down": "等待更新"}})
        self.assertIsNone(payload["sentiment"]["limit_down_count"])
        self.assertEqual(payload["sentiment"]["limit_up_count"], 25)
        self.assertEqual(payload["timestamp"], before["timestamp"])
        self.assertEqual(payload["main_trends"], before["main_trends"])
        self.assertEqual(payload["sentiment"]["judgement"], "原判断")

    def test_sources_fail_independently(self):
        def pool(key, now):
            if key == "limit_down":
                raise OSError("offline")
            return {"count": 2}
        with patch("intraday_structure.fetch_pool", side_effect=pool):
            facts = collect(self.now, Path("/nonexistent/public.json"))
        self.assertEqual(set(facts["pools"]), {"limit_up", "broken_board"})
        self.assertEqual(set(facts["errors"]), {"breadth", "limit_down"})


if __name__ == "__main__":
    unittest.main()

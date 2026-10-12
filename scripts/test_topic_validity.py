"""Research evidence gates shared by opportunity, decision and theme builders."""
import copy
import unittest
from datetime import datetime
from functools import partial
from unittest.mock import patch

import build_decision_feed as decisions
import build_opportunity_watch as opportunities
import build_theme_shifts as shifts
from data_validity import topic_current


class TopicValidityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-10-12T16:00:00+08:00")
        self.day = "2026-10-12"
        self.topic = {"name": "半导体设备", "status": "强化", "conclusion": "核心代表股放量，观察扩散",
                      "action": "等待确认", "updated_at": "2026-10-12T15:35:00+08:00",
                      "source_as_of": "2026-10-12T15:00:00+08:00"}

    def current(self, item):
        return topic_current(item, self.day, now=self.now)

    def test_valid_research_and_timezone_conversion(self):
        self.assertTrue(self.current(self.topic))
        item = dict(self.topic, updated_at="2026-10-12T07:35:00Z", source_as_of="2026-10-12T07:00:00Z")
        self.assertTrue(self.current(item))
        item["source_as_of"] = "2026-10-11T17:00:00-07:00"  # 10/12 08:00 CST
        self.assertTrue(self.current(item))

    def invalid_topics(self):
        mutations = [
            {"update_scope": "closing_representatives_only"},
            {"source_status": "invalidated"},
            {"updated_at": "2026-10-12T16:01:00+08:00"},
            {"source_as_of": "2026-10-12T16:01:00+08:00"},
            {"updated_at": "2026-10-09T15:35:00+08:00"},
            {"source_as_of": "2026-10-09T15:00:00+08:00"},
            {"source_as_of": "2026-10-12 latest close; collected later"},
            {"updated_at": "2026-10-12T15:35:00"},
            {"source_as_of": "2026-10-12T15:00:00"},
            {"updated_at": "2026-10-12"},
            {"source_as_of": "2026-10-12"},
            {"source_as_of": None},
            {"analysis_time": None},
            {"valid_until": "2026-10-12T15:59:59+08:00"},
            {"valid_until": "2026-10-12T16:00:00+08:00"},
            {"valid_until": "2026-10-12T19:00:00"},
            {"valid_until": "not-a-date"},
        ]
        return [dict(self.topic, **change) for change in mutations]

    def test_representative_old_future_ambiguous_or_expired_evidence_is_rejected(self):
        for item in self.invalid_topics():
            with self.subTest(item=item):
                self.assertFalse(self.current(item))

    def test_source_or_nested_fact_time_cannot_replace_research_time(self):
        item = dict(self.topic)
        del item["updated_at"]
        self.assertFalse(self.current(item))
        item["representative_facts"] = {"updated_at": "2026-10-12T15:50:00+08:00",
                                        "source_as_of": "2026-10-12T15:00:00+08:00"}
        self.assertFalse(self.current(item))
        item["updated_at"] = "2026-10-09T15:35:00+08:00"
        self.assertFalse(self.current(item))

    def test_absent_optional_source_and_future_validity_deadline_are_allowed(self):
        item = dict(self.topic, valid_until="2026-10-13T08:00:00+08:00")
        del item["source_as_of"]
        self.assertTrue(self.current(item))

    def test_bad_target_date_or_naive_clock_cannot_claim_current(self):
        self.assertFalse(topic_current(self.topic, "2026-10-12 trailing", now=self.now))
        self.assertFalse(topic_current(self.topic, self.day, now=self.now.replace(tzinfo=None)))

    def downstream(self, item):
        data = {"timestamp": "2026-10-12T15:45:00+08:00", "trade_date": self.day, "topics": [item]}
        gate = partial(topic_current, now=self.now)
        with patch.object(opportunities, "topic_current", side_effect=gate), \
             patch.object(decisions, "topic_current", side_effect=gate), \
             patch.object(shifts, "topic_current", side_effect=gate):
            return [opportunities.items_from_topics(data),
                    decisions.risk_theme_candidates({"topics.json": data}, self.day),
                    shifts.collect_candidates({}, {}, {}, data)]

    def test_all_three_downstream_filters_reject_invalid_topics(self):
        for item in self.invalid_topics():
            with self.subTest(item=item):
                self.assertEqual(self.downstream(item), [[], [], []])

    def test_all_three_downstream_filters_keep_actual_current_research(self):
        self.assertTrue(all(self.downstream(self.topic)))
        item = copy.deepcopy(self.topic)
        item["representative_facts"] = {"update_scope": "closing_representatives_only"}
        self.assertTrue(all(self.downstream(item)))


if __name__ == "__main__":
    unittest.main()

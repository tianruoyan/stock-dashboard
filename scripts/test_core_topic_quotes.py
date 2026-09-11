import unittest
from datetime import datetime, timezone, timedelta
from build_topics import closing_representatives, topic_update, CORE

class CoreTopicTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 11, 15, 35, tzinfo=timezone(timedelta(hours=8)))
        self.expected = CORE["医药修复链"]

    def raw(self, code, name, pct="-2", stamp="20260911153100"):
        f = [""] * 40
        for i, value in {1:name, 3:"9.8", 4:"10", 33:"10.1", 32:pct, 30:stamp}.items(): f[i] = value
        return {"query_code": code, "fields": f}

    def test_real_stock_semantics_and_no_foreign_topic_evidence(self):
        raw = [self.raw(code, name) for code, name in self.expected.items()]
        raw.append(self.raw("sz002409", "雅克科技"))
        quotes = closing_representatives(raw, self.expected, self.now)
        result = topic_update("医药修复链", quotes, self.now, self.now.isoformat())
        self.assertEqual(len(quotes), 3)
        self.assertEqual(result["status"], "代表股多数走弱")
        self.assertNotIn("雅克科技", str(result))
        self.assertNotIn("修复已经出现", result["conclusion"])
        self.assertTrue(all(row["source"] and row["code"] and row["quote_time"] for row in quotes))

    def test_partial_cannot_refresh_the_whole_topic(self):
        self.assertIsNone(topic_update("医药修复链", [], self.now, self.now.isoformat()))

    def test_stale_wrong_identity_or_price_rejected(self):
        for row in (self.raw("sh600276", "恒瑞医药", stamp="20260910153100"),
                    self.raw("sh600276", "恒瑞医药", stamp="20260911143000"),
                    self.raw("sh600276", "另一家公司"), self.raw("sh600276", "恒瑞医药", pct="NaN"),
                    self.raw("sh600276", "恒瑞医药", pct="8")):
            self.assertEqual(closing_representatives([row], self.expected, self.now), [])

if __name__ == '__main__':
    unittest.main()

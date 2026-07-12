from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from v2_platform.sentiment_collector import DOWN_URL, UP_URL, V2SentimentCollector


ROOT = Path(__file__).resolve().parents[1]


class V2SentimentCollectorTests(unittest.TestCase):
    def prepare(self, root: Path) -> None:
        (root / "config").mkdir()
        (root / "config/v2-market-calendar.json").write_text((ROOT / "config/v2-market-calendar.json").read_text(encoding="utf-8"), encoding="utf-8")

    def test_ladders_and_promotion_use_explicit_pool_fields(self) -> None:
        responses = {
            (UP_URL, "20260710"): {"rc": 0, "data": {"qdate": 20260710, "tc": 3, "pool": [
                {"c":"000001","m":0,"n":"甲","lbc":2,"zdp":10.0,"hybk":"行业A","zbc":1},
                {"c":"600001","m":1,"n":"乙","lbc":1,"zdp":10.0,"hybk":"行业B","zbc":0},
                {"c":"000003","m":0,"n":"ST丙","lbc":1,"zdp":5.0,"hybk":"行业C","zbc":0}
            ]}},
            (DOWN_URL, "20260710"): {"rc": 0, "data": {"qdate": 20260710, "tc": 1, "pool": [
                {"c":"000004","m":0,"n":"丁","days":3,"zdp":-10.0,"hybk":"行业D","oc":2}
            ]}},
            (UP_URL, "20260709"): {"rc": 0, "data": {"qdate": 20260709, "tc": 2, "pool": [
                {"c":"000001","m":0,"n":"甲","lbc":1}, {"c":"000005","m":0,"n":"戊","lbc":1}
            ]}},
        }
        def fake(url, params):
            return responses[(url, params["date"])]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            payload = V2SentimentCollector(root, fetcher=fake).collect(date(2026, 7, 10))
            self.assertEqual(payload["limit_up_ladder"]["filtered_count"], 2)
            self.assertEqual(payload["limit_up_ladder"]["items"][0]["height"], 2)
            self.assertEqual(payload["limit_down_ladder"]["items"][0]["height"], 3)
            promotion = payload["promotion_rate"]["items"][0]
            self.assertEqual(promotion["candidate_count"], 2)
            self.assertEqual(promotion["promoted_count"], 1)
            self.assertEqual(payload["high_level_loss_effect"]["state"], "data_missing")

    def test_source_trade_date_mismatch_fails_closed(self) -> None:
        def fake(url, params):
            return {"rc": 0, "data": {"qdate": 20260709, "tc": 0, "pool": []}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            with self.assertRaisesRegex(ValueError, "source_trade_date_mismatch"):
                V2SentimentCollector(root, fetcher=fake).collect(date(2026, 7, 10))

    def test_high_level_loss_uses_next_day_close_and_low(self) -> None:
        def fake(url, params):
            if url == UP_URL and params["date"] == "20260710":
                return {"rc":0,"data":{"qdate":20260710,"tc":1,"pool":[{"c":"000001","m":0,"n":"甲","lbc":3,"zdp":10}]}}
            if url == DOWN_URL:
                return {"rc":0,"data":{"qdate":20260710,"tc":0,"pool":[]}}
            if url == UP_URL and params["date"] == "20260709":
                return {"rc":0,"data":{"qdate":20260709,"tc":1,"pool":[{"c":"000001","m":0,"n":"甲","lbc":2}]}}
            raise AssertionError((url, params))
        def fake_quotes(codes):
            return {"sz000001":{"name":"甲","code":"000001","close":94.0,"previous_close":100.0,"volume":1000.0,"high":101.0,"low":90.0,"as_of":"20260710150000"}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            effect = V2SentimentCollector(root, fetcher=fake, quote_fetcher=fake_quotes).collect(date(2026, 7, 10))["high_level_loss_effect"]
            self.assertEqual(effect["state"], "usable")
            self.assertEqual(effect["median_return_pct"], -6.0)
            self.assertEqual(effect["max_adverse_excursion_pct"], -10.0)
            self.assertEqual(effect["judgement"], "高位亏钱效应明显")


if __name__ == "__main__":
    unittest.main()

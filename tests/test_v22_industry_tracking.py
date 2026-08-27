from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from v2_platform.industry_tracking import V22IndustryTrackingBuilder


ROOT = Path(__file__).resolve().parents[1]


class V22IndustryTrackingTests(unittest.TestCase):
    def test_real_configuration_tracks_ai_industries_without_replacing_existing_industries(self) -> None:
        payload = V22IndustryTrackingBuilder(ROOT).build()
        self.assertGreaterEqual(payload["tracking_count"], 2)
        by_name = {item["name"]: item for item in payload["items"]}
        ai_items = [by_name["AI训练基础设施持续观察"], by_name["端侧AI推理持续观察"]]
        self.assertEqual(ai_items[0]["classification"], "阶段性确认")
        self.assertEqual(ai_items[1]["classification"], "逻辑成立但未交易确认")
        self.assertEqual(sum(len(item["representative_stocks"]) for item in ai_items), 8)
        self.assertTrue(all(item["missing_evidence"] for item in ai_items))
        self.assertTrue(all(item["failure_trigger"] for item in ai_items))
        self.assertTrue(all(item["automatic_upgrade"] is False for item in payload["items"]))
        self.assertTrue(all(item["is_user_asset"] is False for item in payload["items"]))
        self.assertTrue(all(item["trading_enabled"] is False for item in payload["items"]))
        self.assertFalse(payload["guardrails"]["user_assets_modified"])
        self.assertFalse(payload["guardrails"]["v1_modified"])

    def test_quote_freshness_and_linked_topic_context_are_date_aware(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir(parents=True)
            (root / "data/v2/inputs").mkdir(parents=True)
            (root / "data/v2/v22").mkdir(parents=True)
            (root / "config/v2-formal-observation.json").write_text(json.dumps({
                "themes": [{
                    "name": "测试行业",
                    "stocks": ["测试股份"],
                    "related_runtime_topics": ["测试专题"],
                    "current_status": "阶段性确认",
                    "current_updated_at": "2026-08-06T09:00:00+08:00",
                    "missing_evidence": ["订单"],
                    "failure_trigger": "订单失效"
                }],
                "stocks": [{
                    "name": "测试股份",
                    "code": "sh600000",
                    "chain_side": "training",
                    "benefit_tier": "high_certainty",
                    "evidence_grade": "A",
                    "source_refs": [{"title": "公告", "url": "https://example.com/a"}]
                }]
            }, ensure_ascii=False), encoding="utf-8")
            (root / "data/v2/inputs/representative-stock-quotes.json").write_text(json.dumps({
                "quotes": [{
                    "name": "测试股份", "code": "sh600000", "stock_change_pct": 2.0,
                    "stock_quote_as_of": "2026-08-06T10:00:00+08:00", "stock_quote_source": "测试行情"
                }]
            }, ensure_ascii=False), encoding="utf-8")
            (root / "data/topics.json").write_text(json.dumps({
                "topics": [{"name": "测试专题", "status": "强化", "conclusion": "同步走强", "updated_at": "2026-08-06T10:00:00+08:00"}]
            }, ensure_ascii=False), encoding="utf-8")
            (root / "data/v2/v22/market-environment.json").write_text(json.dumps({
                "trade_date": "2026-08-06", "as_of": "2026-08-06T10:00:00+08:00", "headline": "等待确认"
            }, ensure_ascii=False), encoding="utf-8")
            payload = V22IndustryTrackingBuilder(
                root,
                now=datetime(2026, 8, 6, 10, 5, tzinfo=timezone.utc),
            ).build()
            item = payload["items"][0]
            self.assertEqual(item["representative_stocks"][0]["quote_state"], "当前交易日已核验")
            self.assertEqual(item["linked_market_topics"][0]["state"], "强化")


if __name__ == "__main__":
    unittest.main()

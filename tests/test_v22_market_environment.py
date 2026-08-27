from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from v2_platform.market_environment import DIMENSION_LABELS, V22MarketEnvironmentBuilder


ROOT = Path(__file__).resolve().parents[1]


class V22MarketEnvironmentTests(unittest.TestCase):
    def test_workspace_build_has_exactly_eight_dimensions_and_stays_shadow(self) -> None:
        payload = V22MarketEnvironmentBuilder(ROOT).build()
        self.assertEqual(payload["mode"], "shadow_only")
        self.assertTrue(payload["facts_only"])
        self.assertEqual(len(payload["dimensions"]), 8)
        self.assertEqual({item["dimension_code"] for item in payload["dimensions"]}, set(DIMENSION_LABELS))
        self.assertFalse(payload["guardrails"]["current_v2_action_modified"])
        self.assertFalse(payload["guardrails"]["environment_state_machine_enabled"])
        self.assertFalse(payload["guardrails"]["automatic_trading"])
        self.assertFalse(payload["guardrails"]["user_assets_modified"])
        sentiment = payload["sentiment_view"]
        self.assertIn(sentiment["status"], {"risk", "positive", "repair", "neutral", "unknown"})
        self.assertTrue(sentiment["headline"])
        self.assertTrue(sentiment["judgment"])
        self.assertTrue(sentiment["action"])
        self.assertEqual(len(sentiment["drivers"]), 4)
        self.assertEqual(
            {item["label"] for item in sentiment["drivers"]},
            {"涨停与跌停表现", "上涨与下跌家数", "高位股表现", "主要指数表现"},
        )
        self.assertNotIn("另一侧证据", sentiment["judgment"])
        self.assertNotIn("市场宽度", sentiment["judgment"])
        self.assertTrue(any(term in sentiment["judgment"] for term in ("上涨股票", "涨停", "跌停", "高位股")))

    def test_current_snapshot_uses_backfilled_indices_without_mixing_trade_dates(self) -> None:
        payload = V22MarketEnvironmentBuilder(ROOT).build()
        sentiment_input = json.loads((ROOT / "data/v2/inputs/sentiment-structure.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["trade_date"], sentiment_input["trade_date"])
        dimensions = {item["dimension_code"]: item for item in payload["dimensions"]}
        same_day_indices = [
            item for item in json.loads((ROOT / "data/intraday.json").read_text(encoding="utf-8")).get("indices", [])
            if str(item.get("quote_time") or "").startswith(payload["trade_date"].replace("-", ""))
        ]
        positive_count = sum(float(item["pct"]) > 0 for item in same_day_indices)
        negative_count = sum(float(item["pct"]) < 0 for item in same_day_indices)
        if same_day_indices:
            expected_level = "support" if positive_count >= 4 else ("suppress" if negative_count >= 4 else "neutral")
            self.assertEqual(dimensions["index_structure"]["support_level"], expected_level)
            self.assertEqual(dimensions["index_structure"]["freshness_state"], "current")
            self.assertEqual(dimensions["index_structure"]["quality_state"], "usable")
        else:
            self.assertEqual(dimensions["index_structure"]["support_level"], "unknown")
            self.assertIn(dimensions["index_structure"]["freshness_state"], {"missing", "stale"})
            self.assertEqual(dimensions["index_structure"]["quality_state"], "unknown")
        self.assertEqual(dimensions["sentiment_structure"]["freshness_state"], "current")
        self.assertFalse(payload["guardrails"]["mixed_trade_dates_used_as_current"])

    def test_workspace_liquidity_does_not_infer_direction_without_comparable_baseline(self) -> None:
        payload = V22MarketEnvironmentBuilder(ROOT).build()
        liquidity = next(item for item in payload["dimensions"] if item["dimension_code"] == "liquidity")
        self.assertEqual(liquidity["support_level"], "unknown")
        source = json.loads((ROOT / "data/v2/inputs/market-liquidity.json").read_text(encoding="utf-8"))
        expected_quality = "degraded" if source.get("trade_date") == payload["trade_date"] else "unknown"
        self.assertEqual(liquidity["quality_state"], expected_quality)
        self.assertTrue(liquidity["missing_evidence"])

    def test_breadth_and_high_level_risk_are_not_described_as_directionless(self) -> None:
        dimensions = [
            {"dimension_code": "sentiment_structure", "support_level": "neutral", "fact_summary": ["涨停45只、跌停54只。"]},
            {"dimension_code": "market_breadth", "support_level": "suppress", "fact_summary": ["上涨1767家、下跌3635家。"]},
            {"dimension_code": "position_fragility", "support_level": "suppress", "fact_summary": ["高位股有明显回落风险。"]},
            {"dimension_code": "index_structure", "support_level": "suppress", "fact_summary": ["5个主要指数全部下跌。"]},
        ]
        result = V22MarketEnvironmentBuilder._sentiment_user_view(dimensions, "2026-07-30T15:00:00+08:00")
        self.assertEqual(result["status"], "risk")
        self.assertIn("亏钱效应", result["judgment"])
        self.assertIn("不追高", result["action"])
        self.assertNotIn("看不出一致方向", result["judgment"])

    def test_expanding_turnover_during_broad_decline_is_risk_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.copy_fixture(root)
            liquidity_path = root / "data/v2/inputs/market-liquidity.json"
            liquidity_path.parent.mkdir(parents=True, exist_ok=True)
            liquidity_path.write_text(json.dumps({
                "trade_date": "2026-07-17",
                "as_of": "2026-07-17T15:00:00+08:00",
                "total_turnover": 15000,
                "turnover_change_pct": 12,
                "top_concentration_pct": 20,
                "unit": "亿元",
            }, ensure_ascii=False), encoding="utf-8")
            breadth_path = root / "data/v2/inputs/market-breadth.json"
            breadth_path.write_text(json.dumps({
                "trade_date": "2026-07-17",
                "as_of": "2026-07-17T15:00:00+08:00",
                "advance_count": 1000,
                "decline_count": 3000,
                "flat_count": 100,
            }, ensure_ascii=False), encoding="utf-8")
            payload = V22MarketEnvironmentBuilder(root).build()
            liquidity = next(item for item in payload["dimensions"] if item["dimension_code"] == "liquidity")
            self.assertEqual(liquidity["support_level"], "suppress")
            self.assertIn("抛压在增加", liquidity["conclusion"])

    def test_two_sided_sentiment_and_invalid_promotion_are_preserved(self) -> None:
        payload = V22MarketEnvironmentBuilder(ROOT).build()
        sentiment = next(item for item in payload["dimensions"] if item["dimension_code"] == "sentiment_structure")
        source = json.loads((ROOT / "data/v2/inputs/sentiment-structure.json").read_text(encoding="utf-8"))
        up_count = source["limit_up_ladder"]["filtered_count"]
        down_count = source["limit_down_ladder"]["filtered_count"]
        promotion_usable = source.get("promotion_rate", {}).get("state") == "usable"
        expected_level = (
            "suppress" if down_count > max(20, up_count * 2)
            else "support" if up_count > max(20, down_count * 2) and promotion_usable
            else "neutral"
        )
        self.assertEqual(sentiment["support_level"], expected_level)
        self.assertTrue(any("涨停" in item and "跌停" in item for item in sentiment["fact_summary"]))
        promotion_conflicts = [item for item in payload["conflicts"] if item.get("metric_name") == "晋级日期"]
        if source.get("promotion_rate", {}).get("state") == "degraded_response_date_unverified":
            self.assertTrue(any("第二天能否继续走强" in item for item in sentiment["missing_evidence"]))
            self.assertEqual(len(promotion_conflicts), 1)
            self.assertIn("不参与", promotion_conflicts[0]["resolution"])
        else:
            self.assertFalse(promotion_conflicts)

    def test_microcap_proxy_is_never_relabelled_as_small_deng_or_pure_microcap(self) -> None:
        payload = V22MarketEnvironmentBuilder(ROOT).build()
        style = next(item for item in payload["dimensions"] if item["dimension_code"] == "style_structure")
        combined = json.dumps(style, ensure_ascii=False)
        self.assertIn("小微盘宽基代理", combined)
        self.assertIn("不等于纯微盘或小登", combined)
        self.assertIn(style["support_level"], {"support", "neutral", "suppress", "unknown"})
        self.assertIn("纯微盘市场的正式数据", style["missing_evidence"])

    def test_public_output_contains_no_user_asset_fields(self) -> None:
        payload = V22MarketEnvironmentBuilder(ROOT).build()
        raw = json.dumps(payload, ensure_ascii=False)
        for forbidden in ("user_note", "user_priority", "user_intent", "source_account_id", "watchlist_source"):
            self.assertNotIn(forbidden, raw)

    def test_write_is_idempotent_and_snapshot_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.copy_fixture(root)
            built_at = datetime.fromisoformat("2026-07-18T09:00:00+08:00")
            first = V22MarketEnvironmentBuilder(root, built_at=built_at).write()
            snapshot = root / "data/v2/v22/environment-snapshots" / first["trade_date"] / f"{first['environment_snapshot_id']}.json"
            before = snapshot.read_bytes()
            second = V22MarketEnvironmentBuilder(root, built_at=datetime.fromisoformat("2026-07-18T09:05:00+08:00")).write()
            self.assertEqual(first["environment_snapshot_id"], second["environment_snapshot_id"])
            self.assertEqual(first["immutable_hash"], second["immutable_hash"])
            self.assertEqual(snapshot.read_bytes(), before)
            index = json.loads((root / "data/v2/v22/environment-snapshot-index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["snapshot_count"], 1)

    def test_complete_breadth_input_can_be_used_without_ai_fill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.copy_fixture(root)
            path = root / "data/v2/inputs/market-breadth.json"
            path.write_text(json.dumps({
                "trade_date": "2026-07-17",
                "as_of": "2026-07-17T15:00:00+08:00",
                "source_id": "verified_breadth",
                "source_name": "核验宽度样本",
                "source_url": "https://example.com/breadth",
                "universe_definition_id": "cn_a_test_v1",
                "scope": "测试A股全集",
                "advance_count": 3200,
                "decline_count": 1500,
                "flat_count": 100
            }, ensure_ascii=False), encoding="utf-8")
            payload = V22MarketEnvironmentBuilder(root).build()
            breadth = next(item for item in payload["dimensions"] if item["dimension_code"] == "market_breadth")
            self.assertEqual(breadth["support_level"], "support")
            self.assertEqual(breadth["quality_state"], "usable")
            self.assertTrue(any(ref["metric_name"] == "上涨下跌平盘家数" for ref in payload["evidence_refs"]))

    def test_verified_fallback_breadth_keeps_direction_but_is_marked_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.copy_fixture(root)
            path = root / "data/v2/inputs/market-breadth.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "trade_date": "2026-07-17",
                "as_of": "2026-07-17T15:00:00+08:00",
                "source_id": "sina_a_share_universe_live",
                "source_name": "新浪财经A股公开行情",
                "quality_state": "degraded",
                "quality_note": "主来源未返回，使用交叉核验备用源。",
                "advance_count": 3200,
                "decline_count": 1500,
                "flat_count": 100,
            }, ensure_ascii=False), encoding="utf-8")
            payload = V22MarketEnvironmentBuilder(root).build()
            breadth = next(item for item in payload["dimensions"] if item["dimension_code"] == "market_breadth")
            self.assertEqual(breadth["support_level"], "support")
            self.assertEqual(breadth["quality_state"], "degraded")
            self.assertTrue(breadth["missing_evidence"])

    def test_external_quote_after_midnight_does_not_change_a_share_trade_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.copy_fixture(root)
            path = root / "data/v2/inputs/external-market.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "trade_date": "2026-07-17",
                "as_of": "2026-07-18T05:15:59+08:00",
                "markets": [{
                    "market": "US",
                    "a_share_trade_date": "2026-07-17",
                    "as_of": "2026-07-18T05:15:59+08:00",
                    "direction": "down",
                    "mapping_eligible": True,
                }],
            }, ensure_ascii=False), encoding="utf-8")
            payload = V22MarketEnvironmentBuilder(root).build()
            self.assertEqual(payload["trade_date"], "2026-07-17")
            self.assertTrue(payload["as_of"].startswith("2026-07-17"))

    @staticmethod
    def copy_fixture(root: Path) -> None:
        for relative in (
            "config/v2-market-environment-policy.json",
            "config/v2-price-limit-rules.json",
        ):
            source = ROOT / relative
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        decision = root / "data/v2/decision-system.json"
        decision.parent.mkdir(parents=True, exist_ok=True)
        decision.write_text("{}\n", encoding="utf-8")
        breadth = root / "data/v2/inputs/market-breadth.json"
        breadth.parent.mkdir(parents=True, exist_ok=True)
        breadth.write_text(json.dumps({
            "trade_date": "2026-07-17",
            "as_of": "2026-07-17T15:00:00+08:00",
            "source_id": "isolated_test_fixture",
            "source_name": "隔离测试样本",
            "quality_state": "usable",
            "advance_count": 2000,
            "decline_count": 2000,
            "flat_count": 100,
        }, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

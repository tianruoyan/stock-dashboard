from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from v2_platform.cockpit_phase import CockpitPhaseViewBuilder


ROOT = Path(__file__).resolve().parents[1]
CHINA = ZoneInfo("Asia/Shanghai")


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class CockpitPhaseViewTests(unittest.TestCase):
    def prepare(self, root: Path) -> None:
        write(root / "config/v2-market-calendar.json", json.loads((ROOT / "config/v2-market-calendar.json").read_text(encoding="utf-8")))
        write(root / "config/v2-representative-stock-codes.json", {"codes": {"工业富联": "sh601138"}})

    def test_current_premarket_contains_required_user_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            write(root / "data/premarket.json", {
                "timestamp": "2026-07-20T09:20:00+08:00",
                "summary": "开盘前分化，等待竞价确认。",
                "us_overnight": {"conclusion": "美股科技分化。"},
                "early_asia": {"judgement": "日韩科技未共振。"},
                "market_context": {"sentiment_judgement": "情绪中性偏弱。", "benefit_themes": ["AI算力"]},
                "strong_lines": ["AI算力等待竞价扩散。"],
                "a_share_mapping": {"core_leaders": ["工业富联"]},
                "opening_plan": ["竞价扩散后再加强关注。"],
                "risk_lines": ["单股高开兑现风险。"],
            })
            payload = CockpitPhaseViewBuilder(root, now=datetime(2026, 7, 20, 9, 25, tzinfo=CHINA)).build()
            self.assertEqual(payload["stage"], "pre_market")
            self.assertEqual(payload["availability"], "ready")
            self.assertEqual(payload["sections"]["representative_stocks"][0]["code"], "sh601138")
            for key in ("external_market", "sentiment", "mainline", "representative_stocks", "action_conditions", "risks", "invalidation_conditions"):
                self.assertIn(key, payload["sections"])
            self.assertFalse(payload["guardrails"]["automatic_trading"])

    def test_current_premarket_reads_text_mapping_without_using_close_price(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            write(root / "data/premarket.json", {
                "timestamp": "2026-07-20T09:25:00+08:00",
                "summary": "竞价偏弱，等待代表股确认。",
                "a_share_mapping": {"ai_compute": "工业富联、中科曙光：等待竞价承接。"},
                "opening_plan": ["代表股与板块一起走强再关注。"],
            })
            write(root / "data/v2/inputs/representative-stock-quotes.json", {"quotes": [{
                "name": "工业富联", "code": "sh601138", "stock_change_pct": 8.8,
                "stock_quote_as_of": "2026-07-20T15:00:00+08:00", "stock_quote_source": "收盘行情",
            }]})
            payload = CockpitPhaseViewBuilder(root, now=datetime(2026, 7, 20, 9, 26, tzinfo=CHINA)).build()
            representatives = payload["sessions"]["premarket"]["sections"]["representative_stocks"]
            self.assertEqual(representatives[0]["name"], "工业富联")
            self.assertIsNone(representatives[0]["change_pct"])
            self.assertEqual(representatives[0]["quote_status_label"], "盘前行情未单独保存")
            self.assertNotIn("8.8", json.dumps(representatives, ensure_ascii=False))

    def test_stale_premarket_is_not_exposed_as_today(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            write(root / "data/premarket.json", {"timestamp": "2026-07-17T09:20:00+08:00", "summary": "旧结论不应显示"})
            payload = CockpitPhaseViewBuilder(root, now=datetime(2026, 7, 20, 9, 25, tzinfo=CHINA)).build()
            self.assertEqual(payload["availability"], "waiting_update")
            self.assertNotIn("旧结论不应显示", json.dumps(payload, ensure_ascii=False))
            self.assertFalse(payload["guardrails"]["stale_data_used_as_current"])

    def test_open_switches_to_current_intraday_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            write(root / "data/premarket.json", {"timestamp": "2026-07-20T09:20:00+08:00", "summary": "盘前结论"})
            write(root / "data/v2/v22/market-environment.json", {
                "trade_date": "2026-07-20", "as_of": "2026-07-20T09:36:00+08:00",
                "sentiment_view": {"judgment": "开盘后情绪偏弱。", "drivers": [{"evidence": "下跌家数较多。"}]},
            })
            write(root / "data/v2/v22/environment-decision.json", {
                "trade_date": "2026-07-20", "action_constraint": "等待风险收敛", "cross_market_mappings": [],
            })
            write(root / "data/v2/v22/decision-system-candidate.json", {
                "trade_date": "2026-07-20", "as_of": "2026-07-20T09:36:00+08:00", "headline": "当前等待确认",
                "current_cases": [],
                "validation_cases": [{
                    "title": "AI算力", "conclusion": "代表股尚未扩散。",
                    "representative_stocks": [{"name": "工业富联", "stock_code": "sh601138", "stock_change_pct": 0.5, "stock_quote_as_of": "2026-07-20T09:36:00+08:00", "stock_quote_source": "公开行情", "role": "中军", "basis": "当日个股行情"}],
                    "confirm_conditions": ["板块扩散"], "risk_factors": ["高开回落"], "invalidation_conditions": ["代表股转弱"],
                }],
            })
            payload = CockpitPhaseViewBuilder(root, now=datetime(2026, 7, 20, 9, 37, tzinfo=CHINA)).build()
            self.assertEqual(payload["stage"], "intraday_validation")
            self.assertEqual(payload["stage_label"], "盘中判断")
            current_view = {key: value for key, value in payload.items() if key != "sessions"}
            self.assertNotIn("盘前结论", json.dumps(current_view, ensure_ascii=False))
            self.assertEqual(payload["sessions"]["premarket"]["headline"], "盘前结论")
            self.assertEqual(payload["sessions"]["intraday"]["headline"], "当前没有值得出手的机会；等待风险收敛")
            self.assertEqual(payload["sections"]["representative_stocks"][0]["name"], "工业富联")

    def test_cross_market_result_says_direction_risk_and_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            write(root / "data/v2/v22/market-environment.json", {
                "trade_date": "2026-07-20", "as_of": "2026-07-20T10:00:00+08:00",
                "sentiment_view": {"judgment": "情绪偏弱。", "drivers": []},
            })
            write(root / "data/v2/v22/environment-decision.json", {
                "trade_date": "2026-07-20", "action_constraint": "不追高",
                "cross_market_mappings": [{
                    "origin_market": "US", "origin_direction": "down", "a_share_direction": "down",
                    "transmission_state": "confirmed", "a_share_themes": ["AI算力", "光模块/CPO"],
                    "representative_securities": [
                        {"name": "中际旭创", "change_pct": -5.2},
                        {"name": "新易盛", "change_pct": -4.8},
                    ],
                }],
            })
            payload = CockpitPhaseViewBuilder(root, now=datetime(2026, 7, 20, 10, 1, tzinfo=CHINA)).build()
            result = payload["sections"]["external_market"]["conclusion"]
            self.assertIn("美股走弱", result)
            self.assertIn("A股相关股票也在下跌", result)
            self.assertIn("这是风险信号", result)
            self.assertIn("先回避，不抄底", result)
            self.assertIn("中际旭创-5.20%", result)

    def test_daily_sessions_are_exposed_without_promoting_stale_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            write(root / "data/premarket.json", {"timestamp": "2026-07-17T09:20:00+08:00", "summary": "旧盘前"})
            write(root / "data/midday.json", {"timestamp": "2026-07-17T11:40:00+08:00", "summary": "旧午盘"})
            payload = CockpitPhaseViewBuilder(root, now=datetime(2026, 7, 20, 12, 0, tzinfo=CHINA)).build()
            self.assertEqual(set(payload["sessions"]), {"today", "premarket", "intraday", "midday", "postmarket", "evening"})
            self.assertEqual(payload["sessions"]["premarket"]["availability"], "waiting_update")
            self.assertEqual(payload["sessions"]["midday"]["availability"], "waiting_update")
            self.assertNotIn("旧盘前", json.dumps(payload, ensure_ascii=False))
            self.assertNotIn("旧午盘", json.dumps(payload, ensure_ascii=False))

    def test_current_postmarket_uses_close_sentiment_and_verified_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            write(root / "data/postmarket.json", {
                "timestamp": "2026-07-20T16:00:00+08:00",
                "review": {"one_sentence": "收盘强分化。", "summary": "消费护盘，科技承压。"},
                "market_breadth": {
                    "down_ratio_pct": 65.36,
                    "limit_structure": {"limit_up_count": 52, "limit_down_count": 74, "broken_board_count": 19},
                },
                "sentiment_indicator": {"style": "防御型强分化", "risk_level": "高", "limit_up_to_down": 0.7, "breadth": "下跌占65.36%"},
                "hotspots": [
                    {"name": "消费防御/白酒", "status": "强主线", "stocks": ["贵州茅台"], "risk": "消费权重转弱则失效。"},
                    {"name": "科技硬件", "status": "风险线", "stocks": ["工业富联"], "risk": "跌停不收缩则继续回避。"},
                ],
                "next_day_watch": ["观察跌停是否收缩。"],
                "risk": ["科技高成交核心集中下跌。"],
            })
            write(root / "data/v2/inputs/representative-stock-quotes.json", {"quotes": [
                {"name": "贵州茅台", "code": "sh600519", "stock_change_pct": 3.09, "stock_quote_as_of": "2026-07-20T15:00:00+08:00", "stock_quote_source": "双源收盘行情"},
                {"name": "工业富联", "code": "sh601138", "stock_change_pct": -6.84, "stock_quote_as_of": "2026-07-20T15:00:00+08:00", "stock_quote_source": "双源收盘行情"},
            ]})
            payload = CockpitPhaseViewBuilder(root, now=datetime(2026, 7, 20, 17, 0, tzinfo=CHINA)).build()
            postmarket = payload["sessions"]["postmarket"]
            self.assertEqual(postmarket["availability"], "ready")
            sentiment = postmarket["sections"]["sentiment"]
            self.assertIn("防御型强分化", sentiment["conclusion"])
            self.assertIn("涨停52只、跌停74只", sentiment["conclusion"])
            self.assertNotIn("待确认", sentiment["conclusion"])
            representatives = postmarket["sections"]["representative_stocks"]
            self.assertEqual({item["name"] for item in representatives}, {"贵州茅台", "工业富联"})
            self.assertTrue(all(item.get("change_pct") is not None and item.get("quote_as_of") and item.get("source") for item in representatives))

    def test_current_midday_reads_new_breadth_and_structured_quote_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            write(root / "data/midday.json", {
                "timestamp": "2026-07-20T12:10:00+08:00",
                "morning_snapshot": {
                    "indices": [{"quote_time": "20260720113000"}],
                    "breadth": {"non_st_limit_up_count": 50, "non_st_limit_down_count": 45, "broken_limit_count": 10, "comparison": "跌停增加较快，风险仍在扩大。"},
                },
                "morning_review": {"one_sentence": "上午强分化。", "main_trends": [{"name": "消费防御", "status": "偏强"}]},
                "afternoon_watch": ["下午先看跌停是否减少。"],
                "risk": ["高成交核心集中下跌。"],
                "switch_chain_special": {
                    "ranking": [{"name": "工业富联", "role": "平台", "change_pct": -7.36, "intraday_state": "靠近日内低点"}],
                    "invalidate_condition": "继续创新低则不做。",
                },
            })
            write(root / "data/v2/inputs/representative-stock-quotes.json", {"quotes": [{
                "name": "工业富联", "code": "sh601138", "stock_change_pct": -6.84,
                "stock_quote_as_of": "2026-07-20T15:00:00+08:00", "stock_quote_source": "收盘行情",
            }]})
            payload = CockpitPhaseViewBuilder(root, now=datetime(2026, 7, 20, 12, 15, tzinfo=CHINA)).build()
            midday = payload["sessions"]["midday"]
            sentiment = midday["sections"]["sentiment"]
            self.assertIn("涨停50只", sentiment["evidence"][0])
            self.assertIn("跌停45只", sentiment["evidence"][0])
            self.assertIn("炸板10只", sentiment["evidence"][0])
            self.assertNotIn("待更新", json.dumps(sentiment, ensure_ascii=False))
            stock = midday["sections"]["representative_stocks"][0]
            self.assertEqual(stock["change_pct"], -7.36)
            self.assertIn("11:30", stock["quote_as_of"])
            self.assertEqual(stock["source"], "午间11:30行情")
            self.assertIn("下午先看跌停是否减少", midday["sections"]["action_conditions"][0])

    def test_midday_direction_statuses_are_paired_with_their_themes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            write(root / "data/midday.json", {
                "timestamp": "2026-07-20T12:10:00+08:00",
                "morning_review": {"main_trends": [
                    {"name": "消费防御", "status": "偏强"},
                    {"name": "科技硬件", "status": "风险线"},
                ]},
            })
            payload = CockpitPhaseViewBuilder(root, now=datetime(2026, 7, 20, 12, 15, tzinfo=CHINA)).build()
            evidence = payload["sessions"]["midday"]["sections"]["mainline"]["evidence"]
            self.assertEqual(evidence, ["消费防御：偏强", "科技硬件：风险线"])

    def test_open_does_not_reuse_previous_trading_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            write(root / "data/v2/v22/decision-system-candidate.json", {"trade_date": "2026-07-17", "as_of": "2026-07-17T15:00:00+08:00", "headline": "旧盘中结论"})
            payload = CockpitPhaseViewBuilder(root, now=datetime(2026, 7, 20, 9, 31, tzinfo=CHINA)).build()
            self.assertEqual(payload["stage"], "intraday_validation")
            self.assertEqual(payload["availability"], "waiting_update")
            self.assertNotIn("旧盘中结论", json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from stage_fallback import (
    TZ,
    ensure_postmarket,
    execute,
    postmarket_complete,
    read_json,
    due_stage,
    refresh_hk_close,
    refresh_close_structure,
    v2_same_day_facts,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_calendar(root: Path) -> Path:
    path = root / "config" / "calendar.json"
    write_json(
        path,
        {
            "calendars": [
                {
                    "market": "CN",
                    "verification_state": "verified",
                    "valid_from": "2026-01-01",
                    "valid_to": "2026-12-31",
                    "weekend_days": [5, 6],
                    "holidays": ["2026-10-01"],
                    "extra_open_days": [],
                }
            ]
        },
    )
    return path


def index_rows(day: str = "20260901") -> list[dict]:
    return [
        {
            "name": name,
            "code": code,
            "value": value,
            "change_pct": pct,
            "pct": pct,
            "amount_yi": amount,
            "status": "已收盘",
            "quote_time": f"{day}150100",
            "source": "腾讯财经HTTP",
        }
        for name, code, value, pct, amount in (
            ("上证指数", "sh000001", 4000, 0.5, 10000),
            ("深证成指", "sz399001", 14000, 0.3, 11000),
            ("创业板指", "sz399006", 3400, -0.2, 5000),
            ("科创50", "sh000688", 1680, 1.0, 800),
            ("沪深300", "sh000300", 4600, 0.4, 5000),
        )
    ]


def industry_rows(day: str = "20260901") -> list[dict]:
    return [
        {
            "name": f"行业{index}",
            "code": f"pt{index}",
            "change_pct": float(6 - index),
            "quote_time": f"{day}150000",
            "source": "腾讯财经HTTP",
        }
        for index in range(1, 11)
    ]


def watchlist_payload(day: str = "20260901") -> dict:
    return {
        "timestamp": "2026-09-01T15:01:00+08:00",
        "quote_as_of": "2026-09-01T15:01:00+08:00",
        "source": "腾讯财经HTTP",
        "stocks": [
            {
                "name": "样本A",
                "code": "sh600000",
                "price": 10,
                "change_pct": 2.5,
                "quote_time": f"{day}150100",
                "source": "腾讯财经HTTP",
            },
            {
                "name": "样本B",
                "code": "sz000001",
                "price": 9,
                "change_pct": -1.5,
                "quote_time": f"{day}150100",
                "source": "腾讯财经HTTP",
            },
        ],
    }


class StageFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        collector = patch("stage_fallback.refresh_external", return_value=False)
        self.external = collector.start()
        self.addCleanup(collector.stop)
        structure = patch("stage_fallback.collect_structure", return_value={"breadth": None, "pools": {}, "errors": {}})
        structure.start()
        self.addCleanup(structure.stop)

    def test_completed_stage_still_checks_external_quotes(self) -> None:
        tmp, root, calendar = self.make_root()
        self.addCleanup(tmp.cleanup)
        now = datetime(2026, 9, 1, 10, 0, tzinfo=TZ)
        execute(root, now, publish=False, calendar_path=calendar)
        self.external.reset_mock()
        self.external.return_value = True
        result = execute(root, now, publish=False, calendar_path=calendar)
        self.external.assert_called_once_with(root, now)
        self.assertTrue(result["written"])
        payload = read_json(root / "data" / "premarket.json")
        self.assertEqual(payload["stage_updates"][0]["timestamp"], now.isoformat())

    def make_root(self) -> tuple[tempfile.TemporaryDirectory, Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "data").mkdir()
        (root / "logs").mkdir()
        (root / "scripts").mkdir()
        write_json(root / "config" / "watchlist.json", {"watch_only": {"stocks": []}})
        return tmp, root, write_calendar(root)

    def test_0830_replaces_stale_file_with_current_waiting_version(self) -> None:
        tmp, root, calendar = self.make_root()
        self.addCleanup(tmp.cleanup)
        write_json(root / "data" / "premarket.json", {"timestamp": "2026-08-31T09:00:00+08:00", "summary": "旧值"})
        result = execute(
            root,
            datetime(2026, 9, 1, 8, 30, tzinfo=TZ),
            stage="premarket-0830",
            publish=False,
            calendar_path=calendar,
        )
        payload = read_json(root / "data" / "premarket.json")
        self.assertTrue(result["written"])
        self.assertEqual(payload["trade_date"], "2026-09-01")
        self.assertEqual(payload["phase"], "08:30竞价前强制落盘")
        self.assertIn("等待", payload["summary"])
        self.assertNotIn("旧值", payload["summary"])

    def test_0900_catches_up_0830_then_records_increment(self) -> None:
        tmp, root, calendar = self.make_root()
        self.addCleanup(tmp.cleanup)
        execute(
            root,
            datetime(2026, 9, 1, 9, 0, tzinfo=TZ),
            stage="premarket-0900",
            publish=False,
            calendar_path=calendar,
        )
        payload = read_json(root / "data" / "premarket.json")
        self.assertEqual(payload["phase"], "09:00盘前增量更新")
        self.assertEqual([item["stage"] for item in payload["stage_updates"]], ["08:30", "09:00"])
        self.assertIn("等待", payload["hk_auction"]["sentiment"])

    def test_0900_preserves_verified_current_hk_quotes(self) -> None:
        tmp, root, calendar = self.make_root()
        self.addCleanup(tmp.cleanup)
        write_json(
            root / "data" / "premarket.json",
            {
                "timestamp": "2026-09-01T08:40:00+08:00",
                "trade_date": "2026-09-01",
                "summary": "已核验港股报价",
                "hk_auction": {
                    "window": "08:40",
                    "status": "已验证",
                    "indices": [{"name": "恒生科技", "quote_time": "20260901084000", "pct": 0.5}],
                    "sectors": [],
                    "stocks": [],
                    "sentiment": "偏强",
                },
                "stage_updates": [{"stage": "08:30", "timestamp": "2026-09-01T08:40:00+08:00"}],
            },
        )
        execute(
            root,
            datetime(2026, 9, 1, 9, 0, tzinfo=TZ),
            stage="premarket-0900",
            publish=False,
            calendar_path=calendar,
        )
        payload = read_json(root / "data" / "premarket.json")
        self.assertEqual(payload["summary"], "已核验港股报价")
        self.assertEqual(payload["hk_auction"]["indices"][0]["pct"], 0.5)
        self.assertEqual(payload["hk_auction"]["status"], "当日行情已验证")

    def test_holiday_does_not_write_market_file(self) -> None:
        tmp, root, calendar = self.make_root()
        self.addCleanup(tmp.cleanup)
        result = execute(
            root,
            datetime(2026, 10, 1, 8, 30, tzinfo=TZ),
            stage="premarket-0830",
            publish=False,
            calendar_path=calendar,
        )
        self.assertEqual(result["state"], "non_trading_day")
        self.assertFalse((root / "data" / "premarket.json").exists())

    def test_postmarket_rejects_previous_day_close_quotes(self) -> None:
        tmp, root, _ = self.make_root()
        self.addCleanup(tmp.cleanup)
        with patch("stage_fallback.fetch_indices", return_value=index_rows("20260831")):
            with self.assertRaisesRegex(RuntimeError, "不是当日收盘行情"):
                ensure_postmarket(root, datetime(2026, 9, 1, 16, 30, tzinfo=TZ), root / "v2.json")

    def test_postmarket_uses_only_current_close_and_same_day_v2(self) -> None:
        tmp, root, _ = self.make_root()
        self.addCleanup(tmp.cleanup)
        v2 = root / "v2.json"
        write_json(
            v2,
            {
                "trade_date": "2026-09-01",
                "as_of": "2026-09-01T15:10:00+08:00",
                "dimensions": [
                    {
                        "dimension_code": "market_breadth",
                        "label": "上涨与下跌家数",
                        "as_of": "2026-09-01T15:00:00+08:00",
                        "fact_summary": ["上涨3000家、下跌2200家、平盘100家。"],
                        "quality_state": "usable",
                    },
                    {
                        "dimension_code": "sentiment_structure",
                        "label": "涨跌停",
                        "as_of": "2026-09-01T15:00:00+08:00",
                        "fact_summary": ["涨停70只、跌停3只。最高连板5板。"],
                        "quality_state": "usable",
                    },
                ],
            },
        )
        with patch("stage_fallback.fetch_indices", return_value=index_rows()), patch(
            "stage_fallback.fetch_industries", return_value=industry_rows()
        ), patch("stage_fallback.fetch_watchlist_quotes", return_value=watchlist_payload()):
            self.assertTrue(ensure_postmarket(root, datetime(2026, 9, 1, 16, 30, tzinfo=TZ), v2))
        payload = read_json(root / "data" / "postmarket.json")
        self.assertTrue(postmarket_complete(payload, "2026-09-01"))
        self.assertEqual(payload["market_breadth"]["advance_count"], 3000)
        self.assertEqual(payload["market_breadth"]["limit_up_count"], 70)
        self.assertIsNone(payload["closing_auction_patch"]["snapshot_1432"])
        representative_codes = {
            item["code"] for item in payload["review"]["evidence"] if item.get("type") == "representative_stock"
        }
        self.assertEqual(representative_codes, {"sh600000", "sz000001"})

    def test_stale_v2_is_not_used(self) -> None:
        tmp, root, _ = self.make_root()
        self.addCleanup(tmp.cleanup)
        v2 = root / "v2.json"
        write_json(v2, {"trade_date": "2026-08-31", "as_of": "2026-08-31T15:00:00+08:00", "dimensions": []})
        with patch("stage_fallback.fetch_indices", return_value=index_rows()), patch(
            "stage_fallback.fetch_industries", return_value=industry_rows()
        ), patch("stage_fallback.fetch_watchlist_quotes", return_value=watchlist_payload()):
            ensure_postmarket(root, datetime(2026, 9, 1, 16, 30, tzinfo=TZ), v2)
        payload = read_json(root / "data" / "postmarket.json")
        self.assertEqual(payload["market_breadth"]["status"], "same_day_width_unavailable")
        self.assertNotIn("advance_count", payload["market_breadth"])

    def test_current_postmarket_with_preclose_quotes_is_incomplete(self) -> None:
        payload = {
            "timestamp": "2026-09-01T16:30:00+08:00",
            "trade_date": "2026-09-01",
            "index": {"a_share_indices": index_rows()},
            "market_breadth": {},
            "sentiment_indicator": {},
            "review": {"evidence": [{}]},
            "closing_auction_patch": {
                "summary": "x",
                "signals": ["x"],
                "impact": "x",
                "watch_next_day": ["x"],
            },
            "hotspots": [],
            "next_day_watch": [],
        }
        for item in payload["index"]["a_share_indices"]:
            item["quote_time"] = "20260901145600"
        self.assertFalse(postmarket_complete(payload, "2026-09-01"))

    def test_a_share_close_is_due_before_hk_close(self):
        self.assertEqual(due_stage(datetime(2026, 9, 11, 15, 9, tzinfo=TZ)), "premarket-0900")
        self.assertEqual(due_stage(datetime(2026, 9, 11, 15, 10, tzinfo=TZ)), "postmarket-1510")
        self.assertEqual(due_stage(datetime(2026, 9, 11, 16, 30, tzinfo=TZ)), "postmarket-1630")

    def test_hk_supplement_does_not_rewrite_a_share_analysis(self):
        tmp, root, _ = self.make_root()
        self.addCleanup(tmp.cleanup)
        original = {"trade_date": "2026-09-11", "timestamp": "2026-09-11T15:12:00+08:00", "review": {"summary": "当时判断"}}
        path = root / "data/postmarket.json"
        write_json(path, original)
        row = {"name": "恒生指数", "change_pct": 1, "quote_time": "2026-09-11T16:08:00+08:00"}
        with patch("stage_fallback.fetch_quotes", return_value=[[]]), patch("stage_fallback.tencent_row", return_value=row):
            self.assertTrue(refresh_hk_close(root, datetime(2026, 9, 11, 16, 30, tzinfo=TZ)))
        updated = read_json(path)
        self.assertEqual(updated["timestamp"], original["timestamp"])
        self.assertEqual(updated["review"], original["review"])
        self.assertTrue(updated["hk_close_followup"]["complete"])

    def test_hk_quote_before_close_not_called_closing(self):
        tmp, root, _ = self.make_root()
        self.addCleanup(tmp.cleanup)
        write_json(root / "data/postmarket.json", {"trade_date": "2026-09-11", "timestamp": "2026-09-11T15:12:00+08:00"})
        row = {"name": "恒生指数", "change_pct": 1, "quote_time": "2026-09-11T15:40:00+08:00"}
        with patch("stage_fallback.fetch_quotes", return_value=[[]]), patch("stage_fallback.tencent_row", return_value=row):
            self.assertFalse(refresh_hk_close(root, datetime(2026, 9, 11, 16, 30, tzinfo=TZ)))

    def test_morning_v2_statistics_cannot_be_called_close(self):
        tmp, root, _ = self.make_root()
        self.addCleanup(tmp.cleanup)
        path = root / "v2.json"
        write_json(path, {"trade_date": "2026-09-11", "as_of": "2026-09-11T15:10:00+08:00", "dimensions": [
            {"as_of": "2026-09-11T10:30:00+08:00", "fact_summary": ["上涨3000家、下跌2000家。"]}]})
        self.assertEqual(v2_same_day_facts(path, "2026-09-11")["breadth"], {})

    def test_retry_refreshes_facts_without_rewriting_judgement_time(self):
        tmp, root, _ = self.make_root()
        self.addCleanup(tmp.cleanup)
        now = datetime(2026, 9, 1, 15, 20, tzinfo=TZ)
        with patch("stage_fallback.fetch_indices", return_value=index_rows()), patch("stage_fallback.fetch_industries", return_value=industry_rows()), patch("stage_fallback.fetch_watchlist_quotes", return_value=watchlist_payload()):
            ensure_postmarket(root, now, root / "none.json")
        before = read_json(root / "data/postmarket.json")
        facts = {"collected_at": now.isoformat(), "breadth": None, "errors": {"breadth": "待更新"},
                 "pools": {"limit_up": {"count": 0, "as_of": now.isoformat()}, "limit_down": {"count": 12, "as_of": now.isoformat()}}}
        with patch("stage_fallback.collect_structure", return_value=facts):
            self.assertTrue(refresh_close_structure(root, now, force=True))
        after = read_json(root / "data/postmarket.json")
        self.assertEqual(after["timestamp"], before["timestamp"])
        self.assertEqual(after["review"], before["review"])
        self.assertEqual(after["market_breadth"]["limit_up_count"], 0)
        self.assertEqual(after["market_breadth"]["limit_down_count"], 12)


if __name__ == "__main__":
    unittest.main()

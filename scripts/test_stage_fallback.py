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


if __name__ == "__main__":
    unittest.main()

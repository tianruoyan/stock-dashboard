from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from v2_platform.market_fact_collector import V2MarketFactCollector


ROOT = Path(__file__).resolve().parents[1]
CHINA = ZoneInfo("Asia/Shanghai")


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class V22MarketFactCollectorTests(unittest.TestCase):
    def prepare(self, root: Path) -> None:
        (root / "config").mkdir(parents=True)
        (root / "config/v2-market-calendar.json").write_text(
            (ROOT / "config/v2-market-calendar.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        write(root / "local_inputs/sentiment-structure.json", {
            "trade_date": "2026-07-20",
            "as_of": "2026-07-20T10:00:00+08:00",
            "source_name": "测试涨跌停池",
            "source_url": "https://example.test/pool",
            "limit_up_ladder": {"items": [{"height": 1, "stocks": [
                {"code": "sh600001", "name": "甲", "industry": "行业A", "change_pct": 10.0},
                {"code": "sh600002", "name": "乙", "industry": "行业A", "change_pct": 10.0},
                {"code": "sz000003", "name": "丙", "industry": "行业B", "change_pct": 10.0},
            ]}]},
            "limit_down_ladder": {"items": [{"height": 1, "stocks": [
                {"code": "sz000004", "name": "丁", "industry": "行业C", "change_pct": -10.0},
                {"code": "sz000005", "name": "戊", "industry": "行业C", "change_pct": -10.0},
            ]}]},
        })

    @staticmethod
    def universe(_url: str, _params: dict[str, str]) -> dict:
        stamp = int(datetime(2026, 7, 20, 10, 0, tzinfo=CHINA).timestamp())
        rows = []
        for index in range(4100):
            pct = 1.0 if index < 2500 else (-1.0 if index < 4000 else 0.0)
            rows.append({"f2": 10.0, "f3": pct, "f6": 100_000_000 + index, "f12": str(index), "f13": 0, "f14": f"股票{index}", "f124": stamp})
        return {"data": {"total": len(rows), "diff": rows}}

    @staticmethod
    def quotes(_codes: list[str]) -> dict:
        return {
            "usIXIC": {"name": "纳斯达克", "close": 101.0, "previous_close": 100.0, "as_of": "2026-07-17 16:00:00"},
            "usNVDA": {"name": "英伟达", "close": 99.0, "previous_close": 100.0, "as_of": "2026-07-17 16:00:00"},
            "usMU": {"name": "美光", "close": 98.0, "previous_close": 100.0, "as_of": "2026-07-17 16:00:00"},
            "hkHSI": {"name": "恒生指数", "close": 101.0, "previous_close": 100.0, "as_of": "2026/07/20 10:00:00"},
            "hkHSTECH": {"name": "恒生科技", "close": 102.0, "previous_close": 100.0, "as_of": "2026/07/20 10:00:00"},
            "kr005930": {"name": "Samsung Electronics", "close": 103.0, "previous_close": 100.0, "as_of": "2026-07-20 11:00:00"},
            "kr000660": {"name": "SK hynix", "close": 106.0, "previous_close": 100.0, "as_of": "2026-07-20 11:00:00"},
        }

    def test_collects_current_public_facts_without_user_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            observed = datetime(2026, 7, 20, 10, 1, tzinfo=CHINA)
            report = V2MarketFactCollector(root, universe_fetcher=self.universe, quote_fetcher=self.quotes).collect(date(2026, 7, 20), observed_at=observed)
            breadth = json.loads((root / "local_inputs/market-breadth.json").read_text())
            liquidity = json.loads((root / "local_inputs/market-liquidity.json").read_text())
            mainline = json.loads((root / "local_inputs/mainline-structure.json").read_text())
            external = json.loads((root / "local_inputs/external-market.json").read_text())
            self.assertEqual(breadth["advance_count"], 2500)
            self.assertEqual(breadth["decline_count"], 1500)
            self.assertGreater(liquidity["total_turnover"], 0)
            self.assertEqual(mainline["themes"][0]["theme"], "行业A")
            self.assertTrue(all(item["a_share_trade_date"] == "2026-07-20" for item in external["markets"]))
            self.assertEqual({item["market"] for item in external["markets"]}, {"US", "HK", "KR"})
            self.assertEqual(external["quality_state"], "usable")
            kr = next(item for item in external["markets"] if item["market"] == "KR")
            self.assertEqual([item["name"] for item in kr["samples"]], ["三星电子", "SK海力士"])
            self.assertFalse(report["guardrails"]["user_assets_read"])
            self.assertFalse(report["guardrails"]["missing_facts_ai_filled"])

    def test_rejects_cross_date_universe_quotes(self) -> None:
        def stale(_url: str, _params: dict[str, str]) -> dict:
            stamp = int(datetime(2026, 7, 17, 15, 0, tzinfo=CHINA).timestamp())
            return {"data": {"diff": [{"f2": 10, "f3": 1, "f6": 1, "f124": stamp}] * 4100}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            with self.assertRaisesRegex(ValueError, "trade_date_mismatch|not_cross_verified"):
                V2MarketFactCollector(root, universe_fetcher=stale, quote_fetcher=self.quotes).collect(
                    date(2026, 7, 20), observed_at=datetime(2026, 7, 20, 10, 1, tzinfo=CHINA)
                )

    def test_sina_fallback_is_date_verified_and_explicitly_degraded(self) -> None:
        def unavailable(_url: str, _params: dict[str, str]) -> dict:
            return {"data": {"diff": []}}

        def sina() -> list[dict]:
            return [
                {"代码": f"{index:06d}", "名称": f"股票{index}", "最新价": 10, "涨跌幅": 1, "成交额": 1000000, "时间戳": "10:01:00"}
                for index in range(4100)
            ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            write(root / "data/intraday.json", {"indices": [
                {"quote_time": f"2026072010000{index}", "name": f"指数{index}"}
                for index in range(5)
            ]})
            report = V2MarketFactCollector(
                root,
                universe_fetcher=unavailable,
                sina_universe_fetcher=sina,
                quote_fetcher=self.quotes,
            ).collect(date(2026, 7, 20), observed_at=datetime(2026, 7, 20, 10, 2, tzinfo=CHINA))
            breadth = json.loads((root / "local_inputs/market-breadth.json").read_text())
            self.assertEqual(breadth["source_id"], "sina_a_share_universe_live")
            self.assertEqual(breadth["as_of"], "2026-07-20T10:01:00+08:00")
            self.assertEqual(breadth["quality_state"], "degraded")
            self.assertEqual(report["state"], "degraded")

    def test_transient_source_failure_retains_only_same_day_verified_facts(self) -> None:
        def unavailable(_url: str, _params: dict[str, str]) -> dict:
            raise RuntimeError("temporary source failure")

        def sina_unavailable() -> list[dict]:
            raise RuntimeError("temporary fallback failure")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            for filename in (
                "market-breadth.json",
                "market-liquidity.json",
                "mainline-structure.json",
                "external-market.json",
            ):
                write(root / "local_inputs" / filename, {
                    "trade_date": "2026-07-20",
                    "as_of": "2026-07-20T10:00:00+08:00",
                    "quality_state": "usable",
                    "marker": filename,
                })
            report = V2MarketFactCollector(
                root,
                universe_fetcher=unavailable,
                sina_universe_fetcher=sina_unavailable,
                quote_fetcher=self.quotes,
            ).collect(date(2026, 7, 20), observed_at=datetime(2026, 7, 20, 10, 2, tzinfo=CHINA))
            self.assertEqual(report["state"], "waiting_update")
            self.assertTrue(report["guardrails"]["retained_previous_same_day_facts"])
            self.assertTrue(all(item["quality_state"] == "waiting_update" for item in report["outputs"]))
            preserved = json.loads((root / "local_inputs/market-breadth.json").read_text())
            self.assertEqual(preserved["marker"], "market-breadth.json")

    def test_transient_source_failure_never_retains_previous_day_facts(self) -> None:
        def unavailable(_url: str, _params: dict[str, str]) -> dict:
            raise RuntimeError("temporary source failure")

        def sina_unavailable() -> list[dict]:
            raise RuntimeError("temporary fallback failure")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            for filename in (
                "market-breadth.json",
                "market-liquidity.json",
                "mainline-structure.json",
                "external-market.json",
            ):
                write(root / "local_inputs" / filename, {
                    "trade_date": "2026-07-17",
                    "as_of": "2026-07-17T15:00:00+08:00",
                    "quality_state": "usable",
                })
            with self.assertRaisesRegex(ValueError, "sina_universe_trade_date_not_cross_verified"):
                V2MarketFactCollector(
                    root,
                    universe_fetcher=unavailable,
                    sina_universe_fetcher=sina_unavailable,
                    quote_fetcher=self.quotes,
                ).collect(date(2026, 7, 20), observed_at=datetime(2026, 7, 20, 10, 2, tzinfo=CHINA))


if __name__ == "__main__":
    unittest.main()

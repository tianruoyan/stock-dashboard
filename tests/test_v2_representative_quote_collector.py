from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v2_platform.representative_quote_collector import (
    V2RepresentativeQuoteCollector,
    canonical_representative_code,
)


class V2RepresentativeQuoteCollectorTests(unittest.TestCase):
    def test_formal_observation_names_are_always_requested_for_quote_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir(parents=True)
            (root / "data" / "v2").mkdir(parents=True)
            (root / "data" / "alert.json").write_text(json.dumps({"alerts": []}), encoding="utf-8")
            (root / "data" / "opportunity-watch.json").write_text(json.dumps({"items": []}), encoding="utf-8")
            (root / "config" / "v2-formal-observation.json").write_text(
                json.dumps({"stocks": [
                    {"name": "端侧样本", "code": "sh688001", "formal_observation_requested": True},
                    {"name": "未启用样本", "code": "sh688002", "formal_observation_requested": False},
                ]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "data" / "v2" / "stock-pool.json").write_text(
                json.dumps({"stocks": [
                    {"name": "端侧样本", "code": "sh688001"},
                    {"name": "未启用样本", "code": "sh688002"},
                ]}, ensure_ascii=False),
                encoding="utf-8",
            )

            def fetcher(codes: list[str]) -> dict[str, dict[str, object]]:
                self.assertEqual(codes, ["sh688001"])
                return {"sh688001": {"close": 10.5, "previous_close": 10.0, "as_of": "20260805150000"}}

            payload = V2RepresentativeQuoteCollector(root, quote_fetcher=fetcher).collect()
            self.assertEqual([item["name"] for item in payload["quotes"]], ["端侧样本"])

    def test_repairs_bse_code_mislabelled_as_shenzhen(self) -> None:
        self.assertEqual(canonical_representative_code("sz920690"), "bj920690")
        self.assertEqual(canonical_representative_code("920690"), "bj920690")

    def test_bse_quote_does_not_poison_secondary_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "v2").mkdir(parents=True)
            (root / "data" / "alert.json").write_text(
                json.dumps({"alerts": [{"leaders": [{"name": "捷众科技"}, {"name": "测试股份"}]}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "data" / "opportunity-watch.json").write_text(json.dumps({"items": []}), encoding="utf-8")
            (root / "data" / "v2" / "stock-pool.json").write_text(
                json.dumps({"stocks": [
                    {"name": "捷众科技", "code": "sz920690"},
                    {"name": "测试股份", "code": "sh600000"},
                ]}, ensure_ascii=False),
                encoding="utf-8",
            )

            def primary(codes):
                self.assertEqual(codes, ["bj920690", "sh600000"])
                return {
                    code: {"close": 10.5, "previous_close": 10.0, "as_of": "20260727100000"}
                    for code in codes
                }

            def secondary(codes):
                return {
                    code: {"close": 10.5, "previous_close": 10.0, "as_of": "2026-07-27 10:00:00"}
                    for code in codes if not code.startswith("bj")
                }

            payload = V2RepresentativeQuoteCollector(
                root,
                quote_fetcher=primary,
                secondary_quote_fetcher=secondary,
            ).collect()
            by_name = {item["name"]: item for item in payload["quotes"]}
            self.assertEqual(by_name["捷众科技"]["code"], "bj920690")
            self.assertFalse(by_name["捷众科技"]["cross_source_verified"])
            self.assertTrue(by_name["测试股份"]["cross_source_verified"])

    def test_collects_real_stock_fields_without_reusing_theme_pct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "v2").mkdir(parents=True)
            (root / "data" / "alert.json").write_text(
                json.dumps({"alerts": [{"leaders": [{"name": "测试股份"}]}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "data" / "opportunity-watch.json").write_text(
                json.dumps({"items": [{"watch_stocks": ["测试股份"]}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "data" / "v2" / "stock-pool.json").write_text(
                json.dumps({"stocks": [{"name": "测试股份", "code": "sh600000"}]}, ensure_ascii=False),
                encoding="utf-8",
            )

            def fetcher(codes: list[str]) -> dict[str, dict[str, object]]:
                self.assertEqual(codes, ["sh600000"])
                return {
                    "sh600000": {
                        "name": "测试股份",
                        "close": 10.5,
                        "previous_close": 10.0,
                        "as_of": "20260710150000",
                    }
                }

            payload = V2RepresentativeQuoteCollector(root, quote_fetcher=fetcher).collect()
            quote = payload["quotes"][0]
            self.assertEqual(quote["code"], "sh600000")
            self.assertEqual(quote["stock_change_pct"], 5.0)
            self.assertEqual(quote["stock_quote_as_of"], "2026-07-10T15:00:00+08:00")
            self.assertEqual(quote["stock_quote_source"], "腾讯财经公开行情")

    def test_supports_hong_kong_quote_time(self) -> None:
        from v2_platform.representative_quote_collector import quote_time_iso

        self.assertEqual(quote_time_iso("2026/07/10 16:08:41"), "2026-07-10T16:08:41+08:00")

    def test_dual_source_confirmation_keeps_both_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "v2").mkdir(parents=True)
            (root / "data" / "alert.json").write_text(
                json.dumps({"alerts": [{"leaders": [{"name": "测试股份"}]}]}, ensure_ascii=False), encoding="utf-8"
            )
            (root / "data" / "opportunity-watch.json").write_text(json.dumps({"items": []}), encoding="utf-8")
            (root / "data" / "v2" / "stock-pool.json").write_text(
                json.dumps({"stocks": [{"name": "测试股份", "code": "sh600000"}]}, ensure_ascii=False), encoding="utf-8"
            )

            primary = lambda codes: {codes[0]: {"close": 10.5, "previous_close": 10.0, "as_of": "20260727100000", "amount_yi": 2.4}}
            secondary = lambda codes: {codes[0]: {"close": 10.5, "previous_close": 10.0, "as_of": "2026-07-27 10:00:01", "amount_yi": 2.5}}
            payload = V2RepresentativeQuoteCollector(
                root, quote_fetcher=primary, secondary_quote_fetcher=secondary
            ).collect()
            row = payload["quotes"][0]
            self.assertTrue(row["cross_source_verified"])
            self.assertEqual(row["stock_quote_verification"], "两路行情一致")
            self.assertEqual(row["stock_quote_source"], "腾讯与富途行情交叉核验")
            self.assertIsNotNone(row["source_observations"]["primary"])
            self.assertIsNotNone(row["source_observations"]["secondary"])

    def test_conflicting_secondary_quote_does_not_replace_primary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "v2").mkdir(parents=True)
            (root / "data" / "alert.json").write_text(
                json.dumps({"alerts": [{"leaders": [{"name": "测试股份"}]}]}, ensure_ascii=False), encoding="utf-8"
            )
            (root / "data" / "opportunity-watch.json").write_text(json.dumps({"items": []}), encoding="utf-8")
            (root / "data" / "v2" / "stock-pool.json").write_text(
                json.dumps({"stocks": [{"name": "测试股份", "code": "sh600000"}]}, ensure_ascii=False), encoding="utf-8"
            )
            primary = lambda codes: {codes[0]: {"close": 10.5, "previous_close": 10.0, "as_of": "20260727100000"}}
            secondary = lambda codes: {codes[0]: {"close": 11.5, "previous_close": 10.0, "as_of": "2026-07-27 10:00:00"}}
            payload = V2RepresentativeQuoteCollector(
                root, quote_fetcher=primary, secondary_quote_fetcher=secondary
            ).collect()
            row = payload["quotes"][0]
            self.assertFalse(row["cross_source_verified"])
            self.assertEqual(row["close"], 10.5)
            self.assertEqual(row["stock_quote_verification"], "两路行情存在差异")

    def test_unmapped_theme_labels_are_not_requested_as_stocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "v2").mkdir(parents=True)
            (root / "data" / "alert.json").write_text(
                json.dumps({"alerts": [{"leaders": [{"name": "光模块/CPO"}, {"name": "测试股份"}]}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "data" / "opportunity-watch.json").write_text(
                json.dumps({"items": [{"watch_stocks": ["上午情绪判为退潮型"]}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "data" / "v2" / "stock-pool.json").write_text(
                json.dumps({"stocks": [{"name": "测试股份", "code": "sh600000"}]}, ensure_ascii=False),
                encoding="utf-8",
            )

            def fetcher(codes: list[str]) -> dict[str, dict[str, object]]:
                self.assertEqual(codes, ["sh600000"])
                return {
                    "sh600000": {
                        "close": 10.5,
                        "previous_close": 10.0,
                        "as_of": "20260713150000",
                    }
                }

            payload = V2RepresentativeQuoteCollector(root, quote_fetcher=fetcher).collect()
            self.assertEqual(payload["candidate_count"], 3)
            self.assertEqual(payload["requested_count"], 1)
            self.assertEqual(payload["quote_count"], 1)
            self.assertEqual(payload["missing"], [])
            self.assertEqual(
                {item["name"] for item in payload["excluded_unmapped"]},
                {"光模块/CPO", "上午情绪判为退潮型"},
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from v2_platform.futu_quote_provider import FutuQuoteProvider, from_futu_code, to_futu_code


class FakeContext:
    def __init__(self, **_: object) -> None:
        self.closed = False

    def get_market_snapshot(self, codes: list[str]):
        return 0, pd.DataFrame([
            {
                "code": code,
                "name": "测试股份",
                "update_time": "2026-07-27 10:00:00",
                "last_price": 10.5,
                "prev_close_price": 10.0,
                "volume": 123400,
                "turnover": 250000000,
                "high_price": 10.7,
                "low_price": 9.9,
                "sec_status": "NORMAL",
            }
            for code in codes
        ])

    def close(self) -> None:
        self.closed = True


class ZeroTurnoverContext(FakeContext):
    def get_market_snapshot(self, codes: list[str]):
        result, data = super().get_market_snapshot(codes)
        data["turnover"] = 0
        return result, data


class RejectOneSymbolContext(FakeContext):
    def get_market_snapshot(self, codes: list[str]):
        if "SZ.000002" in codes:
            return -1, "未知股票 000002"
        return super().get_market_snapshot(codes)


class FutuQuoteProviderTests(unittest.TestCase):
    def test_code_mapping_is_explicit(self) -> None:
        self.assertEqual(to_futu_code("sh600519"), "SH.600519")
        self.assertEqual(to_futu_code("sz000001"), "SZ.000001")
        self.assertEqual(to_futu_code("hk00700"), "HK.00700")
        self.assertIsNone(to_futu_code("bj920000"))
        self.assertEqual(from_futu_code("SH.600519"), "sh600519")

    def test_snapshot_fields_are_normalized_without_trading_calls(self) -> None:
        provider = FutuQuoteProvider(
            context_factory=FakeContext,
            clock=lambda: datetime(2026, 7, 27, 10, 0, 1, tzinfo=timezone(timedelta(hours=8))),
        )
        quotes = provider.fetch_quotes(["sh600519", "sz000001", "hk00700"])
        self.assertEqual(set(quotes), {"sh600519", "sz000001", "hk00700"})
        self.assertEqual(quotes["sh600519"]["close"], 10.5)
        self.assertEqual(quotes["sh600519"]["previous_close"], 10.0)
        self.assertEqual(quotes["sh600519"]["amount_yi"], 2.5)
        self.assertEqual(quotes["sh600519"]["as_of"], "2026-07-27T10:00:00+08:00")
        self.assertEqual(quotes["sh600519"]["source_label"], "富途 OpenD A股LV1行情")
        self.assertEqual(quotes["hk00700"]["source_label"], "富途 OpenD 港股LV2行情")

    def test_future_placeholder_is_not_treated_as_live_quote(self) -> None:
        provider = FutuQuoteProvider(
            context_factory=FakeContext,
            clock=lambda: datetime(2026, 7, 27, 9, 0, 0, tzinfo=timezone(timedelta(hours=8))),
        )
        self.assertEqual(provider.fetch_quotes(["sh600519"]), {})

    def test_even_small_future_timestamp_beyond_clock_skew_is_rejected(self) -> None:
        provider = FutuQuoteProvider(
            context_factory=FakeContext,
            clock=lambda: datetime(2026, 7, 27, 9, 59, 54, tzinfo=timezone(timedelta(hours=8))),
        )
        self.assertEqual(provider.fetch_quotes(["sh600519"]), {})

    def test_zero_turnover_placeholder_is_not_treated_as_live_quote(self) -> None:
        provider = FutuQuoteProvider(
            context_factory=ZeroTurnoverContext,
            clock=lambda: datetime(2026, 7, 27, 10, 0, 1, tzinfo=timezone(timedelta(hours=8))),
        )
        self.assertEqual(provider.fetch_quotes(["sh600519"]), {})

    def test_bad_symbol_is_isolated_without_discarding_valid_batch_members(self) -> None:
        provider = FutuQuoteProvider(
            context_factory=RejectOneSymbolContext,
            clock=lambda: datetime(2026, 7, 27, 10, 0, 1, tzinfo=timezone(timedelta(hours=8))),
        )
        quotes = provider.fetch_quotes(["sh600519", "sz000002", "sz000001"])
        self.assertEqual(set(quotes), {"sh600519", "sz000001"})


if __name__ == "__main__":
    unittest.main()

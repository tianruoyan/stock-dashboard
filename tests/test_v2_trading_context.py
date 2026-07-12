from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from v2_platform.trading_context import resolve_cn_trading_context


ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))


class TradingContextTests(unittest.TestCase):
    def test_weekend_uses_friday_market_date_and_monday_target(self) -> None:
        context = resolve_cn_trading_context(ROOT, datetime(2026, 7, 12, 19, 0, tzinfo=TZ), ["2026-07-10", "2026-07-11"])
        self.assertEqual(context.market_date.isoformat(), "2026-07-10")
        self.assertEqual(context.target_trade_date.isoformat(), "2026-07-13")
        self.assertEqual(context.phase, "closed")

    def test_open_day_remains_current_target(self) -> None:
        context = resolve_cn_trading_context(ROOT, datetime(2026, 7, 13, 10, 0, tzinfo=TZ), ["2026-07-10"])
        self.assertEqual(context.market_date.isoformat(), "2026-07-10")
        self.assertEqual(context.target_trade_date.isoformat(), "2026-07-13")
        self.assertEqual(context.phase, "morning")


if __name__ == "__main__":
    unittest.main()

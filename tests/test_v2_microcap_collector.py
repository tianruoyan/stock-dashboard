from __future__ import annotations

import unittest
from datetime import date

from v2_platform.microcap_collector import V2MicrocapCollector


class V2MicrocapCollectorTests(unittest.TestCase):
    def test_quote_is_parsed_and_change_is_recomputed(self) -> None:
        fields = ["中证2000", "3276.7552", "3277.0738", "3272.9877", "3358.7835", "3272.9766"] + ["0"] * 24 + ["2026-07-10", "16:09:58", "00", ""]
        raw = f'var hq_str_si932000="{",".join(fields)}";'
        item = V2MicrocapCollector(fetcher=lambda: raw).collect(date(2026, 7, 10))["observations"][0]
        self.assertEqual(item["close"], 3272.9877)
        self.assertEqual(item["change_pct"], -0.1247)
        self.assertEqual(item["source_id"], "sina_csi2000_secondary_proxy")

    def test_wrong_trade_date_fails_closed(self) -> None:
        fields = ["中证2000", "1", "100", "101", "102", "99"] + ["0"] * 24 + ["2026-07-09", "15:00:00", "00", ""]
        raw = f'var hq_str_si932000="{",".join(fields)}";'
        with self.assertRaisesRegex(ValueError, "trade_date_mismatch"):
            V2MicrocapCollector(fetcher=lambda: raw).collect(date(2026, 7, 10))


if __name__ == "__main__":
    unittest.main()

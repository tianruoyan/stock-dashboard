from __future__ import annotations

import unittest

from v2_platform.quote_consistency import compare_quotes


def quote(price: float, previous: float = 10.0, as_of: str = "2026-07-27T10:00:00+08:00") -> dict:
    return {"close": price, "previous_close": previous, "as_of": as_of}


class QuoteConsistencyTests(unittest.TestCase):
    def test_equal_quotes_are_cross_verified(self) -> None:
        result = compare_quotes(quote(10.5), quote(10.5, as_of="2026-07-27 10:00:01"))
        self.assertEqual(result["state"], "confirmed")
        self.assertTrue(result["cross_source_verified"])
        self.assertEqual(result["user_state"], "两路行情一致")

    def test_small_price_and_time_difference_is_tolerated(self) -> None:
        result = compare_quotes(
            quote(10.5, as_of="2026-07-27T10:00:00+08:00"),
            quote(10.504, as_of="2026-07-27T10:00:19+08:00"),
        )
        self.assertEqual(result["state"], "confirmed")
        self.assertLessEqual(result["metrics"]["quote_time_gap_seconds"], 20)
        self.assertLessEqual(result["metrics"]["price_difference_pct"], 0.05)

    def test_time_gap_beyond_tolerance_does_not_confirm(self) -> None:
        result = compare_quotes(
            quote(10.5, as_of="2026-07-27T10:00:00+08:00"),
            quote(10.504, as_of="2026-07-27T10:00:30+08:00"),
        )
        self.assertEqual(result["state"], "time_unaligned")
        self.assertFalse(result["cross_source_verified"])

    def test_exact_match_allows_small_source_delivery_delay(self) -> None:
        result = compare_quotes(
            quote(10.5, as_of="2026-07-27T10:00:00+08:00"),
            quote(10.5, as_of="2026-07-27T10:00:31+08:00"),
        )
        self.assertEqual(result["state"], "confirmed")
        self.assertTrue(result["cross_source_verified"])

    def test_exact_match_delay_still_has_a_hard_limit(self) -> None:
        result = compare_quotes(
            quote(10.5, as_of="2026-07-27T10:00:00+08:00"),
            quote(10.5, as_of="2026-07-27T10:01:01+08:00"),
        )
        self.assertEqual(result["state"], "time_unaligned")
        self.assertFalse(result["cross_source_verified"])

    def test_same_day_close_quotes_use_final_values_instead_of_request_time(self) -> None:
        result = compare_quotes(
            quote(10.5, as_of="2026-07-27T15:05:45+08:00"),
            quote(10.5, as_of="2026-07-27T15:00:00+08:00"),
        )
        self.assertEqual(result["state"], "confirmed")
        self.assertTrue(result["cross_source_verified"])
        self.assertEqual(result["metrics"]["comparison_basis"], "same_day_close")

    def test_same_day_close_price_conflict_remains_a_conflict(self) -> None:
        result = compare_quotes(
            quote(10.5, as_of="2026-07-27T15:05:45+08:00"),
            quote(10.8, as_of="2026-07-27T15:00:00+08:00"),
        )
        self.assertEqual(result["state"], "conflict")
        self.assertFalse(result["cross_source_verified"])

    def test_hong_kong_closing_auction_is_not_treated_as_closed_before_1610(self) -> None:
        result = compare_quotes(
            quote(148.4, previous=149.8, as_of="2026-07-27T16:02:05+08:00"),
            quote(148.6, previous=149.8, as_of="2026-07-27T16:07:58+08:00"),
            {"market_close_time": "16:10:00"},
        )
        self.assertEqual(result["state"], "time_unaligned")
        self.assertFalse(result["cross_source_verified"])

    def test_single_source_is_never_called_verified(self) -> None:
        result = compare_quotes(quote(10.5), None)
        self.assertEqual(result["state"], "primary_only")
        self.assertFalse(result["cross_source_verified"])

    def test_price_conflict_is_not_averaged(self) -> None:
        result = compare_quotes(quote(10.5), quote(10.8))
        self.assertEqual(result["state"], "conflict")
        self.assertEqual(result["selected_source"], "primary")
        self.assertFalse(result["cross_source_verified"])

    def test_cross_date_quotes_cannot_confirm_each_other(self) -> None:
        result = compare_quotes(quote(10.5), quote(10.5, as_of="2026-07-24T15:00:00+08:00"))
        self.assertEqual(result["state"], "date_mismatch")
        self.assertFalse(result["cross_source_verified"])


if __name__ == "__main__":
    unittest.main()

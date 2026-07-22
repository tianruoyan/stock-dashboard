#!/usr/bin/env python3
import unittest

from import_ths_watchlist import merge_watchlist


def watchlist(*stocks):
    return {"watch_only": {"stocks": [dict(stock) for stock in stocks]}}


class TongHuaShunWatchlistSafetyTests(unittest.TestCase):
    def test_default_partial_sync_never_removes_user_asset(self):
        payload = watchlist(
            {"code": "sh688008", "name": "澜起科技", "tags": ["用户关注"]},
            {"code": "sz300033", "name": "同花顺", "tags": ["用户关注"]},
        )

        added, updated, removed = merge_watchlist(
            payload,
            [{"code": "sh688008", "name": "澜起科技"}],
        )

        self.assertEqual(added, 0)
        self.assertGreaterEqual(updated, 0)
        self.assertEqual(removed, 0)
        self.assertEqual(
            {item["code"] for item in payload["watch_only"]["stocks"]},
            {"sh688008", "sz300033"},
        )

    def test_confirmed_complete_sync_can_remove_absent_asset(self):
        payload = watchlist(
            {"code": "sh688008", "name": "澜起科技", "tags": ["用户关注"]},
            {"code": "sz300033", "name": "同花顺", "tags": ["用户关注"]},
        )

        added, updated, removed = merge_watchlist(
            payload,
            [{"code": "sh688008", "name": "澜起科技"}],
            allow_removal=True,
        )

        self.assertEqual(added, 0)
        self.assertGreaterEqual(updated, 0)
        self.assertEqual(removed, 1)
        self.assertEqual(
            [item["code"] for item in payload["watch_only"]["stocks"]],
            ["sh688008"],
        )


if __name__ == "__main__":
    unittest.main()

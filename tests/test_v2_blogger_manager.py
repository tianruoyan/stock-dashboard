from __future__ import annotations

import unittest

import server


class BloggerManagerTests(unittest.TestCase):
    def test_validates_and_normalizes_private_account(self) -> None:
        payload = server.validate_blogger_payload({"accounts": [{"platform": "xiaohongshu", "display_name": "产业观察", "url": "https://www.xiaohongshu.com/user/profile/example", "note": "半导体", "enabled": True}]})
        self.assertEqual(payload["accounts"][0]["platform"], "xiaohongshu")
        self.assertTrue(payload["accounts"][0]["id"].startswith("source_"))
        self.assertNotIn("token", payload["accounts"][0])

    def test_rejects_non_http_url_and_duplicates(self) -> None:
        with self.assertRaises(ValueError):
            server.validate_blogger_payload({"accounts": [{"platform": "weibo", "display_name": "x", "url": "javascript:alert(1)"}]})
        with self.assertRaises(ValueError):
            server.validate_blogger_payload({"accounts": [
                {"platform": "weibo", "display_name": "a", "url": "https://weibo.com/u/1"},
                {"platform": "weibo", "display_name": "b", "url": "https://weibo.com/u/1"},
            ]})


if __name__ == "__main__":
    unittest.main()

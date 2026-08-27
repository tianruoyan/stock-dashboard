from __future__ import annotations

import unittest
from pathlib import Path

from v2_platform.publishing import PublishPolicy


ROOT = Path(__file__).resolve().parents[1]


class V22PrivatePublishingTests(unittest.TestCase):
    def test_private_user_assets_and_raw_sync_remain_hard_blocked(self) -> None:
        policy = PublishPolicy.load(ROOT / "config/v2-publish-policy.json")
        self.assertTrue(policy.hard_blocks_path(".v2_private/user-assets.sqlite3"))
        self.assertTrue(policy.hard_blocks_path("data/v2/raw-sync/ths.json"))
        self.assertTrue({"user_note", "user_priority", "user_intent"}.issubset(set(policy.sensitive_json_keys)))


if __name__ == "__main__":
    unittest.main()

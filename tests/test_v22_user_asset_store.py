from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from v2_platform.publishing import PublishPolicy
from v2_platform.user_asset_store import UserAssetStore
from v2_platform.user_asset_views import build_user_asset_read_projection, build_user_asset_storage_health
from v2_platform.user_assets import UserAssetService, WatchlistSourcePolicy


ROOT = Path(__file__).resolve().parents[1]


class V22UserAssetStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.private_root = Path(self.temp.name)
        self.store = UserAssetStore(self.private_root)
        self.store.initialize()
        policy = WatchlistSourcePolicy.load(ROOT / "config/v2-watchlist-source-policy.json")
        self.service = UserAssetService(self.store, policy)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_initialization_is_idempotent_and_empty(self) -> None:
        first = self.store.integrity_summary()
        second = self.store.initialize()
        self.assertEqual(
            first["schema_versions"],
            ["0001_user_assets", "0002_user_asset_change_log_guard", "0003_watchlist_shadow"],
        )
        self.assertEqual(first["logical_hash"], second["logical_hash"])
        self.assertEqual(second["user_asset_count"], 0)
        self.assertEqual(second["integrity"], "ok")

    def test_security_identity_dedupes_by_market_and_ticker_not_name(self) -> None:
        first = self.service.register_security(
            market="CN_SSE",
            ticker="688981",
            normalized_code="sh688981",
            display_name="中芯国际",
        )
        second = self.service.register_security(
            market="CN_SSE",
            ticker="688981",
            normalized_code="sh688981",
            display_name="中芯国际新名称",
        )
        self.assertEqual(first, second)
        self.assertEqual(self.store.table_count("security_master"), 1)
        with self.store.connection(readonly=True) as connection:
            row = connection.execute("SELECT display_name FROM security_master").fetchone()
        self.assertEqual(row["display_name"], "中芯国际新名称")

    def test_backup_and_restore_keep_schema_counts_and_logical_hash(self) -> None:
        self.service.register_security(
            market="CN_SZSE",
            ticker="000001",
            normalized_code="sz000001",
            display_name="平安银行",
        )
        backup = self.private_root / "backup" / "user-assets.backup"
        backed_up = self.store.backup_to(backup)
        restored = UserAssetStore.restore_backup(
            self.private_root,
            backup,
            self.private_root / "restore" / "user-assets.sqlite3",
        )
        self.assertEqual(backed_up["logical_hash"], restored.integrity_summary()["logical_hash"])
        self.assertEqual(backed_up["schema_versions"], restored.schema_versions())
        self.assertEqual(backed_up["security_count"], restored.table_count("security_master"))

    def test_empty_read_projection_is_chinese_and_hides_engineering_details(self) -> None:
        projection = build_user_asset_read_projection(self.private_root)
        health = build_user_asset_storage_health(self.private_root)
        self.assertEqual(projection["状态"], "空结构已就绪")
        self.assertEqual(projection["数量"], 0)
        self.assertEqual(projection["用户自选"], [])
        rendered = str({"projection": projection, "health": health})
        self.assertNotIn("sqlite", rendered.lower())
        self.assertNotIn("user_watchlist_asset", rendered)
        self.assertNotIn(str(self.store.path), rendered)

    def test_private_database_and_backups_are_ignored_and_publish_blocked(self) -> None:
        for relative in (
            ".v2_private/user-assets.sqlite3",
            ".v2_private/user-assets.sqlite3-wal",
            ".v2_private/user-assets-20260718.backup",
        ):
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", relative],
                cwd=ROOT,
            )
            self.assertEqual(ignored.returncode, 0, relative)
        policy = PublishPolicy.load(ROOT / "config/v2-publish-policy.json")
        self.assertTrue(policy.hard_blocks_path(".v2_private/user-assets.sqlite3"))
        self.assertTrue(policy.hard_blocks_path(".v2_private/user-assets-20260718.backup"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from v2_platform.user_asset_store import UserAssetStore
from v2_platform.watchlist_migration import WatchlistMigrationAuditBuilder
from v2_platform.watchlist_sync import ShadowSource, build_shadow_result, record_shadow_result


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class V22WatchlistMigrationTests(unittest.TestCase):
    def make_root(self, base: Path) -> tuple[Path, UserAssetStore]:
        root = base / "repo"
        (root / "config").mkdir(parents=True)
        (root / "data/v2").mkdir(parents=True)
        (root / "scripts").mkdir(parents=True)
        payload = {
            "watch_only": {"stocks": [
                {"code": "sh600000", "name": "浦发银行", "source": "同花顺自选导入", "tags": ["同花顺自选"]},
                {"code": "sz000001", "name": "平安银行", "source": "同花顺自选导入", "tags": ["同花顺自选"]},
            ]},
            "small_deng": {"stocks": [
                {"code": "sz000001", "name": "平安银行", "source": "风格样本"},
                {"code": "sz300001", "name": "特锐德", "source": "风格样本"},
            ]},
            "old_deng": {"stocks": [{"code": "sh600000", "name": "浦发银行", "source": "风格样本"}]},
        }
        (root / "config/watchlist.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        (root / "data/v2/stock-pool.json").write_text('{"stocks":[]}', encoding="utf-8")
        for name in ("import_ths_watchlist.py", "sync_ths_watchlist.sh", "com.stock-dashboard.ths-watchlist.plist"):
            (root / "scripts" / name).write_text("unchanged", encoding="utf-8")
        store = UserAssetStore(root)
        store.initialize()
        source = ShadowSource(
            watchlist_source="ths_cloud",
            source_mode="full",
            records=({"code": "sh600000"}, {"code": "sh600010"}),
            source_as_of="2026-07-18T10:00:00+08:00",
            observed_at="2026-07-18T10:00:01+08:00",
            source_identity_hash="sha256:test-account",
            completeness_claimed=False,
        )
        result = build_shadow_result(payload["watch_only"]["stocks"], source)
        record_shadow_result(store, result)
        return root, store

    def test_preview_splits_user_and_style_relationships_without_applying(self) -> None:
        with TemporaryDirectory() as tmp:
            root, store = self.make_root(Path(tmp))
            public, private = WatchlistMigrationAuditBuilder(root, store).build()
        self.assertEqual(public["counts"]["watch_only"], 2)
        self.assertEqual(public["counts"]["small_deng"], 2)
        self.assertEqual(public["counts"]["old_deng"], 1)
        self.assertEqual(public["counts"]["watch_small_overlap"], 1)
        self.assertEqual(public["counts"]["currently_observed_candidates"], 1)
        self.assertEqual(public["counts"]["newly_observed_candidates"], 1)
        self.assertFalse(public["guardrails"]["migration_applied"])
        self.assertFalse(public["guardrails"]["style_pool_created_user_assets"])
        overlapping = next(item for item in private["records"] if item["identity"].get("normalized_code") == "sz000001")
        self.assertIn("用户来源候选", overlapping["relationships"])
        self.assertIn("小登风格样本候选", overlapping["relationships"])
        self.assertEqual(overlapping["user_priority_candidate"], "normal")
        self.assertEqual(overlapping["user_priority_origin"], "system_default_not_user_setting")
        self.assertEqual(overlapping["user_intent_candidate"], "unset")
        self.assertEqual(overlapping["user_note"], "")
        self.assertIsNone(overlapping["user_confirmed_at"])
        self.assertFalse(overlapping["applied"])

    def test_public_audit_does_not_publish_private_securities_or_notes(self) -> None:
        with TemporaryDirectory() as tmp:
            root, store = self.make_root(Path(tmp))
            public, _private = WatchlistMigrationAuditBuilder(root, store).build()
        rendered = json.dumps(public, ensure_ascii=False)
        self.assertNotIn("sh600000", rendered)
        self.assertNotIn("浦发银行", rendered)
        self.assertNotIn("test-account", rendered)
        self.assertNotIn("user_note", rendered)
        self.assertFalse(public["privacy"]["private_codes_published"])

    def test_current_workspace_inventory_matches_frozen_e2_evidence(self) -> None:
        public, _private = WatchlistMigrationAuditBuilder(ROOT).build()
        self.assertEqual(public["counts"]["watch_only"], 34)
        self.assertEqual(public["counts"]["small_deng"], 67)
        self.assertEqual(public["counts"]["old_deng"], 22)
        self.assertEqual(public["counts"]["watch_small_overlap"], 9)

    def test_check_and_apply_guard_leave_legacy_watchlist_unchanged(self) -> None:
        watchlist = ROOT / "config/watchlist.json"
        before = digest(watchlist)
        checked = subprocess.run(
            [sys.executable, "scripts/migrate_v2_user_assets.py", "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        blocked = subprocess.run(
            [sys.executable, "scripts/migrate_v2_user_assets.py", "--apply"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(blocked.returncode, 3)
        self.assertIn("不允许应用", blocked.stderr)
        self.assertEqual(before, digest(watchlist))

    def test_shadow_task_is_present_but_disabled_and_page_is_user_facing(self) -> None:
        plist = (ROOT / "scripts/com.stock-dashboard.v2-ths-shadow.plist").read_text(encoding="utf-8")
        page = (ROOT / "v2-stock-pool.html").read_text(encoding="utf-8")
        script = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn("<key>Disabled</key>", plist)
        self.assertIn("<true/>", plist)
        self.assertIn("自选同步对照", page)
        self.assertIn("同步对照说明", page)
        self.assertIn("查看股票池规则", page)
        self.assertNotIn("缺失只表示本次未观察到", script)
        self.assertNotIn("watchlist_sync_batch", page)
        self.assertNotIn("source_identity_hash", page)


if __name__ == "__main__":
    unittest.main()

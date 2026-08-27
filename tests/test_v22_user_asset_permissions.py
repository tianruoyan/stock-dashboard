from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from v2_platform.user_asset_store import UserAssetStore
from v2_platform.user_assets import (
    UserAssetInvariantError,
    UserAssetPermissionError,
    UserAssetService,
    WatchlistSourcePolicy,
    now_iso,
)


ROOT = Path(__file__).resolve().parents[1]


class V22UserAssetPermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.store = UserAssetStore(Path(self.temp.name))
        self.store.initialize()
        self.policy = WatchlistSourcePolicy.load(ROOT / "config/v2-watchlist-source-policy.json")
        self.service = UserAssetService(self.store, self.policy)
        self.security_id = self.service.register_security(
            market="CN_SSE",
            ticker="688981",
            normalized_code="sh688981",
            display_name="中芯国际",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_manual_asset(self) -> str:
        return self.service.create_user_asset(
            user_id="local_user",
            security_id=self.security_id,
            actor_type="user",
            evidence_id="user_action_add_1",
            source="manual_add",
            source_id="manual_688981",
            user_confirmed_at="2026-07-18T10:00:00+08:00",
            user_confirmed_evidence_id="user_action_add_1",
        )

    def test_ai_and_style_model_cannot_create_user_asset(self) -> None:
        for actor in ("ai", "style_model"):
            with self.subTest(actor=actor):
                with self.assertRaises(UserAssetPermissionError):
                    self.service.create_user_asset(
                        user_id="local_user",
                        security_id=self.security_id,
                        actor_type=actor,
                        evidence_id="forbidden",
                        source="manual_add",
                    )

    def test_database_trigger_rejects_ai_even_if_direct_write_is_attempted(self) -> None:
        current_time = now_iso()
        with self.store.connection() as connection:
            connection.execute(
                "INSERT INTO asset_write_authorization(request_id, actor_type, operation, evidence_id, created_at) VALUES ('req_ai', 'ai', 'asset_create', 'ai_attempt', ?)",
                (current_time,),
            )
            with self.assertRaises(sqlite3.IntegrityError) as context:
                connection.execute(
                    """
                    INSERT INTO user_watchlist_asset(
                        user_asset_id, user_id, security_id, membership_state,
                        user_priority, created_at, updated_at, revision,
                        last_request_id
                    ) VALUES ('ua_ai', 'local_user', ?, 'active', 'normal', ?, ?, 1, 'req_ai')
                    """,
                    (self.security_id, current_time, current_time),
                )
        self.assertIn("user_asset_actor_forbidden", str(context.exception))
        self.assertEqual(self.store.table_count("user_watchlist_asset"), 0)

    def test_database_trigger_requires_change_log_for_direct_user_update(self) -> None:
        asset_id = self.create_manual_asset()
        current_time = now_iso()
        with self.store.connection() as connection:
            connection.execute(
                "INSERT INTO asset_write_authorization(request_id, actor_type, operation, evidence_id, created_at) VALUES ('req_user_bypass', 'user', 'asset_update', 'user_edit', ?)",
                (current_time,),
            )
            with self.assertRaises(sqlite3.IntegrityError) as context:
                connection.execute(
                    "UPDATE user_watchlist_asset SET user_note='绕过日志', revision=2, last_request_id='req_user_bypass' WHERE user_asset_id=?",
                    (asset_id,),
                )
        self.assertIn("user_asset_change_log_required", str(context.exception))

    def test_user_confirmed_time_requires_evidence(self) -> None:
        with self.assertRaises(UserAssetInvariantError):
            self.service.create_user_asset(
                user_id="local_user",
                security_id=self.security_id,
                actor_type="user",
                evidence_id="user_action_add_2",
                source="manual_add",
                user_confirmed_at="2026-07-18T10:00:00+08:00",
            )

    def test_user_fields_update_requires_user_actor_and_appends_log(self) -> None:
        asset_id = self.create_manual_asset()
        with self.assertRaises(UserAssetPermissionError):
            self.service.update_user_fields(
                asset_id,
                {"user_priority": "high", "user_note": "AI不得覆盖"},
                actor_type="ai",
                evidence_id="ai_attempt",
                change_reason="AI尝试",
                expected_revision=1,
            )
        revision = self.service.update_user_fields(
            asset_id,
            {"user_priority": "high", "user_intent": "research", "user_note": "AI服务器核心观察"},
            actor_type="user",
            evidence_id="user_edit_1",
            change_reason="用户修改关注设置",
            expected_revision=1,
        )
        self.assertEqual(revision, 2)
        with self.store.connection(readonly=True) as connection:
            row = connection.execute(
                "SELECT user_priority, user_intent, user_note, revision FROM user_watchlist_asset WHERE user_asset_id=?",
                (asset_id,),
            ).fetchone()
            log_count = int(connection.execute(
                "SELECT COUNT(*) FROM user_asset_change_log WHERE user_asset_id=?",
                (asset_id,),
            ).fetchone()[0])
        self.assertEqual(dict(row), {"user_priority": "high", "user_intent": "research", "user_note": "AI服务器核心观察", "revision": 2})
        self.assertEqual(log_count, 4)

    def test_delete_requires_evidence_and_all_user_sources_closed(self) -> None:
        asset_id = self.create_manual_asset()
        with self.assertRaises(UserAssetInvariantError):
            self.service.confirm_asset_deleted(
                asset_id,
                actor_type="user",
                evidence_id="",
                expected_revision=1,
            )
        with self.assertRaises(UserAssetInvariantError):
            self.service.confirm_asset_deleted(
                asset_id,
                actor_type="user",
                evidence_id="user_delete_1",
                expected_revision=1,
            )
        with self.store.connection(readonly=True) as connection:
            source_link_id = str(connection.execute(
                "SELECT source_link_id FROM watchlist_source_link WHERE user_asset_id=?",
                (asset_id,),
            ).fetchone()[0])
        self.service.mark_source_deleted(
            source_link_id,
            actor_type="user",
            evidence_id="user_delete_1",
        )
        revision = self.service.confirm_asset_deleted(
            asset_id,
            actor_type="user",
            evidence_id="user_delete_1",
            expected_revision=1,
        )
        self.assertEqual(revision, 2)
        with self.store.connection(readonly=True) as connection:
            row = connection.execute(
                "SELECT membership_state, delete_evidence_id FROM user_watchlist_asset WHERE user_asset_id=?",
                (asset_id,),
            ).fetchone()
        self.assertEqual(row["membership_state"], "deleted_confirmed")
        self.assertEqual(row["delete_evidence_id"], "user_delete_1")

    def test_user_confirmed_time_cannot_be_rewritten(self) -> None:
        asset_id = self.create_manual_asset()
        with self.assertRaises(UserAssetInvariantError):
            self.service.update_user_fields(
                asset_id,
                {"user_confirmed_at": "2026-07-19T10:00:00+08:00"},
                actor_type="user",
                evidence_id="user_edit_time",
                change_reason="尝试改写确认时间",
                expected_revision=1,
            )

    def test_source_priority_order_is_versioned_and_not_user_priority(self) -> None:
        manual = self.policy.rule("manual_add")
        broker = self.policy.rule("broker_sync")
        ths = self.policy.rule("ths_cloud")
        self.assertGreater(manual.source_priority, broker.source_priority)
        self.assertGreater(broker.source_priority, ths.source_priority)
        self.assertNotIn("system_candidate", self.policy.payload["sources"])
        self.assertNotIn("research_import", self.policy.payload["sources"])

    def test_synced_sources_remain_disabled_during_e1(self) -> None:
        for source in ("ths_cloud", "broker_sync"):
            with self.subTest(source=source):
                with self.assertRaises(UserAssetPermissionError):
                    self.service.create_user_asset(
                        user_id="local_user",
                        security_id=self.security_id,
                        actor_type="sync_service",
                        evidence_id="sync_disabled",
                        source=source,
                    )


if __name__ == "__main__":
    unittest.main()

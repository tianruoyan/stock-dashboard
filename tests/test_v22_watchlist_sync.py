from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from v2_platform.user_asset_store import UserAssetStore
from v2_platform.user_assets import UserAssetService, WatchlistSourcePolicy
from v2_platform.watchlist_sync import (
    ShadowSource,
    build_shadow_result,
    latest_recorded_shadow,
    normalize_code,
    record_shadow_result,
)


ROOT = Path(__file__).resolve().parents[1]


def rows(count: int) -> list[dict[str, str]]:
    return [
        {"code": f"sh{600000 + index:06d}", "name": f"样本{index}"}
        for index in range(count)
    ]


def source(
    records: list[dict[str, str]],
    *,
    complete: bool = False,
    stale: bool = False,
    identity: str | None = "sha256:account-a",
    error: str | None = None,
) -> ShadowSource:
    return ShadowSource(
        watchlist_source="ths_cloud",
        source_mode="full",
        records=tuple(records),
        source_as_of="2026-07-18T10:00:00+08:00",
        observed_at="2026-07-18T10:00:01+08:00",
        source_identity_hash=identity,
        completeness_claimed=complete,
        stale=stale,
        fetch_error=error,
    )


class V22WatchlistSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = UserAssetStore(self.root)
        self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_code_normalization_keeps_markets_separate(self) -> None:
        self.assertEqual(normalize_code("600000"), "sh600000")
        self.assertEqual(normalize_code("000001"), "sz000001")
        self.assertEqual(normalize_code("830001"), "bj830001")
        self.assertEqual(normalize_code("hk00981"), "hk00981")
        self.assertEqual(normalize_code("hk6809"), "hk06809")
        self.assertEqual(normalize_code("invalid"), "")

    def test_complete_input_builds_diff_but_never_applies(self) -> None:
        existing = rows(3)
        observed = [existing[0], existing[1], {"code": "sh600010", "name": "新增"}]
        result = build_shadow_result(existing, source(observed, complete=True))
        self.assertEqual(result.batch_state, "success")
        self.assertTrue(result.completeness_verified)
        self.assertEqual((result.added_count, result.missing_count), (1, 1))
        self.assertFalse(result.deletion_allowed)
        self.assertFalse(result.migration_applied)
        self.assertTrue(all(item["applied"] is False for item in result.events))
        self.assertNotIn("confirmed_delete", {item["event_type"] for item in result.events})

    def test_current_ten_vs_existing_thirty_four_triggers_bulk_delete_guard(self) -> None:
        result = build_shadow_result(rows(34), source(rows(10), complete=False))
        self.assertEqual(result.batch_state, "partial")
        self.assertEqual(result.user_state, "完整性待确认")
        self.assertEqual(result.missing_count, 24)
        self.assertIn("批量删除保护", result.user_message)
        self.assertFalse(result.completeness_verified)

    def test_empty_partial_failed_stale_and_account_change_never_allow_delete(self) -> None:
        scenarios = [
            source([], complete=True),
            source(rows(3), complete=False),
            source(rows(3), complete=True, stale=True),
            source([], error="读取失败"),
            source(rows(3), complete=True, identity="sha256:account-b"),
        ]
        for index, current in enumerate(scenarios):
            with self.subTest(index=index):
                result = build_shadow_result(
                    rows(3),
                    current,
                    previous_source_identity_hash="sha256:account-a",
                )
                self.assertFalse(result.deletion_allowed)
                self.assertTrue(all(item["applied"] is False for item in result.events))
                self.assertNotIn("confirmed_delete", {item["event_type"] for item in result.events})

    def test_recording_same_source_is_idempotent_and_source_id_stays_missing(self) -> None:
        result = build_shadow_result(rows(4), source(rows(3), complete=False))
        first = record_shadow_result(self.store, result)
        second = record_shadow_result(self.store, result)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        with self.store.connection(readonly=True) as connection:
            batch_count = int(connection.execute("SELECT COUNT(*) FROM watchlist_sync_batch").fetchone()[0])
            event_count = int(connection.execute("SELECT COUNT(*) FROM watchlist_sync_event").fetchone()[0])
            applied_count = int(connection.execute("SELECT COUNT(*) FROM watchlist_sync_event WHERE applied=1").fetchone()[0])
            fake_source_ids = int(connection.execute("SELECT COUNT(*) FROM watchlist_shadow_snapshot WHERE source_id IS NOT NULL").fetchone()[0])
        self.assertEqual(batch_count, 1)
        self.assertEqual(event_count, len(result.events))
        self.assertEqual(applied_count, 0)
        self.assertEqual(fake_source_ids, 0)
        self.assertEqual(len(latest_recorded_shadow(self.store)["records"]), 3)

    def test_latest_recorded_shadow_ignores_newer_rejected_fallback(self) -> None:
        usable = build_shadow_result(rows(3), source(rows(2), complete=False))
        record_shadow_result(self.store, usable)
        rejected_source = ShadowSource(
            watchlist_source="ths_cloud",
            source_mode="file_fallback",
            records=tuple(rows(1)),
            source_as_of="2026-07-05T00:00:00+08:00",
            observed_at="2026-07-19T20:00:00+08:00",
            source_identity_hash=None,
            completeness_claimed=False,
            stale=True,
        )
        rejected = build_shadow_result(rows(3), rejected_source)
        self.assertEqual(rejected.batch_state, "rejected")
        record_shadow_result(self.store, rejected)
        latest = latest_recorded_shadow(self.store)
        self.assertEqual(latest["batch"]["sync_batch_id"], usable.batch_id)
        self.assertEqual(len(latest["records"]), 2)

    def test_shadow_record_does_not_modify_user_owned_fields(self) -> None:
        policy = WatchlistSourcePolicy.load(ROOT / "config/v2-watchlist-source-policy.json")
        service = UserAssetService(self.store, policy)
        security_id = service.register_security(
            market="CN_SSE",
            ticker="600000",
            normalized_code="sh600000",
            display_name="浦发银行",
        )
        asset_id = service.create_user_asset(
            user_id="local_user",
            security_id=security_id,
            actor_type="user",
            evidence_id="manual_add_evidence",
            source="manual_add",
            user_priority="high",
            user_intent="research",
            user_note="用户原始备注",
        )
        with self.store.connection(readonly=True) as connection:
            before = dict(connection.execute(
                "SELECT membership_state, user_priority, user_intent, user_note, revision FROM user_watchlist_asset WHERE user_asset_id=?",
                (asset_id,),
            ).fetchone())
        record_shadow_result(self.store, build_shadow_result(rows(2), source(rows(1))))
        with self.store.connection(readonly=True) as connection:
            after = dict(connection.execute(
                "SELECT membership_state, user_priority, user_intent, user_note, revision FROM user_watchlist_asset WHERE user_asset_id=?",
                (asset_id,),
            ).fetchone())
        self.assertEqual(before, after)

    def test_public_summary_contains_counts_but_no_codes_names_or_account(self) -> None:
        result = build_shadow_result(rows(3), source(rows(2)))
        rendered = json.dumps(result.public_summary(), ensure_ascii=False)
        self.assertNotIn("sh600000", rendered)
        self.assertNotIn("样本0", rendered)
        self.assertNotIn("account-a", rendered)
        self.assertIn("是否已应用", rendered)


if __name__ == "__main__":
    unittest.main()

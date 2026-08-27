from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2_platform.user_asset_store import UserAssetStore


USER_ACTORS = {"user", "sync_service"}
AI_ACTORS = {"ai", "style_model"}
USER_FIELDS = {"user_priority", "user_intent", "user_note", "user_confirmed_at"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class UserAssetPermissionError(PermissionError):
    pass


class UserAssetInvariantError(ValueError):
    pass


class UserAssetRevisionError(UserAssetInvariantError):
    pass


@dataclass(frozen=True)
class SourceRule:
    name: str
    source_priority: int
    writer_actor: str
    enabled: bool


class WatchlistSourcePolicy:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    @classmethod
    def load(cls, path: Path) -> "WatchlistSourcePolicy":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise UserAssetInvariantError("自选来源规则无效")
        return cls(value)

    def rule(self, source: str) -> SourceRule:
        raw = (self.payload.get("sources") or {}).get(source)
        if not isinstance(raw, dict):
            raise UserAssetInvariantError("该来源不能建立用户资产")
        return SourceRule(
            name=source,
            source_priority=int(raw.get("source_priority") or 0),
            writer_actor=str(raw.get("writer_actor") or ""),
            enabled=raw.get("enabled") is not False,
        )


class UserAssetService:
    """Command boundary for user-owned fields.

    Nothing calls this service automatically in E1. The methods exist so the
    permission and transaction invariants can be tested before real migration.
    """

    def __init__(self, store: UserAssetStore, source_policy: WatchlistSourcePolicy) -> None:
        self.store = store
        self.source_policy = source_policy

    @classmethod
    def from_root(cls, root: Path, store: UserAssetStore | None = None) -> "UserAssetService":
        root = root.resolve()
        return cls(
            store or UserAssetStore(root),
            WatchlistSourcePolicy.load(root / "config/v2-watchlist-source-policy.json"),
        )

    @staticmethod
    def _require_user_actor(actor_type: str) -> None:
        if actor_type not in USER_ACTORS:
            raise UserAssetPermissionError("AI和风格模型没有用户资产写权限")

    @staticmethod
    def _translate_integrity_error(exc: sqlite3.IntegrityError) -> UserAssetInvariantError:
        message = str(exc)
        if "revision" in message:
            return UserAssetRevisionError("用户资产已被更新，请重新读取后再提交")
        return UserAssetInvariantError(message)

    @staticmethod
    def _authorize(
        connection: sqlite3.Connection,
        *,
        request_id: str,
        actor_type: str,
        operation: str,
        evidence_id: str,
        occurred_at: str,
    ) -> None:
        connection.execute(
            "INSERT INTO asset_write_authorization(request_id, actor_type, operation, evidence_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (request_id, actor_type, operation, evidence_id, occurred_at),
        )

    def register_security(
        self,
        *,
        market: str,
        ticker: str,
        normalized_code: str,
        display_name: str,
        security_type: str = "stock",
        currency: str | None = "CNY",
        listing_state: str = "active",
        identity_source: str = "test_or_manual_identity",
    ) -> str:
        market = str(market).strip()
        ticker = str(ticker).strip()
        normalized_code = str(normalized_code).strip().lower()
        display_name = str(display_name).strip()
        if not all((market, ticker, normalized_code, display_name)):
            raise UserAssetInvariantError("证券身份字段不完整")
        security_id = "sec_" + hashlib.sha256(f"{market}|{ticker}".encode("utf-8")).hexdigest()[:20]
        current_time = now_iso()
        try:
            with self.store.connection() as connection:
                connection.execute(
                    """
                    INSERT INTO security_master(
                        security_id, market, ticker, normalized_code, display_name,
                        security_type, currency, listing_state, identity_source,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(market, ticker) DO UPDATE SET
                        normalized_code=excluded.normalized_code,
                        display_name=excluded.display_name,
                        security_type=excluded.security_type,
                        currency=excluded.currency,
                        listing_state=excluded.listing_state,
                        identity_source=excluded.identity_source,
                        updated_at=excluded.updated_at
                    """,
                    (
                        security_id,
                        market,
                        ticker,
                        normalized_code,
                        display_name,
                        security_type,
                        currency,
                        listing_state,
                        identity_source,
                        current_time,
                        current_time,
                    ),
                )
                row = connection.execute(
                    "SELECT security_id FROM security_master WHERE market=? AND ticker=?",
                    (market, ticker),
                ).fetchone()
        except sqlite3.IntegrityError as exc:
            raise self._translate_integrity_error(exc) from exc
        return str(row["security_id"])

    def create_user_asset(
        self,
        *,
        user_id: str,
        security_id: str,
        actor_type: str,
        evidence_id: str,
        source: str,
        source_id: str | None = None,
        user_priority: str = "normal",
        user_intent: str | None = None,
        user_note: str | None = None,
        user_confirmed_at: str | None = None,
        user_confirmed_evidence_id: str | None = None,
        occurred_at: str | None = None,
    ) -> str:
        self._require_user_actor(actor_type)
        rule = self.source_policy.rule(source)
        if not rule.enabled:
            raise UserAssetPermissionError("该同步来源在E1阶段尚未启用")
        if actor_type != rule.writer_actor:
            raise UserAssetPermissionError("当前身份不能写入该用户来源")
        if user_confirmed_at and not user_confirmed_evidence_id:
            raise UserAssetInvariantError("用户确认时间必须有可核验依据")
        occurred_at = occurred_at or now_iso()
        user_asset_id = new_id("ua")
        asset_request = new_id("req")
        source_request = new_id("req")
        source_link_id = new_id("src")
        try:
            with self.store.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._authorize(
                    connection,
                    request_id=asset_request,
                    actor_type=actor_type,
                    operation="asset_create",
                    evidence_id=evidence_id,
                    occurred_at=occurred_at,
                )
                connection.execute(
                    """
                    INSERT INTO user_watchlist_asset(
                        user_asset_id, user_id, security_id, membership_state,
                        user_priority, user_intent, user_note, user_confirmed_at,
                        user_confirmed_evidence_id, created_at, updated_at, revision,
                        last_request_id
                    ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        user_asset_id,
                        user_id,
                        security_id,
                        user_priority,
                        user_intent,
                        user_note,
                        user_confirmed_at,
                        user_confirmed_evidence_id,
                        occurred_at,
                        occurred_at,
                        asset_request,
                    ),
                )
                self._authorize(
                    connection,
                    request_id=source_request,
                    actor_type=actor_type,
                    operation="source_create",
                    evidence_id=evidence_id,
                    occurred_at=occurred_at,
                )
                connection.execute(
                    """
                    INSERT INTO watchlist_source_link(
                        source_link_id, user_asset_id, watchlist_source,
                        source_priority, source_id, source_state, first_seen_at,
                        last_seen_at, sync_time, last_request_id
                    ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                    """,
                    (
                        source_link_id,
                        user_asset_id,
                        source,
                        rule.source_priority,
                        source_id,
                        occurred_at,
                        occurred_at,
                        occurred_at,
                        source_request,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO user_asset_change_log(
                        change_id, user_asset_id, field_name, before_value,
                        after_value, actor_type, change_reason, evidence_id,
                        occurred_at, request_id
                    ) VALUES (?, ?, 'membership_state', NULL, 'active', ?, ?, ?, ?, ?)
                    """,
                    (new_id("chg"), user_asset_id, actor_type, "用户确认建立关注", evidence_id, occurred_at, asset_request),
                )
        except sqlite3.IntegrityError as exc:
            raise self._translate_integrity_error(exc) from exc
        return user_asset_id

    def update_user_fields(
        self,
        user_asset_id: str,
        changes: dict[str, Any],
        *,
        actor_type: str,
        evidence_id: str,
        change_reason: str,
        expected_revision: int,
        actor_id: str | None = None,
    ) -> int:
        self._require_user_actor(actor_type)
        unknown = set(changes) - USER_FIELDS
        if unknown or not changes:
            raise UserAssetInvariantError("只允许修改已登记的用户字段")
        current_time = now_iso()
        request_id = new_id("req")
        try:
            with self.store.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM user_watchlist_asset WHERE user_asset_id=?",
                    (user_asset_id,),
                ).fetchone()
                if row is None:
                    raise UserAssetInvariantError("用户资产不存在")
                if int(row["revision"]) != expected_revision:
                    raise UserAssetRevisionError("用户资产已被更新，请重新读取后再提交")
                changes = {field: value for field, value in changes.items() if row[field] != value}
                if not changes:
                    return expected_revision
                if "user_confirmed_at" in changes:
                    if row["user_confirmed_at"] is not None and changes["user_confirmed_at"] != row["user_confirmed_at"]:
                        raise UserAssetInvariantError("用户确认时间记录后不可改写")
                    if changes["user_confirmed_at"] is not None and not evidence_id:
                        raise UserAssetInvariantError("用户确认时间必须有可核验依据")
                self._authorize(
                    connection,
                    request_id=request_id,
                    actor_type=actor_type,
                    operation="asset_update",
                    evidence_id=evidence_id,
                    occurred_at=current_time,
                )
                for field, value in changes.items():
                    before = row[field]
                    connection.execute(
                        """
                        INSERT INTO user_asset_change_log(
                            change_id, user_asset_id, field_name, before_value,
                            after_value, actor_type, actor_id, change_reason,
                            evidence_id, occurred_at, request_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_id("chg"),
                            user_asset_id,
                            field,
                            None if before is None else str(before),
                            None if value is None else str(value),
                            actor_type,
                            actor_id,
                            change_reason,
                            evidence_id,
                            current_time,
                            request_id,
                        ),
                    )
                assignments = ", ".join(f"{field}=?" for field in changes)
                values = list(changes.values())
                if "user_confirmed_at" in changes and changes["user_confirmed_at"] is not None:
                    assignments += ", user_confirmed_evidence_id=?"
                    values.append(evidence_id)
                values.extend([current_time, request_id, user_asset_id, expected_revision])
                cursor = connection.execute(
                    f"UPDATE user_watchlist_asset SET {assignments}, updated_at=?, revision=revision+1, last_request_id=? WHERE user_asset_id=? AND revision=?",
                    values,
                )
                if cursor.rowcount != 1:
                    raise UserAssetRevisionError("用户资产已被更新，请重新读取后再提交")
        except sqlite3.IntegrityError as exc:
            raise self._translate_integrity_error(exc) from exc
        return expected_revision + 1

    def mark_source_deleted(
        self,
        source_link_id: str,
        *,
        actor_type: str,
        evidence_id: str,
    ) -> None:
        self._require_user_actor(actor_type)
        current_time = now_iso()
        request_id = new_id("req")
        try:
            with self.store.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT watchlist_source FROM watchlist_source_link WHERE source_link_id=?",
                    (source_link_id,),
                ).fetchone()
                if row is None:
                    raise UserAssetInvariantError("用户来源不存在")
                rule = self.source_policy.rule(str(row["watchlist_source"]))
                if actor_type != rule.writer_actor:
                    raise UserAssetPermissionError("当前身份不能关闭该用户来源")
                self._authorize(
                    connection,
                    request_id=request_id,
                    actor_type=actor_type,
                    operation="source_update",
                    evidence_id=evidence_id,
                    occurred_at=current_time,
                )
                connection.execute(
                    "UPDATE watchlist_source_link SET source_state='deleted_confirmed', delete_evidence_id=?, last_request_id=?, last_seen_at=?, sync_time=? WHERE source_link_id=?",
                    (evidence_id, request_id, current_time, current_time, source_link_id),
                )
        except sqlite3.IntegrityError as exc:
            raise self._translate_integrity_error(exc) from exc

    def confirm_asset_deleted(
        self,
        user_asset_id: str,
        *,
        actor_type: str,
        evidence_id: str,
        expected_revision: int,
    ) -> int:
        self._require_user_actor(actor_type)
        if not evidence_id:
            raise UserAssetInvariantError("删除用户资产必须有用户或云端确认依据")
        current_time = now_iso()
        request_id = new_id("req")
        try:
            with self.store.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                active_count = int(connection.execute(
                    "SELECT COUNT(*) FROM watchlist_source_link WHERE user_asset_id=? AND source_state='active'",
                    (user_asset_id,),
                ).fetchone()[0])
                if active_count:
                    raise UserAssetInvariantError("仍有有效用户来源，不能删除用户资产")
                self._authorize(
                    connection,
                    request_id=request_id,
                    actor_type=actor_type,
                    operation="asset_delete",
                    evidence_id=evidence_id,
                    occurred_at=current_time,
                )
                connection.execute(
                    """
                    INSERT INTO user_asset_change_log(
                        change_id, user_asset_id, field_name, before_value,
                        after_value, actor_type, change_reason, evidence_id,
                        occurred_at, request_id
                    ) VALUES (?, ?, 'membership_state', 'active', 'deleted_confirmed', ?, ?, ?, ?, ?)
                    """,
                    (new_id("chg"), user_asset_id, actor_type, "用户或来源确认删除", evidence_id, current_time, request_id),
                )
                cursor = connection.execute(
                    """
                    UPDATE user_watchlist_asset
                    SET membership_state='deleted_confirmed', deleted_at=?,
                        delete_evidence_id=?, updated_at=?, revision=revision+1,
                        last_request_id=?
                    WHERE user_asset_id=? AND revision=?
                    """,
                    (current_time, evidence_id, current_time, request_id, user_asset_id, expected_revision),
                )
                if cursor.rowcount != 1:
                    raise UserAssetRevisionError("用户资产已被更新，请重新读取后再提交")
        except sqlite3.IntegrityError as exc:
            raise self._translate_integrity_error(exc) from exc
        return expected_revision + 1

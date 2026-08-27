from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from v2_platform.user_asset_store import UserAssetStore


MAX_REMOVAL_RATIO = 0.40


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def stable_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def normalize_code(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if re.fullmatch(r"hk\d{4,5}", value):
        return "hk" + value[2:].zfill(5)
    match = re.fullmatch(r"(sh|sz|bj)[.:_-]?(\d{6})", value)
    if match:
        return match.group(1) + match.group(2)
    digits = re.sub(r"\D", "", value)
    if len(digits) != 6:
        return ""
    if digits.startswith(("5", "6")):
        return "sh" + digits
    if digits.startswith(("0", "1", "3")):
        return "sz" + digits
    if digits.startswith(("4", "8", "9")):
        return "bj" + digits
    return ""


def identity_candidate(code: str, name: str = "") -> dict[str, Any]:
    code = normalize_code(code)
    if not code:
        return {"state": "needs_review", "code": "", "name": str(name or "")}
    prefix, ticker = code[:2], code[2:]
    if prefix == "hk":
        market = "HK_HKEX"
        security_type = "stock"
    elif prefix == "sh":
        market = "CN_SSE"
        security_type = "etf" if ticker.startswith("5") else "stock"
    elif prefix == "sz":
        market = "CN_SZSE"
        security_type = "etf" if ticker.startswith("1") else "stock"
    elif prefix == "bj":
        market = "CN_BSE"
        security_type = "stock"
    else:
        return {"state": "needs_review", "code": code, "name": str(name or "")}
    return {
        "state": "mapped",
        "security_candidate_id": "sec_candidate_" + hashlib.sha256(f"{market}|{ticker}".encode("utf-8")).hexdigest()[:20],
        "market": market,
        "ticker": ticker,
        "normalized_code": code,
        "display_name": str(name or ""),
        "security_type": security_type,
    }


def normalize_records(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for raw in records:
        code = normalize_code(raw.get("code"))
        if not code:
            conflicts.append({"type": "invalid_code", "raw_code": str(raw.get("code") or "")})
            continue
        name = str(raw.get("name") or "").strip()
        item = {
            "code": code,
            "name": name,
            "source_id": str(raw.get("source_id") or "").strip() or None,
        }
        existing = normalized.get(code)
        if existing and existing.get("name") and name and existing["name"] != name:
            conflicts.append({"type": "name_conflict", "code": code})
            continue
        if existing:
            if not existing.get("name") and name:
                existing["name"] = name
            if existing.get("source_id") is None and item.get("source_id"):
                existing["source_id"] = item["source_id"]
            continue
        normalized[code] = item
    return [normalized[key] for key in sorted(normalized)], conflicts


@dataclass(frozen=True)
class ShadowSource:
    watchlist_source: str
    source_mode: str
    records: tuple[dict[str, Any], ...]
    source_as_of: str | None
    observed_at: str
    source_identity_hash: str | None = None
    completeness_claimed: bool = False
    stale: bool = False
    fetch_error: str | None = None


@dataclass(frozen=True)
class ShadowSyncResult:
    batch_id: str
    batch_state: str
    user_state: str
    user_message: str
    completeness_verified: bool
    completeness_reason: str
    records: tuple[dict[str, Any], ...]
    conflicts: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]
    source_mode: str
    source_as_of: str | None
    observed_at: str
    source_identity_hash: str | None
    raw_content_hash: str
    existing_count: int
    added_count: int
    unchanged_count: int
    missing_count: int
    conflict_count: int
    deletion_allowed: bool = False
    migration_applied: bool = False

    def public_summary(self) -> dict[str, Any]:
        return {
            "状态": self.user_state,
            "说明": self.user_message,
            "读取时间": self.observed_at,
            "来源时点": self.source_as_of,
            "本次读取": len(self.records),
            "现有观察": self.existing_count,
            "新增线索": self.added_count,
            "疑似缺失": self.missing_count,
            "冲突": self.conflict_count,
            "是否已应用": "否",
            "删除是否允许": "否",
        }


def build_shadow_result(
    existing_records: Iterable[dict[str, Any]],
    source: ShadowSource,
    *,
    previous_source_identity_hash: str | None = None,
    max_removal_ratio: float = MAX_REMOVAL_RATIO,
) -> ShadowSyncResult:
    existing, existing_conflicts = normalize_records(existing_records)
    observed, source_conflicts = normalize_records(source.records)
    existing_by_code = {item["code"]: item for item in existing}
    observed_by_code = {item["code"]: item for item in observed}
    missing_codes = sorted(set(existing_by_code) - set(observed_by_code))
    added_codes = sorted(set(observed_by_code) - set(existing_by_code))
    unchanged_codes = sorted(set(observed_by_code) & set(existing_by_code))
    all_conflicts = [*existing_conflicts, *source_conflicts]
    missing_ratio = len(missing_codes) / len(existing_by_code) if existing_by_code else 0.0
    account_changed = bool(
        previous_source_identity_hash
        and source.source_identity_hash
        and previous_source_identity_hash != source.source_identity_hash
    )
    if source.fetch_error:
        batch_state = "failed"
        user_state = "读取失败"
        reason = "同花顺数据未成功读取；没有生成删除判断。"
    elif not observed:
        batch_state = "rejected"
        user_state = "结果已阻断"
        reason = "本次返回为空，不能判断为用户已删除。"
    elif source.stale:
        batch_state = "rejected"
        user_state = "结果已阻断"
        reason = "备用文件时间过旧，本次只保留读取记录。"
    elif account_changed:
        batch_state = "rejected"
        user_state = "结果已阻断"
        reason = "来源身份与上次不一致，需人工确认后才能比较。"
    elif missing_ratio > max_removal_ratio and existing_by_code:
        batch_state = "partial"
        user_state = "完整性待确认"
        reason = f"本次有{len(missing_codes)}条现有记录未观察到，已触发批量删除保护。"
    elif not source.completeness_claimed:
        batch_state = "partial"
        user_state = "完整性待确认"
        reason = "当前接口没有提供完整列表证明，缺失项只作核对线索。"
    elif all_conflicts:
        batch_state = "partial"
        user_state = "存在冲突"
        reason = "证券代码或名称存在冲突，需先完成人工核对。"
    else:
        batch_state = "success"
        user_state = "读取完整"
        reason = "读取结果通过完整性检查；E2仍不应用任何增删。"
    completeness_verified = batch_state == "success" and source.completeness_claimed
    raw_content_hash = stable_hash(
        {
            "source": source.watchlist_source,
            "mode": source.source_mode,
            "records": observed,
            "source_identity_hash": source.source_identity_hash,
        }
    )
    batch_id = "ths_shadow_" + raw_content_hash.split(":", 1)[1][:24]
    block_reason = reason
    events: list[dict[str, Any]] = []
    for code in added_codes:
        item = observed_by_code[code]
        events.append({
            "event_type": "observed_add",
            "code": code,
            "before": None,
            "after": item,
            "applied": False,
            "block_reason": "影子核对，尚未应用",
        })
    for code in unchanged_codes:
        before = existing_by_code[code]
        after = observed_by_code[code]
        event_type = "observed_update" if before.get("name") and after.get("name") and before["name"] != after["name"] else "unchanged"
        events.append({
            "event_type": event_type,
            "code": code,
            "before": before,
            "after": after,
            "applied": False,
            "block_reason": "影子核对，尚未应用",
        })
    for code in missing_codes:
        events.append({
            "event_type": "observed_missing",
            "code": code,
            "before": existing_by_code[code],
            "after": None,
            "applied": False,
            "block_reason": block_reason,
        })
    for conflict in all_conflicts:
        events.append({
            "event_type": "conflict",
            "code": str(conflict.get("code") or ""),
            "before": None,
            "after": None,
            "applied": False,
            "block_reason": "证券身份存在冲突，等待核对",
        })
    events.sort(key=lambda item: (item["event_type"], item["code"]))
    return ShadowSyncResult(
        batch_id=batch_id,
        batch_state=batch_state,
        user_state=user_state,
        user_message=reason,
        completeness_verified=completeness_verified,
        completeness_reason=reason,
        records=tuple(observed),
        conflicts=tuple(all_conflicts),
        events=tuple(events),
        source_mode=source.source_mode,
        source_as_of=source.source_as_of,
        observed_at=source.observed_at,
        source_identity_hash=source.source_identity_hash,
        raw_content_hash=raw_content_hash,
        existing_count=len(existing_by_code),
        added_count=len(added_codes),
        unchanged_count=len(unchanged_codes),
        missing_count=len(missing_codes),
        conflict_count=len(all_conflicts),
    )


def latest_source_identity_hash(store: UserAssetStore) -> str | None:
    if not store.exists:
        return None
    with store.connection(readonly=True) as connection:
        row = connection.execute(
            """
            SELECT source_identity_hash
            FROM watchlist_sync_batch
            WHERE watchlist_source='ths_cloud' AND source_identity_hash IS NOT NULL
            ORDER BY started_at DESC, sync_batch_id DESC
            LIMIT 1
            """
        ).fetchone()
    return str(row["source_identity_hash"]) if row and row["source_identity_hash"] else None


def record_shadow_result(store: UserAssetStore, result: ShadowSyncResult) -> dict[str, Any]:
    store.initialize()
    with store.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT sync_batch_id FROM watchlist_sync_batch WHERE sync_batch_id=?",
            (result.batch_id,),
        ).fetchone()
        if existing:
            return {"batch_id": result.batch_id, "created": False, "event_count": len(result.events)}
        connection.execute(
            """
            INSERT INTO watchlist_sync_batch(
                sync_batch_id, watchlist_source, sync_mode, started_at,
                completed_at, batch_state, source_as_of,
                completeness_verified, source_record_count, added_count,
                updated_count, delete_observed_count, delete_applied_count,
                conflict_count, raw_content_hash, deletion_allowed,
                failure_reason, source_identity_hash, input_state,
                completeness_reason
            ) VALUES (?, 'ths_cloud', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0, ?, ?, ?, ?)
            """,
            (
                result.batch_id,
                result.source_mode,
                result.observed_at,
                result.observed_at,
                result.batch_state,
                result.source_as_of,
                1 if result.completeness_verified else 0,
                len(result.records),
                result.added_count,
                result.unchanged_count,
                result.missing_count,
                result.conflict_count,
                result.raw_content_hash,
                result.user_message if result.batch_state != "success" else None,
                result.source_identity_hash,
                result.user_state,
                result.completeness_reason,
            ),
        )
        for item in result.records:
            snapshot_id = "wss_" + hashlib.sha256(f"{result.batch_id}|{item['code']}".encode("utf-8")).hexdigest()[:24]
            connection.execute(
                """
                INSERT INTO watchlist_shadow_snapshot(
                    shadow_snapshot_id, sync_batch_id, normalized_code,
                    display_name, source_id, source_id_state, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    result.batch_id,
                    item["code"],
                    item.get("name") or None,
                    item.get("source_id"),
                    "provided" if item.get("source_id") else "not_provided",
                    result.observed_at,
                ),
            )
        for item in result.events:
            event_key = f"{result.batch_id}|{item['event_type']}|{item['code']}"
            event_id = "wse_" + hashlib.sha256(event_key.encode("utf-8")).hexdigest()[:24]
            connection.execute(
                """
                INSERT INTO watchlist_sync_event(
                    sync_event_id, sync_batch_id, event_type, before_snapshot,
                    after_snapshot, evidence_ref, applied, block_reason,
                    occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    event_id,
                    result.batch_id,
                    item["event_type"],
                    json.dumps(item.get("before"), ensure_ascii=False, sort_keys=True) if item.get("before") is not None else None,
                    json.dumps(item.get("after"), ensure_ascii=False, sort_keys=True) if item.get("after") is not None else None,
                    result.batch_id,
                    item["block_reason"],
                    result.observed_at,
                ),
            )
    return {"batch_id": result.batch_id, "created": True, "event_count": len(result.events)}


def latest_recorded_shadow(store: UserAssetStore) -> dict[str, Any]:
    if not store.exists:
        return {}
    with store.connection(readonly=True) as connection:
        batch = connection.execute(
            """
            SELECT * FROM watchlist_sync_batch
            WHERE watchlist_source='ths_cloud' AND batch_state IN ('success', 'partial')
            ORDER BY started_at DESC, sync_batch_id DESC
            LIMIT 1
            """
        ).fetchone()
        if batch is None:
            return {}
        rows = connection.execute(
            """
            SELECT normalized_code, display_name, source_id, source_id_state
            FROM watchlist_shadow_snapshot
            WHERE sync_batch_id=?
            ORDER BY normalized_code
            """,
            (batch["sync_batch_id"],),
        ).fetchall()
    return {"batch": dict(batch), "records": [dict(row) for row in rows]}

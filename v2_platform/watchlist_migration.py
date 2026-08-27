from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2_platform.user_asset_store import UserAssetStore
from v2_platform.watchlist_sync import identity_candidate, latest_recorded_shadow, normalize_code


PUBLIC_OUTPUT = "data/v2/v22/watchlist-migration-audit.json"
PRIVATE_OUTPUT = ".v2_private/watchlist-migration-preview.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def file_hash(path: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def stocks(payload: dict[str, Any], pool: str) -> list[dict[str, Any]]:
    rows = (payload.get(pool) or {}).get("stocks") if isinstance(payload.get(pool), dict) else []
    return [item for item in (rows or []) if isinstance(item, dict)]


def by_code(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for item in rows:
        code = normalize_code(item.get("code"))
        if code:
            result[code] = item
    return result


class WatchlistMigrationAuditBuilder:
    def __init__(self, root: Path, store: UserAssetStore | None = None) -> None:
        self.root = root.resolve()
        self.store = store or UserAssetStore(self.root)

    def build(self) -> tuple[dict[str, Any], dict[str, Any]]:
        watchlist_path = self.root / "config/watchlist.json"
        stock_pool_path = self.root / "data/v2/stock-pool.json"
        watchlist = load_json(watchlist_path)
        watch_rows = stocks(watchlist, "watch_only")
        small_rows = stocks(watchlist, "small_deng")
        old_rows = stocks(watchlist, "old_deng")
        watch_map = by_code(watch_rows)
        small_map = by_code(small_rows)
        old_map = by_code(old_rows)
        legacy_source_rows = [
            item for item in watch_rows
            if str(item.get("source") or "") == "同花顺自选导入"
        ]
        legacy_source_map = {
            code: item
            for code, item in watch_map.items()
            if str(item.get("source") or "") == "同花顺自选导入"
        }
        invalid_watch_rows = [item for item in watch_rows if not normalize_code(item.get("code"))]
        recorded = latest_recorded_shadow(self.store)
        batch = recorded.get("batch") if isinstance(recorded.get("batch"), dict) else {}
        current_rows = [item for item in recorded.get("records") or [] if isinstance(item, dict)]
        current_map = {
            normalize_code(item.get("normalized_code")): item
            for item in current_rows
            if normalize_code(item.get("normalized_code"))
        }
        currently_observed = sorted(set(legacy_source_map) & set(current_map))
        legacy_missing = sorted(set(legacy_source_map) - set(current_map)) if batch else []
        newly_observed = sorted(set(current_map) - set(watch_map))
        overlap_watch_small = sorted(set(watch_map) & set(small_map))
        input_hashes = {
            "现有股票池配置": file_hash(watchlist_path),
            "当前V2股票池": file_hash(stock_pool_path),
            "旧同花顺同步脚本": file_hash(self.root / "scripts/import_ths_watchlist.py"),
            "旧同花顺任务入口": file_hash(self.root / "scripts/sync_ths_watchlist.sh"),
            "旧同花顺任务配置": file_hash(self.root / "scripts/com.stock-dashboard.ths-watchlist.plist"),
        }
        preview_rows = []
        for code in sorted(set(watch_map) | set(current_map) | set(small_map) | set(old_map)):
            legacy = watch_map.get(code) or {}
            observed = current_map.get(code) or {}
            name = str(legacy.get("name") or observed.get("display_name") or "")
            identity = identity_candidate(code, name)
            relationships = []
            if code in legacy_source_map:
                relationships.append("用户来源候选")
            if code in small_map:
                relationships.append("小登风格样本候选")
            if code in old_map:
                relationships.append("老登风格样本候选")
            preview_rows.append({
                "identity": identity,
                "relationships": relationships,
                "legacy_user_source_evidence": code in legacy_source_map,
                "currently_observed_by_ths": code in current_map,
                "watchlist_source": "ths_cloud" if code in legacy_source_map or code in current_map else None,
                "source_id": observed.get("source_id"),
                "source_id_state": observed.get("source_id_state") if observed else "not_observed",
                "source_priority_candidate": 100 if code in legacy_source_map or code in current_map else None,
                "user_priority_candidate": "normal" if code in legacy_source_map else None,
                "user_priority_origin": "system_default_not_user_setting" if code in legacy_source_map else None,
                "user_intent_candidate": "unset" if code in legacy_source_map else None,
                "user_note": "",
                "user_confirmed_at": None,
                "migration_eligible": False,
                "applied": False,
            })
        for item in invalid_watch_rows:
            is_user_source = str(item.get("source") or "") == "同花顺自选导入"
            preview_rows.append({
                "identity": identity_candidate(str(item.get("code") or ""), str(item.get("name") or "")),
                "relationships": ["用户来源候选"] if is_user_source else [],
                "legacy_user_source_evidence": is_user_source,
                "currently_observed_by_ths": False,
                "watchlist_source": "ths_cloud" if is_user_source else None,
                "source_id": None,
                "source_id_state": "not_observed",
                "source_priority_candidate": 100 if is_user_source else None,
                "user_priority_candidate": "normal" if is_user_source else None,
                "user_priority_origin": "system_default_not_user_setting" if is_user_source else None,
                "user_intent_candidate": "unset" if is_user_source else None,
                "user_note": "",
                "user_confirmed_at": None,
                "migration_eligible": False,
                "applied": False,
            })
        identity_review_count = sum(item["identity"].get("state") != "mapped" for item in preview_rows)
        source_id_missing_count = sum(
            item.get("watchlist_source") == "ths_cloud" and item.get("source_id") is None
            for item in preview_rows
        )
        if not batch:
            state = "等待首次影子读取"
            message = "尚无同花顺影子批次；现有观察池保持不变。"
        else:
            state = str(batch.get("input_state") or "等待核对")
            message = str(batch.get("completeness_reason") or "影子结果等待核对。")
            if state == "完整性待确认" and int(batch.get("delete_observed_count") or 0) > 0:
                message = (
                    "当前接口没有提供完整列表证明；"
                    f"有{int(batch.get('delete_observed_count') or 0)}条现有记录本次未观察到，已触发批量删除保护。"
                )
        generated_at = now_iso()
        public = {
            "schema_version": 1,
            "generated_at": generated_at,
            "stage": "E2同花顺影子同步与迁移核对",
            "status": "shadow_ready" if batch else "input_pending",
            "user_view": {
                "状态": state,
                "说明": message,
                "最近读取": batch.get("completed_at") if batch else None,
                "当前读取数量": len(current_map),
                "现有个人观察数量": len(watch_rows),
                "新增线索数量": len(newly_observed),
                "疑似缺失数量": len(legacy_missing),
                "冲突数量": int(batch.get("conflict_count") or 0) if batch else 0,
                "应用状态": "影子核对，尚未应用到我的关注",
            },
            "frozen_input_fingerprints": input_hashes,
            "counts": {
                "watch_only": len(watch_rows),
                "small_deng": len(small_rows),
                "old_deng": len(old_rows),
                "watch_small_overlap": len(overlap_watch_small),
                "legacy_ths_source_candidates": len(legacy_source_rows),
                "currently_observed_candidates": len(currently_observed),
                "newly_observed_candidates": len(newly_observed),
                "legacy_missing_candidates": len(legacy_missing),
                "identity_review_count": identity_review_count,
                "source_id_not_provided_count": source_id_missing_count,
                "user_confirmed_at_missing_count": len(legacy_source_rows),
            },
            "guardrails": {
                "migration_applied": False,
                "user_assets_modified": False,
                "user_priority_modified": False,
                "user_intent_modified": False,
                "用户备注复制": False,
                "user_confirmed_at_inferred": False,
                "style_pool_created_user_assets": False,
                "delete_applied": False,
            },
            "privacy": {
                "private_codes_published": False,
                "private_names_published": False,
                "source_account_published": False,
                "用户备注公开": False,
            },
        }
        private = {
            "schema_version": 1,
            "generated_at": generated_at,
            "stage": "E2影子迁移预览",
            "batch_id": batch.get("sync_batch_id") if batch else None,
            "input_fingerprints": input_hashes,
            "migration_applied": False,
            "records": preview_rows,
        }
        return public, private

    def write(self) -> dict[str, Any]:
        public, private = self.build()
        public_path = self.root / PUBLIC_OUTPUT
        private_path = self.root / PRIVATE_OUTPUT
        public_path.parent.mkdir(parents=True, exist_ok=True)
        private_path.parent.mkdir(parents=True, exist_ok=True)
        public_path.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        private_path.write_text(json.dumps(private, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return public

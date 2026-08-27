#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.user_asset_store import UserAssetStore
from v2_platform.watchlist_sync import latest_recorded_shadow, normalize_code


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def keyed(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {code: item for item in rows if (code := normalize_code(item.get("code") or item.get("normalized_code")))}


def main() -> int:
    watchlist = load(ROOT / "config/watchlist.json")
    pool = load(ROOT / "data/v2/stock-pool.json")
    old_rows = [item for item in ((watchlist.get("watch_only") or {}).get("stocks") or []) if isinstance(item, dict)]
    invalid_old_rows = [item for item in old_rows if not normalize_code(item.get("code"))]
    old_map = keyed(old_rows)
    system_map = keyed([item for item in pool.get("stocks") or [] if isinstance(item, dict)])
    store = UserAssetStore(ROOT)
    recorded = latest_recorded_shadow(store)
    batch = recorded.get("batch") if isinstance(recorded.get("batch"), dict) else {}
    observed_map = keyed([item for item in recorded.get("records") or [] if isinstance(item, dict)])
    codes = sorted(set(old_map) | set(observed_map))
    rows = []
    for code in codes:
        legacy = old_map.get(code) or {}
        observed = observed_map.get(code) or {}
        system = system_map.get(code) or {}
        rows.append({
            "code": code,
            "name": legacy.get("name") or observed.get("display_name") or system.get("name"),
            "ths_currently_observed": code in observed_map,
            "legacy_watch_only": code in old_map,
            "system_security_present": code in system_map,
            "source_id": observed.get("source_id"),
            "source_id_state": observed.get("source_id_state") if observed else "not_observed",
            "old_source": legacy.get("source"),
            "system_themes": system.get("themes") or [],
            "system_roles": system.get("roles") or [],
            "migration_eligible": False,
            "deletion_evidence": False,
            "review_state": (
                "三方均有记录" if code in observed_map and code in old_map and code in system_map else
                "同花顺新观察，等待完整列表确认" if code in observed_map and code not in old_map else
                "旧观察本次未出现，不得删除" if code in old_map and code not in observed_map else
                "证券主表待补" if code not in system_map else "等待核对"
            ),
        })
    for legacy in invalid_old_rows:
        rows.append({
            "code": legacy.get("code"),
            "name": legacy.get("name"),
            "ths_currently_observed": False,
            "legacy_watch_only": True,
            "system_security_present": False,
            "source_id": None,
            "source_id_state": "identity_needs_review",
            "old_source": legacy.get("source"),
            "system_themes": [],
            "system_roles": [],
            "migration_eligible": False,
            "deletion_evidence": False,
            "review_state": "旧记录代码无法确定市场，必须人工核对证券身份",
        })
    user_asset_count = 0
    if store.exists:
        with store.connection(readonly=True) as connection:
            user_asset_count = int(connection.execute("SELECT COUNT(*) FROM user_watchlist_asset").fetchone()[0])
    complete = bool(batch.get("completeness_verified")) and batch.get("batch_state") == "success"
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    private = {
        "schema_version": 1,
        "generated_at": generated_at,
        "mode": "private_read_only_preview",
        "source_batch": {
            "batch_state": batch.get("batch_state"),
            "source_as_of": batch.get("source_as_of"),
            "completed_at": batch.get("completed_at"),
            "source_record_count": batch.get("source_record_count"),
            "completeness_verified": complete,
            "reason": batch.get("completeness_reason"),
        },
        "records": rows,
        "guardrails": {
            "migration_applied": False,
            "deletion_applied": False,
            "user_assets_modified": False,
            "style_pool_used_as_user_pool": False,
        },
    }
    summary = {
        "schema_version": 1,
        "generated_at": generated_at,
        "mode": "shadow_only",
        "state": "ready_for_user_migration_review" if complete else "source_completeness_blocked",
        "headline": "同花顺完整列表尚未得到证明，用户资产迁移继续阻断。" if not complete else "三方列表已具备完整性证据，仍需用户确认后才能迁移。",
        "counts": {
            "ths_observed": len(observed_map),
            "legacy_watch_only": len(old_rows),
            "legacy_identity_mapped": len(old_map),
            "legacy_identity_needs_review": len(invalid_old_rows),
            "system_security_matches": sum(code in system_map for code in codes),
            "three_way_matches": sum(code in observed_map and code in old_map and code in system_map for code in codes),
            "ths_only": sum(code in observed_map and code not in old_map for code in codes),
            "legacy_not_observed": sum(code in old_map and code not in observed_map for code in codes),
            "user_confirmed_assets": user_asset_count,
        },
        "source": {
            "last_usable_shadow_state": batch.get("batch_state") or "尚无可用批次",
            "last_usable_shadow_at": batch.get("completed_at"),
            "completeness_verified": complete,
            "current_app_read_state": "读取超时；已改为硬超时并保留上一次可用影子结果",
        },
        "next_action": "取得可证明分页结束/完整列表的同花顺读取后，重新生成一次迁移预览并交由用户确认。",
        "guardrails": private["guardrails"],
        "privacy": {
            "public_codes_included": False,
            "public_names_included": False,
            "private_preview_path_published": False,
        },
    }
    write(ROOT / ".v2_private/watchlist-three-way-preview.json", private)
    write(ROOT / "data/v2/v22/watchlist-three-way-summary.json", summary)
    print(json.dumps({"state": summary["state"], **summary["counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

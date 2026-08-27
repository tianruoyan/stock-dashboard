from __future__ import annotations

from pathlib import Path
from typing import Any

from v2_platform.user_asset_store import UserAssetStore, UserAssetStoreError


def build_user_asset_storage_health(root: Path) -> dict[str, Any]:
    store = UserAssetStore(root)
    if not store.exists:
        return {
            "状态": "尚未初始化",
            "完整性": "待检查",
            "写入边界": "页面写入未开放",
            "隐私说明": "用户自选和备注只允许保存在本机私有区。",
        }
    try:
        summary = store.integrity_summary()
    except (OSError, UserAssetStoreError):
        return {
            "状态": "需要检查",
            "完整性": "未通过",
            "写入边界": "页面写入未开放",
            "隐私说明": "未读取或输出任何用户自选内容。",
        }
    empty = int(summary.get("user_asset_count") or 0) == 0
    return {
        "状态": "空结构已就绪" if empty else "本机存储正常",
        "完整性": "正常" if summary.get("integrity") == "ok" else "需要检查",
        "结构版本": "、".join(summary.get("schema_versions") or []) or "待建立",
        "写入边界": "页面写入未开放；AI和风格模型无用户资产写权限",
        "隐私说明": "不输出用户自选、优先级、关注目的、备注或来源账号。",
    }


def build_user_asset_read_projection(root: Path, *, user_id: str = "local_user") -> dict[str, Any]:
    store = UserAssetStore(root)
    if not store.exists:
        return {
            "状态": "尚未初始化",
            "说明": "用户资产私有结构尚未建立。",
            "数量": 0,
            "用户自选": [],
            "写入状态": "当前阶段未开放",
        }
    try:
        with store.connection(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT
                    asset.user_asset_id,
                    security.normalized_code,
                    security.display_name,
                    asset.user_priority,
                    asset.user_intent,
                    asset.user_note,
                    asset.user_confirmed_at,
                    asset.revision
                FROM user_watchlist_asset AS asset
                JOIN security_master AS security ON security.security_id = asset.security_id
                WHERE asset.user_id=? AND asset.membership_state='active'
                ORDER BY
                    CASE asset.user_priority WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
                    security.normalized_code
                """,
                (user_id,),
            ).fetchall()
            items = []
            for row in rows:
                source_rows = connection.execute(
                    """
                    SELECT watchlist_source, source_priority
                    FROM watchlist_source_link
                    WHERE user_asset_id=? AND source_state='active'
                    ORDER BY source_priority DESC
                    """,
                    (row["user_asset_id"],),
                ).fetchall()
                items.append({
                    "代码": row["normalized_code"],
                    "名称": row["display_name"],
                    "用户优先级": row["user_priority"],
                    "关注目的": row["user_intent"] or "未设置",
                    "用户备注": row["user_note"] or "",
                    "用户确认时间": row["user_confirmed_at"],
                    "有效来源": [source["watchlist_source"] for source in source_rows],
                    "版本": int(row["revision"]),
                })
    except (OSError, UserAssetStoreError):
        return {
            "状态": "读取失败",
            "说明": "本机用户资产暂时无法读取，请稍后重试。",
            "数量": 0,
            "用户自选": [],
            "写入状态": "当前阶段未开放",
        }
    return {
        "状态": "空结构已就绪" if not items else "读取正常",
        "说明": "E1只建立私有底座，尚未导入同花顺或现有股票池。" if not items else "以下内容来自本机用户确认资产。",
        "数量": len(items),
        "用户自选": items,
        "写入状态": "当前阶段未开放",
    }

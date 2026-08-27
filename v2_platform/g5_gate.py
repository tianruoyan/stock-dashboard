from __future__ import annotations

from typing import Any


G5_RESULTS = {"support", "partial_support", "neutral", "suppress", "block"}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def build_g5_links(decision: dict[str, Any], environment: dict[str, Any], state: dict[str, Any], cross_market: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dimensions = [item for item in as_list(environment.get("dimensions")) if isinstance(item, dict)]
    support = [item for item in dimensions if item.get("support_level") in {"support", "partial_support"}]
    suppress = [item for item in dimensions if item.get("support_level") in {"suppress", "risk_release"}]
    hard_block = environment.get("quality_state") == "blocked"
    confirmed_external = [item for item in cross_market if item.get("transmission_state") == "confirmed"]
    rows = []
    cards = [
        *[item for item in as_list(decision.get("opportunity_radar")) if isinstance(item, dict)],
        *[item for item in as_list(decision.get("validation_queue")) if isinstance(item, dict)],
    ]
    seen = set()
    for card in cards:
        opportunity_id = str(card.get("id") or "")
        if not opportunity_id or opportunity_id in seen:
            continue
        seen.add(opportunity_id)
        if hard_block:
            result = "block"
            action = "关键数据阻断，停止升级"
            reason = "环境关键数据会改变结论，当前不能进入决策就绪。"
        elif state.get("primary_state") in {"risk_release", "retreat"} or len(suppress) >= 2:
            result = "suppress"
            action = "等待风险收敛，不追"
            reason = "全市场风险状态和抑制维度限制机会升级。"
        elif len(support) >= 3:
            result = "support"
            action = "可继续检查代表股、位置和有效期"
            reason = "至少三个环境维度支持，但仍不能绕过其他门禁。"
        elif support:
            result = "partial_support"
            action = "等待确认"
            reason = "只有局部环境支持，仍有反证或缺失项。"
        else:
            result = "neutral"
            action = "仅保留观察"
            reason = "环境没有提供明确优势。"
        rows.append({
            "opportunity_id": opportunity_id,
            "title": card.get("title") or card.get("theme") or "未命名线索",
            "environment_snapshot_id": environment.get("environment_snapshot_id"),
            "g5_result": result,
            "supporting_dimensions": [item.get("dimension_code") for item in support],
            "suppressing_dimensions": [item.get("dimension_code") for item in suppress],
            "confirmed_external_mappings": [item.get("mapping_id") for item in confirmed_external],
            "effective_action": action,
            "reason": reason,
            "representative_stock_gate_still_required": True,
            "position_gate_still_required": True,
            "user_asset_identity_bypasses_gate": False,
            "user_assets_modified": False,
        })
    return rows

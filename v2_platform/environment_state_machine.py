from __future__ import annotations

from typing import Any

from v2_platform.environment_evidence import stable_id


STATES = ("risk_release", "repair", "rotation_trial", "mainline_confirmed", "diffusion_strengthening", "crowding_divergence", "retreat")


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def decide_environment_transition(
    environment: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
    policy_version: str = "2026-07-18.e5.1",
) -> dict[str, Any]:
    dimensions = [item for item in as_list(environment.get("dimensions")) if isinstance(item, dict)]
    by_code = {str(item.get("dimension_code") or ""): item for item in dimensions}
    previous_state = str((previous or {}).get("primary_state") or "unknown")
    previous_confirmations = int((previous or {}).get("confirmation_count") or 0)
    risk_codes = [
        code for code in ("sentiment_structure", "position_fragility", "liquidity", "market_breadth")
        if by_code.get(code, {}).get("support_level") in {"suppress", "risk_release"}
        and by_code.get(code, {}).get("quality_state") in {"usable", "degraded"}
    ]
    usable_support = [
        code for code, item in by_code.items()
        if item.get("support_level") == "support" and item.get("quality_state") == "usable"
    ]
    partial_support = [
        code for code, item in by_code.items()
        if item.get("support_level") in {"support", "partial_support"} and item.get("quality_state") in {"usable", "degraded"}
    ]
    hard_block = environment.get("quality_state") == "blocked"
    mainline_support = by_code.get("mainline_structure", {}).get("support_level") == "support"
    if len(risk_codes) >= 2:
        target = "risk_release"
        transition_type = "risk_fast_path" if previous_state != target else "unchanged"
        confirmation_count = 1
        reason = "涨跌停、高位股、成交或上涨家数中，至少两项明显转弱，先控制风险。"
    elif risk_codes:
        target = "retreat" if previous_state not in {"risk_release", "retreat"} else previous_state
        transition_type = "risk_fast_path" if target != previous_state else "unchanged"
        confirmation_count = 1
        reason = "至少一项关键市场表现明显转弱，暂时减少进攻，先控制风险。"
    elif hard_block:
        target = previous_state if previous_state in STATES else "risk_release"
        transition_type = "quality_hold"
        confirmation_count = previous_confirmations
        reason = "关键数据不足，暂不增加操作，只保留已有判断。"
    else:
        if mainline_support and len(usable_support) >= 3:
            candidate = "mainline_confirmed"
        elif len(partial_support) >= 2:
            candidate = "repair" if previous_state in {"unknown", "risk_release", "retreat"} else "rotation_trial"
        else:
            candidate = previous_state if previous_state in STATES else "repair"
        same_candidate = str((previous or {}).get("pending_candidate") or "") == candidate
        confirmation_count = previous_confirmations + 1 if same_candidate else 1
        if candidate != previous_state and confirmation_count < 2:
            target = previous_state if previous_state in STATES else "repair"
            transition_type = "pending_confirmation"
            reason = "市场转强只出现一次，还要在下一次检查时继续转强，才能提高关注。"
        else:
            target = candidate
            transition_type = "upgrade" if target != previous_state else "unchanged"
            reason = "市场转强已经连续出现两次，可以提高关注。" if transition_type == "upgrade" else "还没有新的事实足以改变当前判断。"
    action = {
        "risk_release": "先防守，等跌停减少、高位股止跌",
        "repair": "等待确认，只观察板块核心股",
        "rotation_trial": "观察明确条件，不追涨后排",
        "mainline_confirmed": "积极关注已满足全部条件的正式观察对象",
        "diffusion_strengthening": "关注产业逻辑清楚、板块内多数股票同步走强的对象",
        "crowding_divergence": "不追高，等成交充分或风险降低",
        "retreat": "减少追涨，优先控制风险",
    }[target]
    snapshot_id = str(environment.get("environment_snapshot_id") or "")
    return {
        "transition_id": stable_id("environment_transition", snapshot_id, previous_state, target, transition_type, policy_version),
        "environment_snapshot_id": snapshot_id,
        "from_state": previous_state,
        "primary_state": target,
        "transition_type": transition_type,
        "trigger_dimensions": risk_codes if risk_codes else (usable_support or partial_support),
        "trigger_evidence_ids": [ref_id for code in (risk_codes if risk_codes else usable_support) for ref_id in as_list(by_code.get(code, {}).get("evidence_ref_ids"))],
        "counter_evidence": [text for item in dimensions for text in as_list(item.get("counter_evidence"))][:8],
        "confirmation_count": confirmation_count,
        "pending_candidate": None if transition_type not in {"pending_confirmation"} else candidate,
        "policy_version": policy_version,
        "transition_reason": reason,
        "action_constraint": action,
        "positive_upgrade_requires_two_checks": True,
        "risk_fast_path": transition_type == "risk_fast_path",
        "state_changed": target != previous_state and transition_type not in {"pending_confirmation", "quality_hold"},
    }

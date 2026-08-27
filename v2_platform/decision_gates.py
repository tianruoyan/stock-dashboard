from __future__ import annotations

from typing import Any


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def quote_complete(stock: Any) -> bool:
    return bool(
        isinstance(stock, dict)
        and stock.get("stock_code")
        and stock.get("name")
        and stock.get("stock_change_pct") is not None
        and stock.get("stock_quote_as_of")
        and stock.get("stock_quote_source")
        and stock.get("role")
        and stock.get("basis")
    )


def gate(gate_id: str, label: str, state: str, conclusion: str, missing: list[str] | None = None) -> dict[str, Any]:
    return {"gate_id": gate_id, "label": label, "state": state, "conclusion": conclusion, "missing": missing or []}


def evaluate_gates(
    card: dict[str, Any],
    *,
    business_path: str,
    environment_gate: dict[str, Any] | None,
    overall_quality: str,
    ended: bool,
) -> list[dict[str, Any]]:
    representatives = [item for item in as_list(card.get("representative_stocks")) if isinstance(item, dict)]
    complete_representatives = [item for item in representatives if quote_complete(item)]
    explicit_verifications = [
        item for item in complete_representatives
        if item.get("stock_quote_verification") is not None or item.get("cross_source_verified") is not None
    ]
    verification_conflict = any(
        item.get("stock_quote_verification") in {"两路行情存在差异", "两路行情日期不一致", "两路行情时间未对齐"}
        for item in explicit_verifications
    )
    verification_pending = bool(explicit_verifications) and not all(
        item.get("cross_source_verified") is True for item in explicit_verifications
    )
    accepted_evidence = [
        item for item in [*as_list(card.get("evidence")), *as_list(card.get("evidence_refs"))]
        if isinstance(item, dict) and item.get("accepted") is not False
    ]
    trigger = card.get("trigger_metrics") if isinstance(card.get("trigger_metrics"), dict) else {}
    has_material_trigger = bool(
        card.get("triggered_at")
        or (trigger.get("as_of") and (trigger.get("change_pct") is not None or trigger.get("metric_scope")))
        or accepted_evidence
    )
    object_name = card.get("theme") or card.get("title") or card.get("theme_id")
    reason_text = str(card.get("why_watch_summary") or card.get("why_watch") or card.get("conclusion") or "")
    weak_reason = not reason_text or "证据不足" in reason_text or "等待主题专属依据" in reason_text
    roles = {str(item.get("role") or "") for item in complete_representatives if item.get("role")}
    representative_ok = bool(complete_representatives) and len(complete_representatives) == len(representatives)
    theme_roles_ok = business_path != "theme_opportunity" or len(roles) >= 2
    confirm = [str(value) for value in as_list(card.get("confirm_conditions")) if value]
    invalidation = [str(value) for value in as_list(card.get("invalidation_conditions")) if value]
    validity = card.get("valid_until")
    gates = []
    if overall_quality == "blocked":
        gates.append(gate("G0", "数据可用", "block", "关键数据会改变结论，停止正向升级。", ["恢复关键事实"]));
    elif overall_quality == "usable" and accepted_evidence:
        gates.append(gate("G0", "数据可用", "pass", "来源、时点和采用证据可核验。"));
    else:
        gates.append(gate("G0", "数据可用", "partial", "全局或案例证据仍有降级项，只能保守使用。", ["补齐同日证据或冲突处理"]));
    gates.append(gate("G1", "触发成立", "pass" if has_material_trigger else "fail", "已记录实质触发。" if has_material_trigger else "没有可核验的实质变化，只保留为线索。", [] if has_material_trigger else ["实质触发与时点"]));
    gates.append(gate("G2", "对象明确", "pass" if object_name else "fail", f"对象为{object_name}。" if object_name else "主题、单股、风格或事件对象不明确。", [] if object_name else ["明确对象"]));
    if not representatives:
        gates.append(gate("G3", "代表股确认", "fail", "没有代表股依据，不能进入驾驶舱决策案例。", ["代表股代码、真实行情、角色和依据"]));
    elif not representative_ok:
        gates.append(gate("G3", "代表股确认", "fail", "部分代表股缺少代码、真实行情、时点、来源、角色或依据。", ["补齐代表股行情闭环"]));
    elif verification_conflict:
        gates.append(gate("G3", "代表股确认", "fail", "代表股两路行情存在差异，当前不能用于机会升级。", ["等待两路行情重新对齐"]));
    elif verification_pending:
        gates.append(gate("G3", "代表股确认", "partial", "代表股已有真实行情，但仍在等待第二来源确认。", ["完成代表股双源确认"]));
    elif not theme_roles_ok:
        gates.append(gate("G3", "代表股确认", "partial", "代表股真实行情完整，但主题机会仍缺少两类不同角色确认。", ["核心、中军、弹性或后排中至少两类角色"]));
    else:
        gates.append(gate("G3", "代表股确认", "pass", "代表股行情与角色满足当前业务路径要求。"));
    gates.append(gate("G4", "原因可解释", "partial" if weak_reason else "pass", "原因仍偏弱，降低解释强度。" if weak_reason else "当前原因和反向证据可展开核验。", ["主题专属原因"] if weak_reason else []));
    g5_result = str((environment_gate or {}).get("g5_result") or "neutral")
    g5_state = {"support": "pass", "partial_support": "partial", "neutral": "pending", "suppress": "suppress", "block": "block"}.get(g5_result, "pending")
    gates.append(gate("G5", "环境许可", g5_state, str((environment_gate or {}).get("reason") or "环境没有提供明确优势。"), ["等待环境确认"] if g5_state in {"pending", "partial"} else []));
    position_facts = [value for value in as_list(card.get("position_facts")) if value]
    tradability = card.get("tradability")
    if business_path == "risk_path" and representatives:
        gates.append(gate("G6", "位置可交易", "partial", "风险路径可以提前提醒，但仍需核验位置、流动性与恢复条件。", ["位置与可交易性"]));
    elif position_facts and tradability:
        gates.append(gate("G6", "位置可交易", "pass", "位置、流动性和可交易性已有明确事实。"));
    else:
        gates.append(gate("G6", "位置可交易", "pending", "缺少位置、拥挤、流动性或可买性事实，不追。", ["位置、拥挤、流动性和可买性"]));
    if ended:
        gates.append(gate("G7", "条件与时窗", "not_applicable", "案例已经结束，只用于复盘。"));
    elif confirm and invalidation and validity:
        gates.append(gate("G7", "条件与时窗", "pass", "加强、失效和有效时间均已明确。"));
    elif confirm and invalidation:
        gates.append(gate("G7", "条件与时窗", "partial", "加强和失效条件已明确，但有效时间仍待补。", ["本次判断有效至"]));
    else:
        gates.append(gate("G7", "条件与时窗", "fail", "加强、失效或有效时间不完整。", ["加强条件", "失效条件", "本次判断有效至"]));
    return gates


def decision_maturity(gates: list[dict[str, Any]], *, ended: bool, signal_state: str, business_path: str) -> str:
    if ended or signal_state == "invalidated":
        return "ended"
    by_id = {item["gate_id"]: item["state"] for item in gates}
    if by_id.get("G1") == "fail" or by_id.get("G2") == "fail":
        return "clue"
    if by_id.get("G3") == "fail" or by_id.get("G4") in {"fail", "partial"}:
        return "observe"
    allowed = {"pass"}
    if all(by_id.get(gate_id) in allowed for gate_id in ("G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7")):
        return "decision_ready"
    if by_id.get("G5") in {"suppress", "block"} or by_id.get("G6") in {"suppress", "block"}:
        return "weakened"
    return "await_confirmation"

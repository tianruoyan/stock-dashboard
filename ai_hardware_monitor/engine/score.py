from __future__ import annotations

from datetime import datetime
from typing import Any


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _value(payload: dict[str, Any], *path: str) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _points_min(value: float | None, rules: list[dict[str, Any]]) -> int:
    if value is None:
        return 0
    for item in rules:
        threshold = _number(item.get("min"))
        if threshold is not None and value >= threshold:
            return int(item.get("points") or 0)
    return 0


def _points_max(value: float | None, rules: list[dict[str, Any]]) -> int:
    if value is None:
        return 0
    for item in rules:
        threshold = _number(item.get("max"))
        if threshold is not None and value <= threshold:
            return int(item.get("points") or 0)
    return 0


def _component(
    component_id: str,
    label: str,
    value: float | None,
    points: int,
    maximum: int,
    detail: str,
) -> dict[str, Any]:
    return {
        "id": component_id,
        "label": label,
        "value": round(value, 4) if value is not None else None,
        "points": int(points),
        "max_points": int(maximum),
        "available": value is not None,
        "detail": detail,
    }


def _category(category_id: str, label: str, maximum: int, components: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": category_id,
        "label": label,
        "score": sum(int(item["points"]) for item in components),
        "max_points": maximum,
        "available_points": sum(int(item["max_points"]) for item in components if item["available"]),
        "components": components,
    }


def _freshness(snapshot: dict[str, Any], now: datetime, maximum_age_minutes: int) -> tuple[bool, str]:
    raw = snapshot.get("as_of")
    try:
        as_of = datetime.fromisoformat(str(raw))
        if as_of.tzinfo is None or now.tzinfo is None:
            return False, "快照时间缺少时区"
        if str(snapshot.get("trade_date") or "") != now.date().isoformat():
            return False, "快照不是当前交易日"
        age = (now - as_of.astimezone(now.tzinfo)).total_seconds() / 60
        if age < -2:
            return False, "快照时间晚于运行时间"
        if age > maximum_age_minutes:
            return False, f"快照已超过{maximum_age_minutes}分钟"
    except (TypeError, ValueError):
        return False, "快照时间不可解析"
    return True, "快照时点有效"


def evaluate_snapshot(
    snapshot: dict[str, Any],
    weights: dict[str, Any],
    rules: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    scoring = rules.get("scoring") if isinstance(rules, dict) else {}
    scoring = scoring if isinstance(scoring, dict) else {}

    relative = _number(_value(snapshot, "sector", "relative_outperformance_pct"))
    market_rank = _number(_value(snapshot, "sector", "market_rank"))
    sector_breadth = _number(_value(snapshot, "sector", "advance_ratio_pct"))
    sector_components = [
        _component("relative_strength", "相对沪深300", relative, _points_min(relative, scoring.get("relative_outperformance_pct", [])), 15, "代理篮子相对沪深300的当日超额"),
        _component("market_rank", "可比行业排名", market_rank, _points_max(market_rank, scoring.get("market_rank", [])), 8, "8股代理篮子与腾讯行业指数同口径排名；缺失时不能绿色启动"),
        _component("advance_breadth", "股票池上涨宽度", sector_breadth, _points_min(sector_breadth, scoring.get("advance_ratio_pct", [])), 7, "8股代理篮子中上涨股票占比"),
    ]

    leader_outperform = _number(_value(snapshot, "leaders", "outperform_ratio"))
    leader_turnover = _number(_value(snapshot, "leaders", "median_turnover_pace"))
    leader_trend = _number(_value(snapshot, "leaders", "trend_confirmed_ratio"))
    leader_components = [
        _component("leader_outperformance", "核心龙头领先", leader_outperform, _points_min(leader_outperform, scoring.get("leader_outperform_ratio", [])), 10, "新易盛、中际旭创、沪电股份强于代理篮子的比例"),
        _component("leader_turnover_pace", "核心龙头成交速度", leader_turnover, _points_min(leader_turnover, scoring.get("leader_turnover_pace", [])), 10, "相对5日同时点成交速度中位数"),
        _component("leader_trend", "核心龙头趋势", leader_trend, _points_min(leader_trend, scoring.get("leader_trend_ratio", [])), 10, "同时站上5日与10日均线的核心龙头比例"),
    ]

    inflow_days = _number(_value(snapshot, "funds", "continuous_net_inflow_days"))
    pool_inflow = _number(_value(snapshot, "funds", "pool_net_inflow_yi"))
    etf_inflow = _number(_value(snapshot, "funds", "etf_net_inflow_yi"))
    funds_components = [
        _component("continuous_net_inflow", "连续净流入", inflow_days, _points_min(inflow_days, scoring.get("continuous_net_inflow_days", [])), 10, "来自可核验上游的连续净流入天数"),
        _component("pool_net_inflow", "股票池净流入", pool_inflow, 5 if pool_inflow is not None and pool_inflow > 0 else 0, 5, "股票池净流入为正；成交放大不能替代"),
        _component("etf_net_inflow", "相关ETF净流入", etf_inflow, 5 if etf_inflow is not None and etf_inflow > 0 else 0, 5, "相关ETF净流入为正"),
    ]

    market_turnover = _number(_value(snapshot, "market_environment", "market_turnover_ratio"))
    technology_breadth = _number(_value(snapshot, "market_environment", "technology_advance_ratio_pct"))
    limit_ratio = _number(_value(snapshot, "market_environment", "limit_up_down_ratio"))
    environment_components = [
        _component("market_turnover", "市场成交", market_turnover, _points_min(market_turnover, scoring.get("market_turnover_ratio", [])), 8, "两市成交额相对可比基线"),
        _component("technology_breadth", "科技股宽度", technology_breadth, _points_min(technology_breadth, scoring.get("technology_advance_ratio_pct", [])), 6, "同口径科技股上涨占比"),
        _component("limit_up_down_ratio", "涨跌停结构", limit_ratio, _points_min(limit_ratio, scoring.get("limit_up_down_ratio", [])), 6, "同口径涨停数与跌停数之比"),
    ]

    categories = [
        _category("sector_strength", "板块强度", 30, sector_components),
        _category("leader_strength", "龙头强度", 30, leader_components),
        _category("funds_return", "资金回流", 20, funds_components),
        _category("market_environment", "市场环境", 20, environment_components),
    ]
    score = sum(int(item["score"]) for item in categories)
    available = sum(int(item["available_points"]) for item in categories)
    coverage = round(available / 100, 4)

    quality = rules.get("quality") if isinstance(rules.get("quality"), dict) else {}
    fresh, freshness_reason = _freshness(snapshot, now, int(quality.get("maximum_snapshot_age_minutes") or 20))
    source_state = str(_value(snapshot, "source_quality", "state") or "waiting")
    data_usable = fresh and source_state in {"usable", "degraded"}

    gates_config = rules.get("launch_gates") if isinstance(rules.get("launch_gates"), dict) else {}
    leading_count = _number(_value(snapshot, "leaders", "outperform_count"))
    gates = [
        {
            "id": "score",
            "label": "评分达到80",
            "passed": score >= int(_value(rules, "score_thresholds", "launch_min") or 80),
            "actual": score,
        },
        {
            "id": "coverage",
            "label": "数据覆盖率达到80%",
            "passed": coverage >= float(quality.get("minimum_for_launch") or 0.8) and data_usable,
            "actual": coverage,
        },
        {
            "id": "sector_rank",
            "label": "AI硬件代理篮子位于可比行业前三",
            "passed": market_rank is not None and market_rank <= float(gates_config.get("sector_market_rank_max") or 3),
            "actual": market_rank,
        },
        {
            "id": "leader",
            "label": "至少一只核心龙头领先",
            "passed": leading_count is not None and leading_count >= float(gates_config.get("minimum_leading_core_count") or 1),
            "actual": leading_count,
        },
        {
            "id": "turnover",
            "label": "龙头成交速度达到1.2",
            "passed": leader_turnover is not None and leader_turnover >= float(gates_config.get("minimum_leader_turnover_pace") or 1.2),
            "actual": leader_turnover,
        },
        {
            "id": "funds",
            "label": "连续资金净流入至少2天",
            "passed": inflow_days is not None and inflow_days >= float(gates_config.get("minimum_continuous_net_inflow_days") or 2),
            "actual": inflow_days,
        },
    ]

    thresholds = rules.get("score_thresholds") if isinstance(rules.get("score_thresholds"), dict) else {}
    minimum_for_risk = float(quality.get("minimum_for_risk") or 0.65)
    all_launch_gates = all(bool(item["passed"]) for item in gates)
    if all_launch_gates:
        state_code, state_label, action = "launch", "🟢启动", "触发买入观察；不自动交易，由用户结合风险自行决定"
    elif not data_usable or coverage < minimum_for_risk:
        state_code, state_label, action = "observe", "🟡观察", "数据不足或过期，等待下一检查点补齐"
    elif score < int(thresholds.get("risk_below") or 40):
        state_code, state_label, action = "risk", "🔴风险", "暂停新增观察，等待风险事实收敛"
    elif score >= int(thresholds.get("observe_confirmed_min") or 60):
        state_code, state_label, action = "observe", "🟡观察", "资金回流观察中，等待绿色硬门槛同时成立"
    else:
        state_code, state_label, action = "observe", "🟡观察", "弱观察，等待龙头、板块与资金进一步确认"

    failed_gates = [item["label"] for item in gates if not item["passed"]]
    missing = _value(snapshot, "source_quality", "missing")
    missing = missing if isinstance(missing, list) else []
    return {
        "score": score,
        "max_score": 100,
        "coverage_ratio": coverage,
        "categories": categories,
        "state": {"code": state_code, "label": state_label, "action": action},
        "launch_gates": gates,
        "failed_launch_gates": failed_gates,
        "data_quality": {
            "state": source_state,
            "usable": data_usable,
            "freshness": freshness_reason,
            "missing": missing,
        },
    }

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


CHINA_TZ = timezone(timedelta(hours=8))


DEFAULT_POLICY = {
    "max_quote_time_gap_seconds": 20,
    "max_exact_match_time_gap_seconds": 60,
    "max_price_relative_diff_pct": 0.05,
    "max_change_diff_percentage_points": 0.10,
    "minimum_price_tick": 0.01,
    "market_close_time": "15:00:00",
}


USER_STATES = {
    "confirmed": "两路行情一致",
    "primary_only": "等待第二来源确认",
    "secondary_only": "主行情暂缺，仅作观察",
    "conflict": "两路行情存在差异",
    "date_mismatch": "两路行情日期不一致",
    "time_unaligned": "两路行情时间未对齐",
    "unavailable": "行情暂不可用",
}


def parse_quote_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=CHINA_TZ)
        return parsed.astimezone(CHINA_TZ)
    except ValueError:
        pass
    for pattern in ("%Y%m%d%H%M%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, pattern).replace(tzinfo=CHINA_TZ)
        except ValueError:
            continue
    return None


def valid_quote(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        return float(value.get("close")) > 0 and float(value.get("previous_close")) > 0 and parse_quote_time(value.get("as_of")) is not None
    except (TypeError, ValueError):
        return False


def change_pct(quote: dict[str, Any]) -> float:
    return (float(quote["close"]) / float(quote["previous_close"]) - 1) * 100


def is_same_day_close_pair(primary_at: datetime, secondary_at: datetime, close_time: str) -> bool:
    try:
        close_hour, close_minute, close_second = (int(part) for part in close_time.split(":"))
    except (TypeError, ValueError):
        close_hour, close_minute, close_second = (15, 0, 0)
    market_close = primary_at.replace(
        hour=close_hour,
        minute=close_minute,
        second=close_second,
        microsecond=0,
    )
    return (
        primary_at.date() == secondary_at.date()
        and primary_at >= market_close
        and secondary_at >= market_close
    )


def compare_quotes(
    primary: dict[str, Any] | None,
    secondary: dict[str, Any] | None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = {**DEFAULT_POLICY, **(policy or {})}
    primary_ok = valid_quote(primary)
    secondary_ok = valid_quote(secondary)
    if not primary_ok and not secondary_ok:
        return result("unavailable", rules)
    if primary_ok and not secondary_ok:
        return result("primary_only", rules, selected="primary")
    if secondary_ok and not primary_ok:
        return result("secondary_only", rules, selected="secondary")

    assert isinstance(primary, dict) and isinstance(secondary, dict)
    primary_at = parse_quote_time(primary.get("as_of"))
    secondary_at = parse_quote_time(secondary.get("as_of"))
    assert primary_at is not None and secondary_at is not None
    price_a = float(primary["close"])
    price_b = float(secondary["close"])
    previous_a = float(primary["previous_close"])
    previous_b = float(secondary["previous_close"])
    price_diff = abs(price_a - price_b)
    price_diff_pct = price_diff / max(abs(price_a), abs(price_b)) * 100
    previous_diff = abs(previous_a - previous_b)
    previous_diff_pct = previous_diff / max(abs(previous_a), abs(previous_b)) * 100
    change_diff = abs(change_pct(primary) - change_pct(secondary))
    time_gap = abs((primary_at - secondary_at).total_seconds())
    metrics = {
        "primary_quote_time": primary_at.isoformat(timespec="seconds"),
        "secondary_quote_time": secondary_at.isoformat(timespec="seconds"),
        "quote_time_gap_seconds": round(time_gap, 3),
        "price_difference": round(price_diff, 6),
        "price_difference_pct": round(price_diff_pct, 6),
        "previous_close_difference": round(previous_diff, 6),
        "previous_close_difference_pct": round(previous_diff_pct, 6),
        "change_difference_percentage_points": round(change_diff, 6),
    }
    if primary_at.date() != secondary_at.date():
        return result("date_mismatch", rules, selected="primary", metrics=metrics)
    tick = float(rules["minimum_price_tick"])
    price_matches = price_diff <= tick or price_diff_pct <= float(rules["max_price_relative_diff_pct"])
    previous_matches = previous_diff <= tick or previous_diff_pct <= float(rules["max_price_relative_diff_pct"])
    change_matches = change_diff <= float(rules["max_change_diff_percentage_points"])
    same_day_close_pair = is_same_day_close_pair(
        primary_at,
        secondary_at,
        str(rules["market_close_time"]),
    )
    metrics["comparison_basis"] = "same_day_close" if same_day_close_pair else "aligned_intraday"
    exact_value_match = price_diff <= 1e-9 and previous_diff <= 1e-9
    time_aligned = time_gap <= float(rules["max_quote_time_gap_seconds"])
    exact_match_time_aligned = (
        exact_value_match
        and time_gap <= float(rules["max_exact_match_time_gap_seconds"])
    )
    if not same_day_close_pair and not time_aligned and not exact_match_time_aligned:
        return result("time_unaligned", rules, selected="primary", metrics=metrics)
    state = "confirmed" if price_matches and previous_matches and change_matches else "conflict"
    return result(state, rules, selected="primary", metrics=metrics)


def result(
    state: str,
    rules: dict[str, Any],
    *,
    selected: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "state": state,
        "user_state": USER_STATES[state],
        "cross_source_verified": state == "confirmed",
        "selected_source": selected,
        "metrics": metrics or {},
        "policy": {
            "max_quote_time_gap_seconds": rules["max_quote_time_gap_seconds"],
            "max_exact_match_time_gap_seconds": rules["max_exact_match_time_gap_seconds"],
            "max_price_relative_diff_pct": rules["max_price_relative_diff_pct"],
            "max_change_diff_percentage_points": rules["max_change_diff_percentage_points"],
            "minimum_price_tick": rules["minimum_price_tick"],
            "market_close_time": rules["market_close_time"],
        },
    }

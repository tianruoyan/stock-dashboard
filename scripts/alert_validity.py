"""Read-only alert timing and verification checks shared by report gates.

Generation timestamps never renew an event. Existing five/fifteen-minute windows
are caps; an explicit deadline can shorten them, and an unknown deadline cannot
prove that a trigger is still current.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

TZ = timezone(timedelta(hours=8))
ALERT_CURRENT_SECONDS = 5 * 60
FUTURE_ALERT_TOLERANCE_SECONDS = 60


def parse_alert_timestamp(value: Any, *, require_timezone: bool = False) -> datetime | None:
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        if require_timezone:
            return None
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def alert_event_time(item: dict[str, Any], payload: dict[str, Any]) -> datetime | None:
    raw = item.get("time")
    parsed = parse_alert_timestamp(raw, require_timezone=True)
    if parsed is not None:
        return parsed
    if not isinstance(raw, str) or not re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", raw):
        return None
    # Legacy clock-only records retain their ID's original day when available.
    match = re.search(r"(?:^|[^\d])(\d{4})(\d{2})(\d{2})(?:[^\d]|$)", str(item.get("id") or ""))
    base = "-".join(match.groups()) if match else str(payload.get("timestamp") or "")[:10]
    return parse_alert_timestamp(f"{base}T{raw}+08:00")


def alert_time_state(item: Any, payload: dict[str, Any], now: datetime) -> str:
    """Return current, expired, unknown, closed, or invalidated without mutation."""
    if not isinstance(item, dict):
        return "unknown"
    if payload.get("source_status") == "invalidated" or item.get("confirmation_level") == "invalidated" or item.get("source_status") == "invalidated":
        return "invalidated"
    event = alert_event_time(item, payload)
    deadline = parse_alert_timestamp(item.get("valid_until"), require_timezone=True)
    now = now.astimezone(TZ)
    if event is None or deadline is None or deadline < event:
        return "unknown"
    age = (now - event).total_seconds()
    if age < -FUTURE_ALERT_TOLERANCE_SECONDS:
        return "unknown"
    window = 15 * 60 if item.get("signal_type") == "持续走强观察" else ALERT_CURRENT_SECONDS
    if now >= deadline or age > window:
        return "expired"
    if payload.get("source_status") == "monitor_session_closed" or item.get("source_status") == "monitor_session_closed":
        return "closed"
    return "current"


def alert_quote_audit(item: dict[str, Any], fallback: Any = None) -> dict[str, Any]:
    # An explicitly broken per-event audit must not inherit a healthy batch audit.
    audit = item.get("quote_audit") if "quote_audit" in item else fallback
    return audit if isinstance(audit, dict) else {}


def alert_quote_failed(audit: dict[str, Any]) -> bool:
    sanity = audit.get("sanity_checks")
    if isinstance(sanity, dict) and any(sanity.get(key) is False for key in ("price_move_valid", "volume_valid", "direction_ratio_valid")):
        return True
    verification = audit.get("secondary_verification")
    return isinstance(verification, dict) and verification.get("state") in {"mismatch", "failed", "error"}


def alert_cross_verified(audit: dict[str, Any]) -> bool:
    sanity = audit.get("sanity_checks")
    verification = audit.get("secondary_verification")
    secondary_passed = not isinstance(verification, dict) or verification.get("state") == "passed"
    return isinstance(sanity, dict) and sanity.get("cross_source_verified") is True and secondary_passed and not alert_quote_failed(audit)

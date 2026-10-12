"""Small shared validity checks for existing report builders."""
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))


def source_window(source, now=None):
    now = now or datetime.now(TZ)
    values = [source.get(k) for k in ("last_check", "checked_at", "as_of", "timestamp", "updated_at") if source.get(k)]
    stamps = []
    for value in values:
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if stamp.tzinfo is not None:
                stamps.append(stamp)
        except ValueError:
            pass
    if not stamps:
        return "unknown"
    age = (now - max(stamps)).total_seconds()
    if age < -120:
        return "unknown"
    return "current" if age <= 86400 else "history"


def risk_line(item):
    import re
    if item.get("type") == "risk_line" or item.get("role") == "risk_line":
        return True
    if item.get("type") in {"watch_line", "strong_line"}:
        return False
    return bool(re.search(r"风险线|相对弱势|退潮|排名居后|弱化", " ".join(str(item.get(k) or "") for k in ("name", "status", "continuity"))))


def topic_current(topic, day):
    stamp = str(topic.get("source_as_of") or topic.get("updated_at") or topic.get("timestamp") or "")
    if stamp[:10] != day:
        return False
    end = topic.get("valid_until")
    if end:
        try:
            deadline = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
            if deadline.tzinfo is None or deadline < datetime.now(TZ):
                return False
        except ValueError:
            return False
    return True


def iso_trade_date(value):
    """Accept an actual YYYY-MM-DD date, not a timestamp or a date-like substring."""
    import re
    from datetime import date
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return ""


def premarket_timing(data, now=None):
    """Separate a plan's target session from the time its analysis was written.

    This never creates quote timestamps or treats the target date as market evidence.
    Old files without an explicit target date keep their previous timestamp semantics.
    """
    now = (now or datetime.now(TZ)).astimezone(TZ)
    result = {"target_date": "", "date_field": "", "state": "", "auction_pending": False,
              "advance_plan": False}
    if not isinstance(data, dict):
        return result
    field = "trade_date" if "trade_date" in data else ("date" if "date" in data else "")
    if not field:
        return result
    target = iso_trade_date(data.get(field))
    result.update(target_date=target, date_field=field)
    if not target:
        result["state"] = "invalid_date"
        return result
    # Do not silently use the alias to hide a bad or conflicting explicit trade date.
    if field == "trade_date" and "date" in data and iso_trade_date(data.get("date")) != target:
        result["state"] = "invalid_date"
        return result
    try:
        stamp = datetime.fromisoformat(str(data.get("timestamp") or "").replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=TZ)
        stamp = stamp.astimezone(TZ)
    except ValueError:
        result["state"] = "invalid_timestamp"
        return result
    result["advance_plan"] = stamp.date().isoformat() < target
    auction_at = datetime.fromisoformat(target + "T09:25:00+08:00")
    result["auction_pending"] = now < auction_at and stamp <= now + timedelta(seconds=120)
    today = now.date().isoformat()
    if target > today:
        result["state"] = "upcoming"
    elif target < today or now.hour * 100 + now.minute >= 1130:
        result["state"] = "historical"
    else:
        context = data.get("market_context")
        status = " ".join(str(data.get(k) or "") for k in ("status", "data_status"))
        if isinstance(context, dict):
            status += " " + str(context.get("status") or "")
        waiting = any(word in status.lower() for word in ("waiting", "pending", "not_started", "unconfirmed", "等待", "待确认"))
        result["state"] = "awaiting_confirmation" if result["advance_plan"] or waiting or not isinstance(context, dict) else "current"
    return result

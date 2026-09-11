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

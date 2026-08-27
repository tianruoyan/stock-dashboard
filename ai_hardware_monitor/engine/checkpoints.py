from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def _minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":", 1))
    return hour * 60 + minute


def resolve_checkpoint(now: datetime, config: dict[str, Any], *, force: bool = False) -> dict[str, Any] | None:
    checkpoints = config.get("checkpoints") if isinstance(config, dict) else []
    checkpoints = checkpoints if isinstance(checkpoints, list) else []
    if not checkpoints:
        return None
    minute_of_day = now.hour * 60 + now.minute
    tolerance = int(config.get("tolerance_minutes") or 0)
    nearest = min(checkpoints, key=lambda item: abs(minute_of_day - _minutes(str(item["scheduled_at"]))))
    distance = minute_of_day - _minutes(str(nearest["scheduled_at"]))
    if force or 0 <= distance <= tolerance:
        return dict(nearest)
    return None


def next_checkpoint(now: datetime, config: dict[str, Any]) -> dict[str, Any] | None:
    checkpoints = config.get("checkpoints") if isinstance(config, dict) else []
    for item in checkpoints if isinstance(checkpoints, list) else []:
        scheduled = _minutes(str(item["scheduled_at"]))
        current = now.hour * 60 + now.minute
        if scheduled > current:
            return dict(item)
    return None


def scheduled_datetime(day: datetime, checkpoint: dict[str, Any]) -> datetime:
    hour, minute = (int(part) for part in str(checkpoint["scheduled_at"]).split(":", 1))
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)

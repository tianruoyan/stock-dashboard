from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from v2_platform.learning import TradingCalendar, load_json


@dataclass(frozen=True)
class CnTradingContext:
    market_date: date
    target_trade_date: date
    phase: str
    calendar_version: str


def resolve_cn_trading_context(root: Path, now: datetime, evidence_dates: Iterable[str] = ()) -> CnTradingContext:
    calendar = TradingCalendar(load_json(root / "config" / "v2-market-calendar.json"), "CN")
    latest_open = _open_on_or_before(calendar, now.date())
    verified_evidence = []
    for raw in evidence_dates:
        try:
            value = date.fromisoformat(str(raw))
        except ValueError:
            continue
        if value <= now.date() and calendar.is_open(value) is True:
            verified_evidence.append(value)
    market_date = max(verified_evidence) if verified_evidence else latest_open
    today_open = calendar.is_open(now.date()) is True
    target = now.date() if today_open else _open_after(calendar, now.date())
    return CnTradingContext(
        market_date=market_date,
        target_trade_date=target,
        phase=_phase(now, today_open),
        calendar_version=calendar.version,
    )


def _open_on_or_before(calendar: TradingCalendar, day: date) -> date:
    cursor = day
    for _ in range(20):
        state = calendar.is_open(cursor)
        if state is None:
            raise ValueError("calendar_unverified_or_outside_coverage")
        if state:
            return cursor
        cursor -= timedelta(days=1)
    raise ValueError("no_previous_open_day")


def _open_after(calendar: TradingCalendar, day: date) -> date:
    cursor = day + timedelta(days=1)
    for _ in range(20):
        state = calendar.is_open(cursor)
        if state is None:
            raise ValueError("calendar_unverified_or_outside_coverage")
        if state:
            return cursor
        cursor += timedelta(days=1)
    raise ValueError("no_next_open_day")


def _phase(now: datetime, today_open: bool) -> str:
    if not today_open:
        return "closed"
    hhmm = now.hour * 100 + now.minute
    if 830 <= hhmm < 930:
        return "premarket"
    if 930 <= hhmm < 1130:
        return "morning"
    if 1130 <= hhmm < 1300:
        return "midday"
    if 1300 <= hhmm < 1500:
        return "afternoon"
    if 1500 <= hhmm < 2000:
        return "postmarket"
    if hhmm >= 2000:
        return "evening"
    return "overnight"

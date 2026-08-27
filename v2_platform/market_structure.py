from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from v2_platform.learning import TradingCalendar, load_json


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class V2MarketStructureBuilder:
    def __init__(self, root: Path, *, today: date | None = None, now: datetime | None = None) -> None:
        self.root = root.resolve()
        resolved_now = now or datetime.now().astimezone()
        if resolved_now.tzinfo is None:
            resolved_now = resolved_now.astimezone()
        self.now = resolved_now
        self.today_was_explicit = today is not None
        self.today = today or resolved_now.date()
        self.config = load_json(self.root / "config" / "v2-market-structure-sources.json")
        self.calendar = TradingCalendar(load_json(self.root / "config" / "v2-market-calendar.json"), "CN")

    def build(self) -> dict[str, Any]:
        dimension = as_dict(as_dict(self.config.get("dimensions")).get("microcap"))
        input_path = self.root / str(dimension.get("input_path") or "data/v2/inputs/microcap-observation.json")
        payload = load_json(input_path)
        observations = as_list(payload.get("observations"))
        expected_date = self._latest_expected_trade_date()
        sources = as_dict(dimension.get("sources"))
        priority = [str(item) for item in as_list(dimension.get("source_priority"))]
        validated = [self._validate(item, sources, expected_date) for item in observations if isinstance(item, dict)]
        usable = [item for item in validated if item["quality_state"] == "usable"]
        usable.sort(key=lambda item: priority.index(item["source_id"]) if item["source_id"] in priority else len(priority))
        conflicts = self._conflicts(usable)
        selected = usable[0] if usable and not conflicts else None
        proxy = as_dict(sources.get("csi2000_official_proxy"))
        if selected:
            change = float(selected["change_pct"])
            direction = "up" if change > 0 else ("down" if change < 0 else "flat")
            state = "usable_proxy" if "proxy" in str(selected.get("kind") or "") or "proxy" in selected["source_id"] else "usable"
            conclusion = f"{selected['name']}最近交易日涨跌幅 {change:.2f}%；仅描述市场结构，不推断小登题材。"
        else:
            direction = "unknown"
            state = "conflict" if conflicts else "proxy_configured_data_pending"
            conclusion = "已配置中证2000观察代理，但缺少最近交易日的完整可审计行情；暂不判断微盘方向。"
        return {
            "schema_version": 1,
            "config_version": self.config.get("version"),
            "dimension": "microcap",
            "definition": dimension.get("definition"),
            "state": state,
            "direction": direction,
            "expected_trade_date": expected_date.isoformat() if expected_date else None,
            "selected_observation": selected,
            "conclusion": conclusion,
            "proxy": {
                "name": proxy.get("name"),
                "code": proxy.get("code"),
                "scope_note": proxy.get("scope"),
                "factsheet_url": proxy.get("factsheet_url"),
                "methodology_url": proxy.get("methodology_url"),
            },
            "source_states": [
                {"source_id": source_id, "status": as_dict(source).get("status"), "scope": as_dict(source).get("scope")}
                for source_id, source in sources.items()
            ],
            "observation_checks": validated,
            "conflicts": conflicts,
            "quality_policy": as_list(dimension.get("quality_policy")),
        }

    def _latest_expected_trade_date(self) -> date | None:
        cursor = self.today
        # Before today's market has closed, only yesterday's (or the prior open
        # day's) close is complete enough to validate a daily market-structure
        # observation. Explicit ``today`` values keep the deterministic legacy
        # behaviour used by historical builds and tests.
        if (
            not self.today_was_explicit
            and self.now.date() == cursor
            and self.calendar.is_open(cursor) is True
            and self.now.timetz().replace(tzinfo=None) < time(15, 5)
        ):
            cursor -= timedelta(days=1)
        for _ in range(15):
            state = self.calendar.is_open(cursor)
            if state is None:
                return None
            if state:
                return cursor
            cursor -= timedelta(days=1)
        return None

    @staticmethod
    def _validate(item: dict[str, Any], sources: dict[str, Any], expected_date: date | None) -> dict[str, Any]:
        source_id = str(item.get("source_id") or "")
        missing = [key for key in ("source_id", "trade_date", "as_of", "close", "change_pct", "source_url") if item.get(key) in (None, "")]
        flags = []
        if source_id not in sources:
            flags.append("unknown_source")
        try:
            trade_date = date.fromisoformat(str(item.get("trade_date")))
        except ValueError:
            trade_date = None
            flags.append("invalid_trade_date")
        try:
            as_of = datetime.fromisoformat(str(item.get("as_of")))
            if as_of.tzinfo is None:
                flags.append("timezone_missing")
        except ValueError:
            as_of = None
            flags.append("invalid_as_of")
        if expected_date and trade_date and trade_date != expected_date:
            flags.append("not_latest_expected_trade_date")
        for key in ("close", "change_pct"):
            if item.get(key) not in (None, "") and not isinstance(item.get(key), (int, float)):
                flags.append(f"{key}_not_numeric")
        if isinstance(item.get("close"), (int, float)) and item["close"] <= 0:
            flags.append("close_not_positive")
        quality = "usable" if not missing and not flags else "invalid"
        source = as_dict(sources.get(source_id))
        return {
            "source_id": source_id,
            "name": source.get("name") or source_id,
            "trade_date": trade_date.isoformat() if trade_date else item.get("trade_date"),
            "as_of": as_of.isoformat() if as_of else item.get("as_of"),
            "close": item.get("close"),
            "change_pct": item.get("change_pct"),
            "source_url": item.get("source_url"),
            "kind": source.get("kind"),
            "quality_state": quality,
            "missing_fields": missing,
            "quality_flags": sorted(set(flags)),
        }

    @staticmethod
    def _conflicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(items) < 2:
            return []
        rounded = {round(float(item["change_pct"]), 4) for item in items}
        if len(rounded) <= 1:
            return []
        return [{"field": "change_pct", "sources": [item["source_id"] for item in items], "values": sorted(rounded)}]

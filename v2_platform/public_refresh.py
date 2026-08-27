from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from v2_platform.learning import TradingCalendar, as_list, load_json, write_json
from v2_platform.microcap_collector import V2MicrocapCollector
from v2_platform.official_event_collector import V2OfficialEventCollector
from v2_platform.sentiment_collector import V2SentimentCollector


class V2PublicInputRefresher:
    def __init__(
        self,
        root: Path,
        *,
        microcap_collector: Callable[[date], dict[str, Any]] | None = None,
        sentiment_collector: Callable[[date], dict[str, Any]] | None = None,
        official_event_collector: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.input_dir = self.root / "local_inputs"
        self.calendar = TradingCalendar(load_json(self.root / "config" / "v2-market-calendar.json"), "CN")
        self.microcap_collector = microcap_collector or V2MicrocapCollector().collect
        self.sentiment_collector = sentiment_collector or V2SentimentCollector(self.root).collect
        self.official_event_collector = official_event_collector or V2OfficialEventCollector(self.root).collect

    def run(self, today: date | None = None, *, force: bool = False) -> dict[str, Any]:
        self.input_dir.mkdir(parents=True, exist_ok=True)
        trade_date = self._latest_open_day(today or date.today())
        rows = [
            self._refresh_market("microcap", "microcap-observation.json", trade_date, self.microcap_collector, force),
            self._refresh_market("sentiment", "sentiment-structure.json", trade_date, self.sentiment_collector, force),
            self._refresh_events(force),
        ]
        health_path = self.root / "data" / "v2" / "public-input-health.json"
        refreshed_ids = {str(item.get("id") or "") for item in rows}
        previous = load_json(health_path)
        carried_rows = [
            item
            for item in as_list(previous.get("collectors"))
            if isinstance(item, dict) and str(item.get("id") or "") not in refreshed_ids
        ]
        all_rows = rows + carried_rows
        report = {
            "schema_version": 1,
            "trade_date": trade_date.isoformat(),
            "state": "degraded" if any(item.get("state") == "failed" for item in all_rows) else "usable",
            "collectors": all_rows,
            "privacy_note": "只刷新公开市场和官方来源；不读取或发布本地持仓。",
        }
        write_json(health_path, report)
        return report

    def _refresh_market(
        self,
        collector_id: str,
        filename: str,
        trade_date: date,
        collector: Callable[[date], dict[str, Any]],
        force: bool,
    ) -> dict[str, Any]:
        path = self.input_dir / filename
        current = load_json(path)
        current_date = self._payload_trade_date(current)
        if not force and current_date == trade_date.isoformat():
            return {"id": collector_id, "state": "current", "trade_date": current_date, "detail": "existing_latest_trade_date"}
        try:
            payload = collector(trade_date)
            write_json(path, payload)
            return {"id": collector_id, "state": "updated", "trade_date": trade_date.isoformat(), "detail": "public_source_refreshed"}
        except Exception as exc:
            return {
                "id": collector_id,
                "state": "failed",
                "trade_date": current_date,
                "detail": f"{type(exc).__name__}:{str(exc)[:180]}",
                "previous_input_preserved": bool(current),
            }

    def _refresh_events(self, force: bool) -> dict[str, Any]:
        path = self.input_dir / "events.json"
        current = load_json(path)
        if not force and as_list(current.get("events")):
            return {"id": "official_events", "state": "current", "event_count": len(as_list(current.get("events"))), "detail": "existing_verified_seed"}
        try:
            payload = self.official_event_collector()
            existing = {item.get("event_id"): item for item in as_list(current.get("events")) if isinstance(item, dict) and item.get("event_id")}
            for item in as_list(payload.get("events")):
                if isinstance(item, dict) and item.get("event_id"):
                    existing[item["event_id"]] = item
            payload["events"] = sorted(existing.values(), key=lambda item: str(item.get("published_at") or ""), reverse=True)
            if not payload["events"]:
                raise ValueError("no_verified_official_events")
            write_json(path, payload)
            return {"id": "official_events", "state": "updated", "event_count": len(payload["events"]), "detail": payload.get("collection_state")}
        except Exception as exc:
            return {
                "id": "official_events",
                "state": "failed",
                "event_count": len(as_list(current.get("events"))),
                "detail": f"{type(exc).__name__}:{str(exc)[:180]}",
                "previous_input_preserved": bool(current),
            }

    def _latest_open_day(self, today: date) -> date:
        cursor = today
        for _ in range(15):
            state = self.calendar.is_open(cursor)
            if state is None:
                raise ValueError("calendar_unverified_or_outside_coverage")
            if state:
                return cursor
            cursor -= timedelta(days=1)
        raise ValueError("no_open_day_in_window")

    @staticmethod
    def _payload_trade_date(payload: dict[str, Any]) -> str | None:
        if payload.get("trade_date"):
            return str(payload["trade_date"])
        observations = as_list(payload.get("observations"))
        if observations and isinstance(observations[0], dict):
            return str(observations[0].get("trade_date") or "") or None
        return None

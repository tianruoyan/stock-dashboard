from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


class TradingCalendar:
    def __init__(self, config: dict[str, Any], market: str = "CN") -> None:
        rows = [item for item in as_list(config.get("calendars")) if isinstance(item, dict)]
        self.row = next((item for item in rows if item.get("market") == market), {})
        self.holidays = {date.fromisoformat(item) for item in as_list(self.row.get("holidays"))}
        self.extra_open = {date.fromisoformat(item) for item in as_list(self.row.get("extra_open_days"))}
        self.valid_from = date.fromisoformat(self.row["valid_from"]) if self.row.get("valid_from") else None
        self.valid_to = date.fromisoformat(self.row["valid_to"]) if self.row.get("valid_to") else None

    @property
    def version(self) -> str:
        return str(self.row.get("version") or "missing")

    @property
    def verified(self) -> bool:
        return self.row.get("verification_state") == "verified"

    def is_open(self, day: date) -> bool | None:
        if day in self.extra_open:
            return True
        if day.weekday() >= 5:
            return False
        if not self.verified or not self.valid_from or not self.valid_to or not self.valid_from <= day <= self.valid_to:
            return None
        return day not in self.holidays

    def advance(self, start: date, sessions: int) -> date | None:
        cursor = start
        found = 0
        for _ in range(370):
            cursor += timedelta(days=1)
            state = self.is_open(cursor)
            if state is None:
                return None
            if state:
                found += 1
                if found == sessions:
                    return cursor
        return None


class V2LearningBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.out_dir = self.root / "data" / "v2"
        self.policy = load_json(self.root / "config" / "v2-learning-policy.json")
        self.calendar = TradingCalendar(load_json(self.root / "config" / "v2-market-calendar.json"), str(self.policy.get("primary_market") or "CN"))
        self.prices = load_json(self.out_dir / "outcome-prices.json")

    def build(self, decision: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], Path]:
        snapshot = self._snapshot(decision)
        day = snapshot["decision_date"] or "unknown-date"
        path = self.out_dir / "snapshots" / day / f"{snapshot['snapshot_id']}.json"
        if not path.exists():
            write_json(path, snapshot)
        stored = load_json(path)
        index = self._index(stored, path)
        outcomes = self._resolve_outcomes(index)
        review = self._review(index, outcomes)
        write_json(self.out_dir / "replay-index.json", index)
        write_json(self.out_dir / "signal-outcomes.json", outcomes)
        write_json(self.out_dir / "signal-review.json", review)
        return index, review, path

    def _snapshot(self, decision: dict[str, Any]) -> dict[str, Any]:
        system = as_dict(decision.get("system"))
        as_of_raw = system.get("decision_as_of") or system.get("latest_source_at")
        try:
            decision_date = datetime.fromisoformat(str(as_of_raw)).date() if as_of_raw else None
        except ValueError:
            decision_date = None
        windows = [int(item) for item in as_list(self.policy.get("outcome_windows")) if int(item) > 0]
        stock_by_name = {
            item.get("name"): item
            for item in as_list(as_dict(decision.get("stock_pool")).get("stocks"))
            if isinstance(item, dict) and item.get("name")
        }
        signals = []
        for card in as_list(decision.get("opportunity_radar")):
            if not isinstance(card, dict):
                continue
            securities = []
            for raw in as_list(card.get("representative_stocks")):
                name = raw if isinstance(raw, str) else raw.get("name") if isinstance(raw, dict) else None
                ref = stock_by_name.get(name)
                securities.append({"name": name, "code": ref.get("code") if ref else None, "mapping_status": "mapped" if ref else "code_missing"})
            signals.append(
                {
                    "signal_id": card.get("id"),
                    "kind": card.get("kind"),
                    "state": card.get("state"),
                    "title": card.get("title"),
                    "trigger": card.get("trigger"),
                    "conclusion": card.get("conclusion"),
                    "action": card.get("action"),
                    "evidence": as_list(card.get("evidence")),
                    "counter_evidence": as_list(card.get("counter_evidence")),
                    "confirm_conditions": as_list(card.get("confirm_conditions")),
                    "invalidation_conditions": as_list(card.get("invalidation_conditions")),
                    "securities": securities,
                    "outcome_windows": self._window_rows(decision_date, windows),
                }
            )
        frozen = {
            "decision_as_of": as_of_raw,
            "decision_date": decision_date.isoformat() if decision_date else None,
            "quality": decision.get("data_quality_gate"),
            "market_environment": decision.get("market_environment"),
            "style_map": decision.get("style_map"),
            "signals": signals,
            "learning_policy_version": self.policy.get("version"),
            "calendar_version": self.calendar.version,
        }
        digest = stable_hash(frozen)
        return {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": f"snapshot_{digest[:20]}",
            "content_hash": digest,
            "created_at": now_iso(),
            **frozen,
        }

    def _index(self, snapshot: dict[str, Any], path: Path) -> dict[str, Any]:
        current = load_json(self.out_dir / "replay-index.json")
        entries = [item for item in as_list(current.get("snapshots")) if isinstance(item, dict)]
        ref = {
            "snapshot_id": snapshot.get("snapshot_id"),
            "decision_as_of": snapshot.get("decision_as_of"),
            "decision_date": snapshot.get("decision_date"),
            "quality_state": as_dict(snapshot.get("quality")).get("state"),
            "signal_count": len(as_list(snapshot.get("signals"))),
            "path": str(path.relative_to(self.root)),
            "content_hash": snapshot.get("content_hash"),
        }
        entries = [item for item in entries if item.get("snapshot_id") != ref["snapshot_id"]]
        entries.append(ref)
        entries.sort(key=lambda item: str(item.get("decision_as_of") or ""), reverse=True)
        return {
            "schema_version": SCHEMA_VERSION,
            "updated_at": now_iso(),
            "snapshot_count": len(entries),
            "snapshots": entries,
            "calendar_version": self.calendar.version,
            "learning_policy_version": self.policy.get("version"),
        }

    def _window_rows(self, decision_date: date | None, windows: list[int]) -> list[dict[str, Any]]:
        rows = []
        for window in windows:
            target = self.calendar.advance(decision_date, window) if decision_date else None
            rows.append(
                {
                    "window": f"T+{window}",
                    "target_date": target.isoformat() if target else None,
                    "status": "pending_data",
                    "result": None,
                }
            )
        return rows

    def _resolve_outcomes(self, index: dict[str, Any]) -> dict[str, Any]:
        observations = [item for item in as_list(self.prices.get("observations")) if isinstance(item, dict)]
        by_key = {
            (item.get("snapshot_id"), item.get("signal_id"), item.get("code")): item
            for item in observations
        }
        rows = []
        for ref in as_list(index.get("snapshots")):
            snapshot = load_json(self.root / str(ref.get("path")))
            for signal in as_list(snapshot.get("signals")):
                security_results = []
                for security in as_list(signal.get("securities")):
                    code = security.get("code") if isinstance(security, dict) else None
                    observation = by_key.get((snapshot.get("snapshot_id"), signal.get("signal_id"), code))
                    if not observation:
                        continue
                    reference_price = observation.get("reference_price")
                    reference_at = observation.get("reference_at")
                    source = observation.get("source")
                    windows = []
                    for planned in as_list(signal.get("outcome_windows")):
                        window = planned.get("window")
                        value = as_dict(as_dict(observation.get("windows")).get(window))
                        price = value.get("price")
                        if not isinstance(reference_price, (int, float)) or reference_price <= 0 or not isinstance(price, (int, float)):
                            windows.append({**planned, "status": "pending_data", "result": None})
                            continue
                        absolute_return = round((price / reference_price - 1) * 100, 4)
                        direction = "positive" if absolute_return > 0 else ("negative" if absolute_return < 0 else "flat")
                        supportive = (signal.get("kind") == "opportunity" and absolute_return > 0) or (signal.get("kind") == "risk" and absolute_return < 0)
                        windows.append(
                            {
                                **planned,
                                "status": "evaluated",
                                "result": {
                                    "price": price,
                                    "price_at": value.get("as_of"),
                                    "absolute_return_pct": absolute_return,
                                    "direction": direction,
                                    "signal_support": "supportive" if supportive else "not_supportive",
                                    "source": value.get("source") or source,
                                },
                            }
                        )
                    security_results.append(
                        {
                            "code": code,
                            "name": security.get("name"),
                            "reference_price": reference_price,
                            "reference_at": reference_at,
                            "source": source,
                            "windows": windows,
                        }
                    )
                rows.append(
                    {
                        "snapshot_id": snapshot.get("snapshot_id"),
                        "decision_date": snapshot.get("decision_date"),
                        "signal_id": signal.get("signal_id"),
                        "title": signal.get("title"),
                        "kind": signal.get("kind"),
                        "status": "partially_evaluated" if any(
                            window.get("status") == "evaluated"
                            for item in security_results for window in as_list(item.get("windows"))
                        ) else "pending_data",
                        "security_results": security_results,
                    }
                )
        evaluated_windows = sum(
            window.get("status") == "evaluated"
            for row in rows for item in as_list(row.get("security_results")) for window in as_list(item.get("windows"))
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "updated_at": now_iso(),
            "observation_schema": "snapshot_id + signal_id + code + reference_price/reference_at/source + windows[T+N]",
            "evaluated_window_count": evaluated_windows,
            "signals": rows,
        }

    def _review(self, index: dict[str, Any], outcomes: dict[str, Any]) -> dict[str, Any]:
        entries = as_list(index.get("snapshots"))
        outcome_signals = as_list(outcomes.get("signals"))
        evaluated = sum(item.get("status") == "partially_evaluated" for item in outcome_signals)
        total = sum(int(item.get("signal_count") or 0) for item in entries)
        pending = max(0, total - evaluated)
        min_samples = 20
        distinct_dates = {item.get("decision_date") for item in outcome_signals if item.get("status") == "partially_evaluated" and item.get("decision_date")}
        reveal = evaluated >= min_samples and len(distinct_dates) >= 20
        supports = [
            window.get("result", {}).get("signal_support") == "supportive"
            for row in outcome_signals
            for item in as_list(row.get("security_results"))
            for window in as_list(item.get("windows"))
            if window.get("status") == "evaluated"
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "collecting" if entries else "unavailable",
            "summary": f"已冻结 {len(entries)} 个判断快照、{pending} 条信号；结果窗口等待可审计价格数据。",
            "windows": [f"T+{item}" for item in as_list(self.policy.get("outcome_windows"))],
            "snapshot_count": len(entries),
            "pending_signal_count": pending,
            "evaluated_signal_count": evaluated,
            "hit_rate": round(sum(supports) / len(supports) * 100, 2) if reveal and supports else None,
            "hit_rate_state": "available" if reveal else "withheld_insufficient_samples_or_time_span",
            "guardrail": as_dict(self.policy.get("outcome_policy")).get("aggregate_guardrail"),
            "workflow": as_list(self.policy.get("workflow")),
            "items": entries[:10],
            "updated_at": now_iso(),
        }

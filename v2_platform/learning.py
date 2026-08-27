from __future__ import annotations

import hashlib
import json
from copy import deepcopy
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


def parse_iso(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


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
        self.primary_market = str(self.policy.get("primary_market") or "CN")
        self.calendar = TradingCalendar(load_json(self.root / "config" / "v2-market-calendar.json"), self.primary_market)
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
                raw_code = (
                    raw.get("stock_code") or raw.get("code")
                    if isinstance(raw, dict)
                    else None
                )
                code = raw_code or (ref.get("code") if ref else None)
                securities.append({
                    "name": name,
                    "code": code,
                    "mapping_status": "mapped" if code else "code_missing",
                })
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
            "primary_market": self.primary_market,
            "decision_as_of": as_of_raw,
            "decision_date": decision_date.isoformat() if decision_date else None,
            "quality": decision.get("data_quality_gate"),
            "market_environment": decision.get("market_environment"),
            "style_map": decision.get("style_map"),
            "signals": signals,
            "learning_policy_version": self.policy.get("version"),
            "decision_model_version": system.get("decision_model_version"),
            "calendar_version": self.calendar.version,
        }
        digest = stable_hash(self._semantic_snapshot(frozen))
        return {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": f"snapshot_{digest[:20]}",
            "content_hash": digest,
            "created_at": now_iso(),
            **frozen,
        }

    @staticmethod
    def _semantic_snapshot(frozen: dict[str, Any]) -> dict[str, Any]:
        """Exclude rebuild-clock metadata while retaining all decision facts and values."""
        semantic = deepcopy(frozen)
        quality = as_dict(semantic.get("quality"))
        for item in as_list(quality.get("evidence")):
            if isinstance(item, dict):
                item.pop("as_of", None)
        style = as_dict(semantic.get("style_map"))
        style.pop("as_of", None)
        for signal in as_list(semantic.get("signals")):
            if not isinstance(signal, dict):
                continue
            for item in as_list(signal.get("evidence")):
                if isinstance(item, dict) and (item.get("type") == "data_quality" or "quality-report.json" in str(item.get("source") or "")):
                    item.pop("as_of", None)
        return semantic

    def _index(self, snapshot: dict[str, Any], path: Path) -> dict[str, Any]:
        current = load_json(self.out_dir / "replay-index.json")
        entries = [item for item in as_list(current.get("snapshots")) if isinstance(item, dict)]
        ref = {
            "snapshot_id": snapshot.get("snapshot_id"),
            "primary_market": snapshot.get("primary_market") or self.primary_market,
            "decision_as_of": snapshot.get("decision_as_of"),
            "decision_date": snapshot.get("decision_date"),
            "quality_state": as_dict(snapshot.get("quality")).get("state"),
            "signal_count": len(as_list(snapshot.get("signals"))),
            "path": str(path.relative_to(self.root)),
            "content_hash": snapshot.get("content_hash"),
            "decision_model_version": snapshot.get("decision_model_version"),
            "created_at": snapshot.get("created_at"),
        }
        entries = [item for item in entries if item.get("snapshot_id") != ref["snapshot_id"]]
        entries.append(ref)
        entries = self._canonicalize_entries(entries)
        entries.sort(key=lambda item: str(item.get("decision_as_of") or ""), reverse=True)
        return {
            "schema_version": SCHEMA_VERSION,
            "updated_at": now_iso(),
            "snapshot_count": len(entries),
            "evaluation_snapshot_count": sum(item.get("evaluation_eligible") is True for item in entries),
            "snapshots": entries,
            "calendar_version": self.calendar.version,
            "learning_policy_version": self.policy.get("version"),
        }

    def _canonicalize_entries(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in entries:
            path = self.root / str(item.get("path") or "")
            snapshot = load_json(path)
            if not snapshot or not snapshot.get("snapshot_id"):
                continue
            market = str(snapshot.get("primary_market") or item.get("primary_market") or self.primary_market)
            as_of = snapshot.get("decision_as_of") or item.get("decision_as_of")
            model = snapshot.get("decision_model_version") or item.get("decision_model_version")
            canonical_key = f"{market}|{as_of or 'missing'}|{model or 'missing'}"
            semantic_hash = self._snapshot_semantic_hash(snapshot)
            contract_valid = bool(parse_iso(as_of) and model and isinstance(snapshot.get("signals"), list) and snapshot.get("signals"))
            normalized.append({
                **item,
                "snapshot_id": snapshot.get("snapshot_id"),
                "primary_market": market,
                "decision_as_of": as_of,
                "decision_date": snapshot.get("decision_date") or item.get("decision_date"),
                "decision_model_version": model,
                "created_at": snapshot.get("created_at") or item.get("created_at"),
                "signal_count": len(as_list(snapshot.get("signals"))),
                "semantic_hash": semantic_hash,
                "canonical_key": canonical_key,
                "contract_valid": contract_valid,
            })
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in normalized:
            groups.setdefault(str(item["canonical_key"]), []).append(item)
        result: list[dict[str, Any]] = []
        for rows in groups.values():
            eligible = [item for item in rows if item["contract_valid"]]
            canonical = max(eligible, key=lambda item: (str(item.get("created_at") or ""), str(item.get("snapshot_id") or ""))) if eligible else None
            canonical_id = canonical.get("snapshot_id") if canonical else None
            for item in rows:
                is_canonical = bool(canonical_id and item.get("snapshot_id") == canonical_id)
                result.append({
                    **item,
                    "canonical_snapshot_id": canonical_id,
                    "evaluation_eligible": is_canonical,
                    "variant_of": None if is_canonical else canonical_id,
                    "exclusion_reason": None if is_canonical else ("rebuild_variant" if canonical_id else "contract_invalid"),
                })
        return result

    def migrate_existing(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        current = load_json(self.out_dir / "replay-index.json")
        entries = [item for item in as_list(current.get("snapshots")) if isinstance(item, dict)]
        canonicalized = self._canonicalize_entries(entries)
        canonicalized.sort(key=lambda item: str(item.get("decision_as_of") or ""), reverse=True)
        index = {
            **current,
            "schema_version": SCHEMA_VERSION,
            "updated_at": now_iso(),
            "snapshot_count": len(canonicalized),
            "evaluation_snapshot_count": sum(item.get("evaluation_eligible") is True for item in canonicalized),
            "snapshots": canonicalized,
            "calendar_version": self.calendar.version,
            "learning_policy_version": self.policy.get("version"),
        }
        outcomes = self._resolve_outcomes(index)
        review = self._review(index, outcomes)
        write_json(self.out_dir / "replay-index.json", index)
        write_json(self.out_dir / "signal-outcomes.json", outcomes)
        write_json(self.out_dir / "signal-review.json", review)
        return index, outcomes, review

    @classmethod
    def _snapshot_semantic_hash(cls, snapshot: dict[str, Any]) -> str | None:
        if not snapshot:
            return None
        frozen = {
            key: snapshot.get(key)
            for key in (
                "primary_market", "decision_as_of", "decision_date", "quality", "market_environment", "style_map",
                "signals", "learning_policy_version", "decision_model_version", "calendar_version",
            )
        }
        return stable_hash(cls._semantic_snapshot(frozen))

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
        seen_signals: set[tuple[str, str]] = set()
        for ref in as_list(index.get("snapshots")):
            if not isinstance(ref, dict) or ref.get("evaluation_eligible") is not True:
                continue
            snapshot = load_json(self.root / str(ref.get("path")))
            for signal in as_list(snapshot.get("signals")):
                evaluation_key = (str(ref.get("canonical_key") or snapshot.get("snapshot_id")), str(signal.get("signal_id")))
                if evaluation_key in seen_signals:
                    continue
                seen_signals.add(evaluation_key)
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
                        "canonical_key": ref.get("canonical_key"),
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
        all_entries = [item for item in as_list(index.get("snapshots")) if isinstance(item, dict)]
        entries = [item for item in all_entries if item.get("evaluation_eligible") is True]
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
            "summary": f"已形成 {len(entries)} 个有效复盘样本、{pending} 条信号；结果窗口等待可审计价格数据。",
            "windows": [f"T+{item}" for item in as_list(self.policy.get("outcome_windows"))],
            "snapshot_count": len(entries),
            "raw_snapshot_count": len(all_entries),
            "excluded_variant_count": len(all_entries) - len(entries),
            "pending_signal_count": pending,
            "evaluated_signal_count": evaluated,
            "hit_rate": round(sum(supports) / len(supports) * 100, 2) if reveal and supports else None,
            "hit_rate_state": "available" if reveal else "withheld_insufficient_samples_or_time_span",
            "guardrail": as_dict(self.policy.get("outcome_policy")).get("aggregate_guardrail"),
            "workflow": as_list(self.policy.get("workflow")),
            "items": entries[:10],
            "updated_at": now_iso(),
        }

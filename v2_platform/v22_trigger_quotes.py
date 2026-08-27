from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2_platform.environment_evidence import canonical_hash, parse_datetime, stable_id, trade_date_of
from v2_platform.learning import as_dict, as_list, load_json, write_json


INDEX_OUTPUT = "data/v2/v22/trigger-quote-index.json"
REPORT_OUTPUT = "data/v2/v22/trigger-quote-capture-report.json"
SNAPSHOT_DIR = "data/v2/v22/trigger-quote-snapshots"
MAX_QUOTE_LAG_SECONDS = 15 * 60


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def market_of(code: str) -> str | None:
    normalized = str(code or "").lower()
    if normalized.startswith(("sh", "sz", "bj")):
        return "CN"
    if normalized.startswith("hk"):
        return "HK"
    return None


def state_material(case: dict[str, Any]) -> dict[str, Any]:
    """Only substantive decision fields participate; rebuild clocks and prices do not."""
    representatives = [
        {
            "code": item.get("stock_code") or item.get("code"),
            "name": item.get("name"),
            "role": item.get("role"),
        }
        for item in as_list(case.get("representative_stocks"))
        if isinstance(item, dict)
    ]
    return {
        "case_id": case.get("case_id"),
        "title": case.get("title"),
        "business_path": case.get("business_path"),
        "signal_state": case.get("signal_state"),
        "maturity": case.get("maturity"),
        "ended": bool(case.get("ended")),
        "current_judgment": case.get("current_judgment"),
        "trigger": case.get("trigger"),
        "risk_factors": as_list(case.get("risk_factors")),
        "confirm_conditions": as_list(case.get("confirm_conditions")),
        "invalidation_conditions": as_list(case.get("invalidation_conditions")),
        "representatives": representatives,
        "environment_result": as_dict(case.get("environment_gate")).get("g5_result"),
        "gate_states": [
            {"gate_id": item.get("gate_id"), "state": item.get("state")}
            for item in as_list(case.get("gates"))
            if isinstance(item, dict)
        ],
    }


class V22TriggerQuoteCapture:
    """Freeze the first auditable quote observed for a case state; never backfill history."""

    def __init__(self, root: Path, *, max_quote_lag_seconds: int = MAX_QUOTE_LAG_SECONDS) -> None:
        self.root = root.resolve()
        self.max_quote_lag_seconds = max_quote_lag_seconds
        self.cases = load_json(self.root / "data/v2/v22/decision-cases.json")
        self.quote_input = load_json(self.root / "data/v2/inputs/representative-stock-quotes.json")
        self.index = load_json(self.root / INDEX_OUTPUT)

    def capture(self) -> tuple[dict[str, Any], dict[str, Any]]:
        existing_rows = [item for item in as_list(self.index.get("snapshots")) if isinstance(item, dict)]
        existing_state_keys = {
            (str(item.get("trade_date")), str(item.get("case_id")), str(item.get("state_hash")))
            for item in existing_rows
        }
        case_ids_with_capture = {str(item.get("case_id")) for item in existing_rows}
        quote_by_code = {
            str(item.get("code")): item
            for item in as_list(self.quote_input.get("quotes"))
            if isinstance(item, dict) and item.get("code")
        }
        observed_at = self.cases.get("built_at")
        observed_stamp = parse_datetime(observed_at)
        trade_date = str(self.cases.get("trade_date") or "")
        holds: Counter[str] = Counter()
        created: list[dict[str, Any]] = []

        for case in as_list(self.cases.get("cases")):
            if not isinstance(case, dict) or not case.get("case_id"):
                continue
            case_id = str(case["case_id"])
            state_hash = canonical_hash(state_material(case))
            if (trade_date, case_id, state_hash) in existing_state_keys:
                holds["same_state_already_captured"] += 1
                continue
            if case.get("ended") and case_id not in case_ids_with_capture:
                holds["historical_case_without_prior_capture"] += 1
                continue
            if not observed_stamp or trade_date_of(observed_at) != trade_date:
                holds["case_observation_date_mismatch"] += 1
                continue
            representatives = [item for item in as_list(case.get("representative_stocks")) if isinstance(item, dict)]
            if not representatives:
                holds["representative_stock_missing"] += 1
                continue
            frozen_quotes: list[dict[str, Any]] = []
            quote_problem = None
            for representative in representatives:
                code = str(representative.get("stock_code") or representative.get("code") or "")
                quote = quote_by_code.get(code)
                if not quote:
                    quote_problem = "representative_quote_missing"
                    break
                quote_at = quote.get("stock_quote_as_of")
                quote_stamp = parse_datetime(quote_at)
                price = quote.get("close")
                previous = quote.get("previous_close")
                change_pct = quote.get("stock_change_pct")
                if not quote_stamp or trade_date_of(quote_at) != trade_date:
                    quote_problem = "quote_trade_date_mismatch"
                    break
                if abs((observed_stamp - quote_stamp).total_seconds()) > self.max_quote_lag_seconds:
                    quote_problem = "quote_not_near_first_observation"
                    break
                if not isinstance(price, (int, float)) or price <= 0 or not isinstance(previous, (int, float)) or previous <= 0 or not isinstance(change_pct, (int, float)):
                    quote_problem = "quote_fields_incomplete"
                    break
                recomputed = (float(price) / float(previous) - 1) * 100
                if abs(recomputed - float(change_pct)) > 0.05:
                    quote_problem = "stock_change_pct_not_from_quote"
                    break
                market = market_of(code)
                if not market:
                    quote_problem = "unsupported_market"
                    break
                frozen_quotes.append({
                    "code": code,
                    "name": quote.get("name") or representative.get("name"),
                    "market": market,
                    "trigger_price": float(price),
                    "previous_close": float(previous),
                    "stock_change_pct": round(float(change_pct), 4),
                    "quote_time": quote_at,
                    "source_id": quote.get("stock_quote_source_id") or self.quote_input.get("source_id"),
                    "source_label": quote.get("stock_quote_source") or self.quote_input.get("source_label"),
                    "collected_at": self.quote_input.get("generated_at"),
                    "verification_state": quote.get("stock_quote_verification") or "未提供第二来源状态",
                    "cross_source_verified": quote.get("cross_source_verified") is True,
                    "quality_state": "dual_source_confirmed" if quote.get("cross_source_verified") is True else "single_source_observation",
                })
                if not frozen_quotes[-1]["source_id"] or not frozen_quotes[-1]["source_label"] or not frozen_quotes[-1]["collected_at"]:
                    quote_problem = "quote_source_or_collection_time_missing"
                    break
            if quote_problem:
                holds[quote_problem] += 1
                continue

            snapshot_id = stable_id("trigger_quote_snapshot", case_id, state_hash, canonical_hash(frozen_quotes))
            snapshot: dict[str, Any] = {
                "schema_version": 1,
                "snapshot_id": snapshot_id,
                "mode": "shadow_only",
                "case_id": case_id,
                "case_batch_id": self.cases.get("case_batch_id"),
                "case_content_hash": canonical_hash(case),
                "state_hash": state_hash,
                "state_observed_at": observed_at,
                "source_evidence_at": case.get("last_evidence_at"),
                "trade_date": trade_date,
                "signal_state": case.get("signal_state"),
                "maturity": case.get("maturity"),
                "kind": "risk" if case.get("business_path") == "risk_path" else "opportunity",
                "capture_kind": "first_system_observation_of_case_state",
                "representative_quotes": frozen_quotes,
                "created_at": now_iso(),
                "guardrails": {
                    "historical_quote_backfilled": False,
                    "theme_change_used_as_stock_change": False,
                    "user_assets_modified": False,
                    "automatic_trade": False,
                },
            }
            immutable_material = {key: value for key, value in snapshot.items() if key not in {"created_at", "immutable_hash"}}
            snapshot["immutable_hash"] = canonical_hash(immutable_material)
            path = self.root / SNAPSHOT_DIR / trade_date / f"{snapshot_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                stored = load_json(path)
                if stored.get("immutable_hash") != snapshot["immutable_hash"]:
                    raise ValueError("immutable trigger quote snapshot conflict")
            else:
                write_json(path, snapshot)
            row = {
                "snapshot_id": snapshot_id,
                "case_id": case_id,
                "case_batch_id": self.cases.get("case_batch_id"),
                "state_hash": state_hash,
                "trade_date": trade_date,
                "state_observed_at": observed_at,
                "quote_count": len(frozen_quotes),
                "relative_path": str(path.relative_to(self.root)),
                "immutable_hash": snapshot["immutable_hash"],
            }
            existing_rows.append(row)
            existing_state_keys.add((trade_date, case_id, state_hash))
            case_ids_with_capture.add(case_id)
            created.append(row)

        deduped = {str(item.get("snapshot_id")): item for item in existing_rows if item.get("snapshot_id")}
        rows = sorted(deduped.values(), key=lambda item: (str(item.get("state_observed_at") or ""), str(item.get("snapshot_id") or "")))
        index = {
            "schema_version": 1,
            "generated_at": now_iso(),
            "mode": "shadow_only",
            "snapshot_count": len(rows),
            "current_case_batch_id": self.cases.get("case_batch_id"),
            "snapshots": rows,
            "guardrails": {
                "historical_quotes_backfilled": False,
                "same_state_duplicate_created": False,
                "user_assets_modified": False,
            },
        }
        report = {
            "schema_version": 1,
            "generated_at": now_iso(),
            "mode": "shadow_only",
            "case_count": len(as_list(self.cases.get("cases"))),
            "created_snapshot_count": len(created),
            "total_snapshot_count": len(rows),
            "hold_count": sum(holds.values()),
            "hold_reasons": dict(sorted(holds.items())),
            "summary": "当前没有同交易日、近触发时点的完整代表股行情，继续等待。" if not created else f"新增{len(created)}个可审计触发行情快照。",
            "guardrails": index["guardrails"],
        }
        write_json(self.root / INDEX_OUTPUT, index)
        write_json(self.root / REPORT_OUTPUT, report)
        return index, report

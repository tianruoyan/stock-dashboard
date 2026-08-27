from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2_platform.learning import load_json, parse_iso, write_json
from v2_platform.publishing import PublishPolicy


PUBLIC_RESULT_PATHS = (
    "data/premarket.json",
    "data/intraday.json",
    "data/alert.json",
    "data/midday.json",
    "data/postmarket.json",
    "data/evening-sentiment.json",
    "data/topics.json",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sensitive_hits(value: Any, blocked: set[str], prefix: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key) in blocked:
                hits.append(path)
            hits.extend(sensitive_hits(child, blocked, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(sensitive_hits(child, blocked, f"{prefix}[{index}]"))
    return hits


def effective_time(payload: dict[str, Any]) -> datetime | None:
    """Return the time of the analysis decision, not the latest quote refresh.

    V1's no-model market updater is allowed to refresh ``market_data_as_of``
    without changing the written analysis.  Treating that quote timestamp as
    the decision time would make a previous-day conclusion look current and
    could overwrite a genuinely newer V2 decision.
    """
    candidates = [
        payload.get("timestamp"),
        payload.get("as_of"),
        payload.get("current_signal_date"),
        payload.get("target_trade_date"),
    ]
    parsed: list[datetime] = []
    for value in candidates:
        item = parse_iso(value)
        if item:
            parsed.append(item)
            continue
        try:
            day = datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc).astimezone()
        except (TypeError, ValueError):
            continue
        parsed.append(day)
    return max(parsed) if parsed else None


def market_data_time(payload: dict[str, Any]) -> datetime | None:
    return parse_iso(payload.get("market_data_as_of"))


class V1PublicBaselineImporter:
    """Copy only governed public V1 result files into V2 for same-day comparison."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        rollout = load_json(self.root / "config/v2-rollout.json")
        production = rollout.get("production_v1") if isinstance(rollout.get("production_v1"), dict) else {}
        self.source_root = Path(str(production.get("path") or "")).expanduser().resolve()
        policy = PublishPolicy.load(self.root / "config/v2-publish-policy.json")
        self.sensitive_keys = set(policy.sensitive_json_keys)

    def run(self, *, dry_run: bool = False) -> dict[str, Any]:
        rows = []
        imported = 0
        for relative in PUBLIC_RESULT_PATHS:
            source = self.source_root / relative
            target = self.root / relative
            source_payload = load_json(source)
            target_payload = load_json(target)
            if not source_payload:
                rows.append({"path": relative, "state": "source_missing_or_invalid"})
                continue
            retained_alert_history = False
            if relative == "data/alert.json":
                source_payload = deepcopy(source_payload)
                current_alerts = source_payload.get("alerts") if isinstance(source_payload.get("alerts"), list) else []
                current_ids = {
                    str(item.get("id"))
                    for item in current_alerts
                    if isinstance(item, dict) and item.get("id") not in (None, "")
                }
                history_candidates = []
                for key in ("historical_alerts", "alerts"):
                    rows_to_keep = target_payload.get(key) if isinstance(target_payload.get(key), list) else []
                    history_candidates.extend(deepcopy(rows_to_keep))
                historical_alerts = []
                seen_history_ids: set[str] = set()
                for item in history_candidates:
                    if not isinstance(item, dict):
                        continue
                    item_id = str(item.get("id") or "")
                    if item_id and (item_id in current_ids or item_id in seen_history_ids):
                        continue
                    if item_id:
                        seen_history_ids.add(item_id)
                    historical_alerts.append(item)
                if historical_alerts:
                    source_payload["historical_alerts"] = historical_alerts
                    source_payload["history_retained"] = True
                    retained_alert_history = True
                    if not current_alerts:
                        source_payload["note"] = (
                            str(source_payload.get("note") or "").rstrip("。")
                            + "；V2仅保留此前已落盘的过期触发供复盘，不作为今天盘中异动。"
                        ).lstrip("；")
            hits = sensitive_hits(source_payload, self.sensitive_keys)
            if hits:
                rows.append({"path": relative, "state": "blocked_sensitive_fields", "hits": hits[:12]})
                continue
            source_at = effective_time(source_payload)
            target_at = effective_time(target_payload)
            source_market_at = market_data_time(source_payload)
            target_market_at = market_data_time(target_payload)
            if source_at and target_at and source_at < target_at:
                rows.append({
                    "path": relative,
                    "state": "kept_newer_destination",
                    "source_as_of": source_at.isoformat(timespec="seconds"),
                    "destination_as_of": target_at.isoformat(timespec="seconds"),
                    "source_market_data_as_of": source_market_at.isoformat(timespec="seconds") if source_market_at else None,
                    "destination_market_data_as_of": target_market_at.isoformat(timespec="seconds") if target_market_at else None,
                })
                continue
            if stable_hash(source_payload) == stable_hash(target_payload):
                rows.append({"path": relative, "state": "unchanged"})
                continue
            if not dry_run:
                write_json(target, source_payload)
            imported += 1
            rows.append({
                "path": relative,
                "state": "would_import_with_alert_history" if dry_run and retained_alert_history else (
                    "imported_with_alert_history" if retained_alert_history else ("would_import" if dry_run else "imported")
                ),
                "source_as_of": source_at.isoformat(timespec="seconds") if source_at else None,
                "source_market_data_as_of": source_market_at.isoformat(timespec="seconds") if source_market_at else None,
            })
        report = {
            "schema_version": 1,
            "generated_at": now_iso(),
            "mode": "governed_public_read_only_import",
            "source_root": str(self.source_root),
            "imported_count": imported,
            "files": rows,
            "guardrails": {
                "v1_files_modified": False,
                "user_assets_read": False,
                "user_assets_modified": False,
                "private_fields_imported": False,
                "older_source_overwrote_newer_destination": False,
                "quote_refresh_treated_as_new_analysis": False,
            },
        }
        if not dry_run:
            write_json(self.root / "data/v2/v22/v1-public-baseline-import.json", report)
        return report

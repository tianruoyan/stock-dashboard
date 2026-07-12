from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from v2_platform.learning import as_dict, as_list, load_json, write_json


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def content_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def timezone_valid(value: Any) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return False
    return parsed.tzinfo is not None


class V2InputImporter:
    TIME_FIELDS = {"as_of", "published_at", "observed_at", "reference_at"}

    def __init__(self, root: Path, input_dir: Path | None = None) -> None:
        self.root = root.resolve()
        self.config = load_json(self.root / "config" / "v2-input-contracts.json")
        default = self.root / str(self.config.get("default_input_dir") or "local_inputs")
        self.input_dir = (input_dir or default).resolve()

    def run(self) -> dict[str, Any]:
        rows = [self._process(item) for item in as_list(self.config.get("contracts")) if isinstance(item, dict)]
        report = {
            "schema_version": 1,
            "contract_version": self.config.get("version"),
            "imported_at": now_iso(),
            "input_dir": str(self.input_dir),
            "status": "invalid" if any(item["status"] == "invalid" for item in rows) else ("updated" if any(item["status"] == "updated" for item in rows) else "no_change"),
            "contracts": rows,
            "safety_rules": as_list(self.config.get("safety_rules")),
        }
        manifest_path = self.root / str(self.config.get("manifest_path") or "data/v2/input-import-manifest.json")
        write_json(manifest_path, report)
        return report

    def _process(self, contract: dict[str, Any]) -> dict[str, Any]:
        contract_id = str(contract.get("id") or "unknown")
        source = self.input_dir / str(contract.get("filename") or "")
        target = self.root / str(contract.get("target") or "")
        base = {"id": contract_id, "source": source.name, "target": str(target.relative_to(self.root))}
        if not source.exists():
            return {**base, "status": "pending", "detail": "input_file_missing", "content_hash": None}
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except Exception as exc:
            return {**base, "status": "invalid", "detail": f"invalid_json:{type(exc).__name__}", "content_hash": None}
        if not isinstance(payload, dict):
            return {**base, "status": "invalid", "detail": "top_level_not_object", "content_hash": None}
        issues = self._validate(contract, payload)
        digest = content_hash(payload)
        if issues:
            return {**base, "status": "invalid", "detail": "validation_failed", "issues": issues, "content_hash": digest}
        current = load_json(target)
        if current and content_hash(current) == digest:
            return {**base, "status": "unchanged", "detail": "same_content", "content_hash": digest}
        write_json(target, payload)
        return {**base, "status": "updated", "detail": "validated_and_imported", "content_hash": digest}

    def _validate(self, contract: dict[str, Any], payload: dict[str, Any]) -> list[str]:
        issues = []
        for field in as_list(contract.get("required_fields")):
            if payload.get(field) in (None, ""):
                issues.append(f"missing:{field}")
        list_name = contract.get("top_level_list")
        if list_name:
            items = payload.get(list_name)
            if not isinstance(items, list):
                issues.append(f"not_list:{list_name}")
                items = []
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    issues.append(f"{list_name}[{index}]:not_object")
                    continue
                for field in as_list(contract.get("required_item_fields")):
                    if item.get(field) in (None, ""):
                        issues.append(f"{list_name}[{index}]:missing:{field}")
                issues.extend(self._validate_time_fields(item, f"{list_name}[{index}]") )
        issues.extend(self._validate_time_fields(payload, "root"))
        if contract.get("id") == "microcap_observation":
            for index, item in enumerate(as_list(payload.get("observations"))):
                if isinstance(item, dict):
                    try:
                        date.fromisoformat(str(item.get("trade_date")))
                    except ValueError:
                        issues.append(f"observations[{index}]:invalid_trade_date")
                    if not isinstance(item.get("close"), (int, float)) or float(item.get("close") or 0) <= 0:
                        issues.append(f"observations[{index}]:invalid_close")
                    if not isinstance(item.get("change_pct"), (int, float)):
                        issues.append(f"observations[{index}]:invalid_change_pct")
        if contract.get("id") == "sentiment_structure":
            for key in ("limit_up_ladder", "limit_down_ladder"):
                value = payload.get(key)
                if not isinstance(value, dict) or not isinstance(value.get("items"), list):
                    issues.append(f"invalid_ladder:{key}")
        if contract.get("id") == "portfolio_context":
            if not isinstance(payload.get("holdings"), list):
                issues.append("holdings:not_list")
        return sorted(set(issues))

    def _validate_time_fields(self, value: dict[str, Any], prefix: str) -> list[str]:
        issues = []
        for field in self.TIME_FIELDS:
            if field in value and value.get(field) not in (None, "") and not timezone_valid(value.get(field)):
                issues.append(f"{prefix}:timezone_required:{field}")
        windows = value.get("windows")
        if isinstance(windows, dict):
            for key, item in windows.items():
                if isinstance(item, dict) and item.get("as_of") and not timezone_valid(item.get("as_of")):
                    issues.append(f"{prefix}:windows[{key}]:timezone_required:as_of")
        return issues

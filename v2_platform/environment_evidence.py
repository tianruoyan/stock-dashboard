from __future__ import annotations

import hashlib
import json
from datetime import datetime, time
from typing import Any, Iterable


def stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return parse_compact_quote_time(raw)
    return parsed if parsed.tzinfo else None


def parse_compact_quote_time(value: str) -> datetime | None:
    raw = str(value or "").strip()
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M"):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return parsed.astimezone() if parsed.tzinfo else parsed.replace().astimezone()
    return None


def normalize_quote_time(value: Any, *, timezone_suffix: str = "+08:00") -> str | None:
    raw = str(value or "").strip()
    if len(raw) in {12, 14} and raw.isdigit():
        fmt = "%Y%m%d%H%M%S" if len(raw) == 14 else "%Y%m%d%H%M"
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            return None
        return f"{parsed.isoformat(timespec='seconds')}{timezone_suffix}"
    parsed = parse_datetime(raw)
    return parsed.isoformat(timespec="seconds") if parsed else None


def trade_date_of(value: Any) -> str | None:
    parsed = parse_datetime(value)
    return parsed.date().isoformat() if parsed else None


def infer_session_phase(value: Any) -> str:
    parsed = parse_datetime(value)
    if not parsed:
        return "unknown"
    current = parsed.timetz().replace(tzinfo=None)
    if current <= time(9, 14, 59):
        return "pre_market"
    if current <= time(9, 35):
        return "auction"
    if current <= time(11, 30):
        return "morning"
    if current <= time(12, 59, 59):
        return "midday"
    if current <= time(14, 59, 59):
        return "afternoon"
    if current <= time(18, 0):
        return "close"
    return "evening_plan"


def newest_time(values: Iterable[Any]) -> str | None:
    parsed = [item for value in values if (item := parse_datetime(value))]
    return max(parsed).isoformat(timespec="seconds") if parsed else None


def evidence_ref(
    *,
    snapshot_id: str,
    dimension_code: str,
    evidence_role: str,
    metric_name: str,
    metric_scope: str,
    metric_value: Any,
    unit: str | None,
    source_id: str,
    source_label: str,
    source_url: str | None,
    source_as_of: str,
    quality_state: str,
    rule_version: str | None = None,
    scope_definition: str | None = None,
    representative_securities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not parse_datetime(source_as_of):
        raise ValueError("environment evidence source_as_of must include timezone")
    ref_id = stable_id(
        "env_evidence",
        snapshot_id,
        dimension_code,
        evidence_role,
        metric_name,
        metric_scope,
        source_id,
        source_as_of,
        canonical_hash(metric_value),
    )
    return {
        "evidence_ref_id": ref_id,
        "environment_snapshot_id": snapshot_id,
        "dimension_code": dimension_code,
        "evidence_role": evidence_role,
        "metric_name": metric_name,
        "metric_scope": metric_scope,
        "metric_value": metric_value,
        "unit": unit,
        "source_id": source_id,
        "source_label": source_label,
        "source_url": source_url,
        "source_as_of": source_as_of,
        "trade_date": trade_date_of(source_as_of),
        "session_phase": infer_session_phase(source_as_of),
        "quality_state": quality_state,
        "rule_version": rule_version,
        "scope_definition": scope_definition,
        "representative_securities": representative_securities or [],
    }


def same_metric_conflicts(evidence: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str | None], list[dict[str, Any]]] = {}
    for item in evidence:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("dimension_code") or ""),
            str(item.get("metric_name") or ""),
            str(item.get("metric_scope") or ""),
            str(item.get("source_as_of") or ""),
            item.get("scope_definition"),
        )
        grouped.setdefault(key, []).append(item)
    conflicts = []
    for key, rows in grouped.items():
        values = {canonical_hash(row.get("metric_value")) for row in rows}
        sources = {str(row.get("source_id") or "") for row in rows}
        if len(values) <= 1 or len(sources) <= 1:
            continue
        conflicts.append({
            "conflict_id": stable_id("env_conflict", *key, *sorted(values)),
            "dimension_code": key[0],
            "metric_name": key[1],
            "source_as_of": key[3],
            "scope_definition": key[4],
            "values": [
                {"source_id": row.get("source_id"), "value": row.get("metric_value")}
                for row in rows
            ],
            "resolution": "保留全部原值；该维度不能用此指标升级。",
        })
    return conflicts


def dimension_state(
    *,
    snapshot_id: str,
    dimension_code: str,
    label: str,
    support_level: str,
    conclusion: str,
    fact_summary: list[str],
    counter_evidence: list[str],
    missing_evidence: list[str],
    quality_state: str,
    freshness_state: str,
    as_of: str,
    method_version: str,
    evidence_ref_ids: list[str],
) -> dict[str, Any]:
    return {
        "dimension_state_id": stable_id("env_dimension", snapshot_id, dimension_code),
        "environment_snapshot_id": snapshot_id,
        "dimension_code": dimension_code,
        "label": label,
        "scope_type": "market",
        "scope_id": None,
        "support_level": support_level,
        "conclusion": conclusion,
        "fact_summary": fact_summary,
        "counter_evidence": counter_evidence,
        "missing_evidence": missing_evidence,
        "quality_state": quality_state,
        "freshness_state": freshness_state,
        "as_of": as_of,
        "method_version": method_version,
        "evidence_ref_ids": evidence_ref_ids,
    }

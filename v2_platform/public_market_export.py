"""Local, allowlisted public facts projection. No acquisition, Git or network I/O."""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CHINA = ZoneInfo("Asia/Shanghai")
OUTPUT = "data/v2/v22/market-environment.json"
INPUTS = {
    "market_breadth": "local_inputs/market-breadth.json",
    "liquidity": "local_inputs/market-liquidity.json",
}
# The remaining projections have not passed a field/provenance privacy review.
UNAPPROVED = (
    "data/v2/decision-system.json",
    "data/v2/v22/decision-system-candidate.json",
    "data/v2/v22/environment-decision.json",
    "data/v2/v22/model-evaluation.json",
    "data/v2/v22/parallel-comparison.json",
    "data/v2/v22/replay-index.json",
    "data/v2/v22/stock-pool-shadow.json",
)
SOURCES = {
    "eastmoney_a_share_universe_live": "东方财富公开市场行情",
    "sina_a_share_universe_live": "新浪财经公开市场行情",
}
MAX_AGE_SECONDS = 1800
MAX_INPUT_BYTES = 1_000_000


class ExportBlocked(ValueError):
    """Only stable reason codes; never include rejected private values."""


def _path(root: Path, relative: str) -> Path:
    path = root
    for part in Path(relative).parts:
        if part in {"..", "."} or Path(relative).is_absolute():
            raise ExportBlocked("invalid_path")
        path = path / part
        if path.is_symlink():
            raise ExportBlocked("symlink_not_allowed")
    if not path.resolve().is_relative_to(root):
        raise ExportBlocked("path_outside_root")
    return path


def _read(root: Path, relative: str) -> dict[str, Any]:
    path = _path(root, relative)
    try:
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ExportBlocked("oversize_json")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, ExportBlocked):
            raise
        raise ExportBlocked("missing_or_invalid_json") from None
    if not isinstance(value, dict):
        raise ExportBlocked("json_object_required")
    return value


def _time(raw: Any) -> datetime:
    if not isinstance(raw, str):
        raise ExportBlocked("source_as_of_required")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise ExportBlocked("source_as_of_invalid") from None
    if parsed.tzinfo is None:
        raise ExportBlocked("source_timezone_required")
    return parsed.astimezone(CHINA)


def _number(value: Any, *, maximum: float | None = None, integer: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ExportBlocked("invalid_numeric_fact")
    if maximum is not None and value > maximum:
        raise ExportBlocked("numeric_fact_out_of_range")
    if integer and not isinstance(value, int):
        raise ExportBlocked("integer_fact_required")
    return value


def build_public_market_facts(source: Path, now: datetime) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ExportBlocked("clock_timezone_required")
    now = now.astimezone(CHINA)
    source = source.resolve()
    health = _read(source, "data/v2/public-market-fact-health.json")
    guardrails = health.get("guardrails")
    if not isinstance(guardrails, dict) or guardrails.get("public_sources_only") is not True or guardrails.get("user_assets_read") is not False or guardrails.get("user_assets_modified") is not False:
        raise ExportBlocked("public_provenance_unverified")
    if health.get("state") not in {"usable", "degraded"} or guardrails.get("retained_previous_same_day_facts"):
        raise ExportBlocked("source_not_refreshed")
    if health.get("trade_date") != now.date().isoformat():
        raise ExportBlocked("collector_trade_date_mismatch")
    raw = {key: _read(source, path) for key, path in INPUTS.items()}
    times = {}
    for key, row in raw.items():
        at = _time(row.get("as_of"))
        age = (now - at).total_seconds()
        if at.date() != now.date() or row.get("trade_date") != at.date().isoformat():
            raise ExportBlocked("source_trade_date_mismatch")
        if age < 0:
            raise ExportBlocked("source_in_future")
        if age > MAX_AGE_SECONDS:
            raise ExportBlocked("source_stale")
        if row.get("quality_state") not in {"usable", "degraded"}:
            raise ExportBlocked("source_quality_unverified")
        times[key] = at
    breadth, liquidity = raw["market_breadth"], raw["liquidity"]
    base_source = breadth.get("source_id")
    if base_source not in SOURCES or liquidity.get("source_id") != base_source + "_turnover":
        raise ExportBlocked("public_source_not_allowlisted")
    if times["market_breadth"] != times["liquidity"]:
        raise ExportBlocked("source_snapshot_mismatch")
    if breadth.get("universe_definition_id") != "cn_a_sh_sz_bj_valid_quote_v2" or liquidity.get("unit") != "亿元":
        raise ExportBlocked("fact_scope_unverified")
    counts = {key: _number(breadth.get(key), maximum=20000, integer=True) for key in ("advance_count", "decline_count", "flat_count", "total_count", "missing_quote_count")}
    if counts["total_count"] < 1 or counts["advance_count"] + counts["decline_count"] + counts["flat_count"] != counts["total_count"]:
        raise ExportBlocked("breadth_counts_inconsistent")
    turnover = _number(liquidity.get("total_turnover"))
    as_of = breadth["as_of"]  # Preserve the source's literal timestamp, never build time.
    day = breadth["trade_date"]
    boundary = "仅公开上涨下跌家数和累计成交；其他市场依据未同步，不能据此判断交易机会。"
    metrics = {
        "market_breadth": [("advance_count", "上涨家数", counts["advance_count"], "家"), ("decline_count", "下跌家数", counts["decline_count"], "家"), ("flat_count", "平盘家数", counts["flat_count"], "家")],
        "liquidity": [("total_turnover", "累计成交额", turnover, "亿元")],
    }
    facts = {
        "market_breadth": f"上涨{counts['advance_count']}家，下跌{counts['decline_count']}家，平盘{counts['flat_count']}家；有效样本{counts['total_count']}家。",
        "liquidity": f"当前累计成交额{turnover:g}亿元；未提供同时间历史基线。",
    }
    labels = {"market_breadth": "上涨与下跌家数", "liquidity": "全市场累计成交"}
    dimensions, evidence, status = [], [], []
    for key in INPUTS:
        source_id = raw[key]["source_id"]
        refs = []
        for metric, label, value, unit in metrics[key]:
            ref = "public_" + metric
            refs.append(ref)
            evidence.append({"evidence_ref_id": ref, "dimension_code": key, "metric_name": label, "metric_value": value, "unit": unit, "source_id": source_id, "source_label": SOURCES[base_source], "source_as_of": raw[key]["as_of"], "trade_date": day, "quality_state": raw[key]["quality_state"], "representative_securities": []})
        dimensions.append({"dimension_code": key, "label": labels[key], "scope_type": "market", "support_level": "unknown", "conclusion": "公开事实已更新，交易含义尚未确认。", "fact_summary": [facts[key]], "counter_evidence": [boundary], "missing_evidence": ["其他市场维度及判断未同步"], "quality_state": raw[key]["quality_state"], "as_of": raw[key]["as_of"], "evidence_ref_ids": refs})
        status.append({"label": labels[key], "source_id": source_id, "state": raw[key]["quality_state"], "as_of": raw[key]["as_of"], "note": "仅此公开事实来源已同步。"})
    return {
        "schema_version": 1, "mode": "partial_public_facts", "facts_only": True,
        "trade_date": day, "as_of": as_of, "built_at": now.isoformat(timespec="seconds"),
        "primary_state": "unknown", "action_constraint": "wait_for_confirmation", "quality_state": "degraded",
        "headline": "公开市场事实（仅宽度与成交）", "conclusion": boundary,
        "dimension_summary": {"total": 2, "support": 0, "partial_support": 0, "neutral": 0, "suppress": 0, "risk_release": 0, "unknown": 2},
        "dimensions": dimensions, "evidence_refs": evidence, "source_status": status,
        "conflicts": [{"metric_name": "覆盖范围", "resolution": "其他市场资料尚未同步，无法判断完整市场状态。"}],
        "sentiment_view": {"status": "unknown", "headline": "情绪判断尚未同步", "judgment": boundary, "action": "等待完整依据", "as_of": as_of},
        "user_view": {"标题": "仅部分公开事实", "当前判断": boundary, "当前允许": "等待完整依据", "行情时点": as_of, "交易日": day, "阶段": "部分事实同步"},
        "public_export": {"version": 1, "decision_readiness": False, "source_as_of": {key: raw[key]["as_of"] for key in INPUTS}, "generated_at_used_as_source_time": False},
        "guardrails": {"public_sources_only": True, "user_assets_read": False, "user_assets_modified": False, "automatic_trading": False, "model_promoted": False},
    }


def _check_existing(existing: dict[str, Any], candidate: dict[str, Any]) -> str | None:
    old = _time(existing.get("as_of"))
    new = _time(candidate["as_of"])
    if old >= new:
        return "existing_newer_or_equal_retained"
    # Each individual published source must also move forward or stay unchanged.
    old_sources = (existing.get("public_export") or {}).get("source_as_of") or {}
    for key, value in old_sources.items():
        if key in INPUTS and _time(value) > _time(candidate["public_export"]["source_as_of"][key]):
            return "existing_source_newer_retained"
    for row in existing.get("dimensions", []):
        if isinstance(row, dict) and row.get("dimension_code") in INPUTS:
            if _time(row.get("as_of")) > _time(candidate["public_export"]["source_as_of"][row["dimension_code"]]):
                return "existing_source_newer_retained"
    return None


def export_public_market_facts(source: Path, target: Path, *, apply: bool = False, now: datetime | None = None) -> dict[str, Any]:
    """Preview by default. Apply touches only OUTPUT, preserving seven other projections."""
    source, target = source.resolve(), target.resolve()
    observed = now or datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "state": "blocked", "mode": "partial_public_facts", "applied": False,
        "output": OUTPUT, "decision_readiness": False,
        "skipped": [{"path": path, "reason": "projection_not_privacy_approved"} for path in UNAPPROVED],
    }
    try:
        if source == target or source.is_relative_to(target) or target.is_relative_to(source):
            raise ExportBlocked("source_target_must_be_separate")
        candidate = build_public_market_facts(source, observed)
        path = _path(target, OUTPUT)
        report["source_as_of"] = candidate["public_export"]["source_as_of"]
        def inspect() -> str | None:
            if not path.exists():
                return None
            try:
                return _check_existing(_read(target, OUTPUT), candidate)
            except (ExportBlocked, TypeError, AttributeError):
                raise ExportBlocked("existing_output_date_unverified") from None
        retained = inspect()
        if retained:
            report.update(state="retained", reason=retained)
            return report
        if not apply:
            report.update(state="ready", reason="preview_only")
            return report
        target.mkdir(parents=True, exist_ok=True)
        lock = _path(target, ".public-market-export.lock")
        with lock.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                retained = inspect()
                if retained:
                    report.update(state="retained", reason=retained)
                    return report
                path = _path(target, OUTPUT)
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = json.dumps(candidate, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".public-market-", suffix=".tmp", delete=False) as temporary:
                    temporary.write(payload)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    tmp = Path(temporary.name)
                try:
                    _path(target, OUTPUT)
                    tmp.replace(path)
                finally:
                    tmp.unlink(missing_ok=True)
                report.update(state="updated", applied=True, sha256=hashlib.sha256(payload.encode()).hexdigest())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except ExportBlocked as exc:
        report["reason"] = str(exc)
    except (OSError, ValueError, TypeError):
        report["reason"] = "local_export_failed"
    return report

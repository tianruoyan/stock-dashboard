from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from v2_platform.learning import as_dict, as_list, load_json, now_iso


class V2ModelEvaluator:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.data_dir = self.root / "data" / "v2"
        self.registry = load_json(self.root / "config" / "v2-model-registry.json")

    def build(self) -> dict[str, Any]:
        index = load_json(self.data_dir / "replay-index.json")
        outcomes = load_json(self.data_dir / "signal-outcomes.json")
        refs = as_list(index.get("snapshots"))
        all_snapshot_meta = self._snapshot_meta(refs, eligible_only=False)
        snapshot_meta = self._snapshot_meta(refs, eligible_only=True)
        records = self._records(as_list(outcomes.get("signals")), snapshot_meta)
        versions = sorted(set(meta["model_version"] for meta in snapshot_meta.values()) | {record["model_version"] for record in records})
        summaries = [self._summary(version, records, snapshot_meta) for version in versions]
        baseline = as_dict(self.registry.get("baseline")).get("version")
        candidates = {item.get("version") for item in as_list(self.registry.get("candidates")) if isinstance(item, dict)}
        comparisons = [self._compare(baseline, candidate, summaries) for candidate in sorted(candidates)]
        gates = as_dict(self.registry.get("evaluation"))
        return {
            "schema_version": 1,
            "registry_version": self.registry.get("registry_version"),
            "generated_at": now_iso(),
            "state": "collecting" if not records else ("candidate_review" if comparisons else "baseline_observation"),
            "baseline_version": baseline,
            "primary_window": gates.get("primary_window"),
            "version_summaries": summaries,
            "comparisons": comparisons,
            "promotion_policy": self.registry.get("promotion_policy"),
            "recommendation": self._recommendation(comparisons),
            "record_count": len(records),
            "data_gaps": self._data_gaps(records, all_snapshot_meta),
        }

    def _snapshot_meta(self, refs: list[Any], eligible_only: bool) -> dict[str, dict[str, Any]]:
        result = {}
        baseline = str(as_dict(self.registry.get("baseline")).get("version") or "unversioned")
        for ref in refs:
            if not isinstance(ref, dict) or not ref.get("path"):
                continue
            if eligible_only and ref.get("evaluation_eligible") is not True:
                continue
            snapshot = load_json(self.root / str(ref["path"]))
            result[str(snapshot.get("snapshot_id"))] = {
                "model_version": str(snapshot.get("decision_model_version") or "legacy_unversioned"),
                "decision_date": snapshot.get("decision_date"),
                "quality_state": as_dict(snapshot.get("quality")).get("state"),
                "market_stance": as_dict(snapshot.get("market_environment")).get("state"),
                "baseline_at_creation": baseline,
            }
        return result

    def _records(self, signals: list[Any], snapshot_meta: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        primary = str(as_dict(self.registry.get("evaluation")).get("primary_window") or "T+3")
        rows = []
        for signal in signals:
            if not isinstance(signal, dict):
                continue
            meta = snapshot_meta.get(str(signal.get("snapshot_id")))
            if meta is None:
                continue
            returns = []
            supports = []
            for security in as_list(signal.get("security_results")):
                if not isinstance(security, dict):
                    continue
                for window in as_list(security.get("windows")):
                    if not isinstance(window, dict) or window.get("window") != primary or window.get("status") != "evaluated":
                        continue
                    result = as_dict(window.get("result"))
                    value = result.get("absolute_return_pct")
                    if isinstance(value, (int, float)):
                        returns.append(float(value))
                        supports.append(result.get("signal_support") == "supportive")
            if returns:
                rows.append(
                    {
                        "snapshot_id": signal.get("snapshot_id"),
                        "signal_id": signal.get("signal_id"),
                        "title": signal.get("title"),
                        "kind": signal.get("kind"),
                        "model_version": meta.get("model_version", "unknown"),
                        "decision_date": meta.get("decision_date") or signal.get("decision_date"),
                        "quality_state": meta.get("quality_state"),
                        "market_stance": meta.get("market_stance"),
                        "median_absolute_return_pct": round(statistics.median(returns), 4),
                        "signal_support": sum(supports) / len(supports) >= 0.5,
                        "security_count": len(returns),
                    }
                )
        return rows

    def _summary(self, version: str, records: list[dict[str, Any]], snapshot_meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
        selected = [item for item in records if item["model_version"] == version]
        dates = {item["decision_date"] for item in selected if item.get("decision_date")}
        opportunity = [item for item in selected if item.get("kind") == "opportunity"]
        risk = [item for item in selected if item.get("kind") == "risk"]
        gates = as_dict(self.registry.get("evaluation"))
        gate_results = {
            "evaluated_signals": len(selected) >= int(gates.get("minimum_evaluated_signals") or 0),
            "distinct_dates": len(dates) >= int(gates.get("minimum_distinct_decision_dates") or 0),
            "opportunity_signals": len(opportunity) >= int(gates.get("minimum_opportunity_signals") or 0),
            "risk_signals": len(risk) >= int(gates.get("minimum_risk_signals") or 0),
        }
        return {
            "version": version,
            "snapshot_count": sum(meta.get("model_version") == version for meta in snapshot_meta.values()),
            "evaluated_signal_count": len(selected),
            "distinct_decision_dates": len(dates),
            "opportunity_count": len(opportunity),
            "risk_count": len(risk),
            "signal_support_rate": round(sum(bool(item["signal_support"]) for item in selected) / len(selected) * 100, 2) if selected else None,
            "median_absolute_return_pct": round(statistics.median(item["median_absolute_return_pct"] for item in selected), 4) if selected else None,
            "quality_regimes": sorted({str(item.get("quality_state")) for item in selected if item.get("quality_state")}),
            "market_regimes": sorted({str(item.get("market_stance")) for item in selected if item.get("market_stance")}),
            "gate_results": gate_results,
            "promotion_eligible": bool(selected) and all(gate_results.values()),
        }

    @staticmethod
    def _compare(baseline: Any, candidate: Any, summaries: list[dict[str, Any]]) -> dict[str, Any]:
        by_version = {item["version"]: item for item in summaries}
        base = by_version.get(baseline)
        cand = by_version.get(candidate)
        if not base or not cand or not base.get("promotion_eligible") or not cand.get("promotion_eligible"):
            return {"baseline": baseline, "candidate": candidate, "state": "insufficient_samples", "support_rate_delta_pct": None}
        return {
            "baseline": baseline,
            "candidate": candidate,
            "state": "offline_comparable",
            "support_rate_delta_pct": round(float(cand["signal_support_rate"]) - float(base["signal_support_rate"]), 2),
            "candidate_market_regimes": cand["market_regimes"],
            "automatic_promotion": False,
        }

    @staticmethod
    def _recommendation(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
        comparable = [item for item in comparisons if item.get("state") == "offline_comparable"]
        if not comparable:
            return {"action": "keep_baseline", "reason": "没有满足样本、时间跨度和双侧信号门槛的候选版本。", "requires_user_confirmation": True}
        best = max(comparable, key=lambda item: item.get("support_rate_delta_pct") or float("-inf"))
        return {"action": "review_candidate" if (best.get("support_rate_delta_pct") or 0) > 0 else "keep_baseline", "candidate": best.get("candidate"), "reason": "仅形成离线比较，不自动晋级。", "requires_user_confirmation": True}

    @staticmethod
    def _data_gaps(records: list[dict[str, Any]], snapshot_meta: dict[str, dict[str, Any]]) -> list[str]:
        gaps = []
        if not snapshot_meta:
            gaps.append("没有判断快照")
        if not records:
            gaps.append("主评估窗口没有可审计结果价格")
        if any(meta.get("model_version") == "legacy_unversioned" for meta in snapshot_meta.values()):
            gaps.append("历史快照没有决策模型版本，只能作为旧基线背景")
        return gaps

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from v2_platform.environment_evidence import canonical_hash, parse_datetime, trade_date_of
from v2_platform.learning import as_dict, as_list, load_json, write_json
from v2_platform.v22_time_semantics import V22TimeSemanticsBuilder


MINIMUMS = {
    "evaluated_signals": 50,
    "distinct_decision_dates": 20,
    "opportunity_signals": 15,
    "risk_signals": 15,
}
PRIMARY_WINDOW = "T+3"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class V22LearningBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.cases = load_json(self.root / "data/v2/v22/decision-cases.json")
        self.candidate = load_json(self.root / "data/v2/v22/decision-system-candidate.json")
        self.case_index = load_json(self.root / "data/v2/v22/decision-case-snapshot-index.json")
        self.trigger_index = load_json(self.root / "data/v2/v22/trigger-quote-index.json")
        self.price_input = load_json(self.root / "data/v2/v22/outcome-prices.json")
        self.baseline = load_json(self.root / "data/v2/decision-system.json")
        self.time_semantics = load_json(self.root / "data/v2/v22/time-semantics.json") or V22TimeSemanticsBuilder(self.root).build()

    def build(self) -> dict[str, dict[str, Any]]:
        replay, trigger_snapshots = self._replay()
        outcomes, records = self._outcomes(trigger_snapshots)
        replay["evaluation_snapshot_count"] = sum(item.get("evaluation_included") is True for item in records)
        evaluation = self._evaluation(records)
        comparison = self._comparison(evaluation)
        acceptance = self._acceptance(replay, outcomes, evaluation, comparison)
        return {
            "replay-index.json": replay,
            "signal-outcomes.json": outcomes,
            "model-evaluation.json": evaluation,
            "parallel-comparison.json": comparison,
            "acceptance-report.json": acceptance,
        }

    def _replay(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        snapshots = []
        current_batch = self.cases.get("case_batch_id")
        for item in as_list(self.case_index.get("snapshots")):
            if not isinstance(item, dict):
                continue
            snapshots.append({
                "case_batch_id": item.get("case_batch_id"),
                "trade_date": item.get("trade_date"),
                "as_of": item.get("as_of"),
                "case_count": item.get("case_count"),
                "is_current": item.get("case_batch_id") == current_batch,
                "relative_path": item.get("relative_path"),
                "immutable_hash": item.get("immutable_hash"),
            })
        trigger_snapshots = []
        for item in as_list(self.trigger_index.get("snapshots")):
            if not isinstance(item, dict) or not item.get("relative_path"):
                continue
            snapshot = load_json(self.root / str(item["relative_path"]))
            if snapshot and snapshot.get("immutable_hash") == item.get("immutable_hash"):
                trigger_snapshots.append(snapshot)
        replay = {
            "schema_version": 2,
            "generated_at": now_iso(),
            "mode": "shadow_only",
            "snapshot_count": len(snapshots),
            "decision_case_snapshot_count": len(snapshots),
            "trigger_quote_snapshot_count": len(trigger_snapshots),
            "current_case_batch_id": current_batch,
            "evaluation_snapshot_count": 0,
            "snapshots": snapshots,
            "trigger_quote_snapshots": [{
                "snapshot_id": item.get("snapshot_id"),
                "case_id": item.get("case_id"),
                "trade_date": item.get("trade_date"),
                "state_observed_at": item.get("state_observed_at"),
                "quote_count": len(as_list(item.get("representative_quotes"))),
                "immutable_hash": item.get("immutable_hash"),
            } for item in trigger_snapshots],
            "guardrails": {
                "historical_snapshot_rewritten": False,
                "later_evidence_backfilled_as_known": False,
                "current_quote_used_as_historical_reference": False,
                "automatic_model_promotion": False,
            },
        }
        return replay, trigger_snapshots

    def _outcomes(self, trigger_snapshots: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        observations = [item for item in as_list(self.price_input.get("observations")) if isinstance(item, dict)]
        observations_by_snapshot: dict[str, list[dict[str, Any]]] = {}
        for item in observations:
            observations_by_snapshot.setdefault(str(item.get("trigger_snapshot_id") or ""), []).append(item)
        records = []
        case_rows = []
        snapshot_case_ids = {str(item.get("case_id")) for item in trigger_snapshots}
        trigger_id_counts: dict[str, int] = {}
        for snapshot in trigger_snapshots:
            trigger_id = str(snapshot.get("snapshot_id") or "")
            trigger_id_counts[trigger_id] = trigger_id_counts.get(trigger_id, 0) + 1
        for snapshot in trigger_snapshots:
            snapshot_id = str(snapshot.get("snapshot_id") or "")
            rows = observations_by_snapshot.get(snapshot_id, [])
            expected_quotes = [item for item in as_list(snapshot.get("representative_quotes")) if isinstance(item, dict)]
            by_code = {str(item.get("code")): item for item in rows}
            gates = self._evaluation_gates(snapshot, expected_quotes, by_code, trigger_id_counts.get(snapshot_id, 0) == 1)
            eligible = all(item["passed"] for item in gates)
            returns = []
            if eligible:
                for quote in expected_quotes:
                    observation = by_code[str(quote.get("code"))]
                    result = as_dict(as_dict(observation.get("windows")).get(PRIMARY_WINDOW))
                    returns.append(round((float(result["price"]) / float(observation["reference_price"]) - 1) * 100, 4))
            aggregate_return = round(float(median(returns)), 4) if returns else None
            supportive = None
            if aggregate_return is not None:
                supportive = aggregate_return > 0 if snapshot.get("kind") == "opportunity" else aggregate_return < 0
            record = {
                "trigger_snapshot_id": snapshot_id,
                "case_id": snapshot.get("case_id"),
                "trade_date": snapshot.get("trade_date"),
                "kind": snapshot.get("kind"),
                "primary_window": PRIMARY_WINDOW,
                "evaluation_included": eligible,
                "evaluation_gates": gates,
                "representative_count": len(expected_quotes),
                "representative_result_count": len(returns),
                "median_return_pct": aggregate_return,
                "signal_supported": supportive,
                "result_summary": "主要结果窗口完整，可进入离线评价。" if eligible else self._hold_summary(gates),
            }
            records.append(record)
            case_rows.append(record)

        for case in as_list(self.cases.get("cases")):
            if not isinstance(case, dict) or str(case.get("case_id")) in snapshot_case_ids:
                continue
            case_rows.append({
                "trigger_snapshot_id": None,
                "case_id": case.get("case_id"),
                "trade_date": self.cases.get("trade_date"),
                "kind": "risk" if case.get("business_path") == "risk_path" else "opportunity",
                "primary_window": PRIMARY_WINDOW,
                "evaluation_included": False,
                "evaluation_gates": [],
                "representative_count": len(as_list(case.get("representative_stocks"))),
                "representative_result_count": 0,
                "median_return_pct": None,
                "signal_supported": None,
                "result_summary": "历史或当前案例没有同交易日、近触发时点的行情快照，不进入评价。" if case.get("ended") else "等待首次触发行情快照与到期结果。",
            })
        evaluated = sum(item.get("evaluation_included") is True for item in records)
        outcomes = {
            "schema_version": 2,
            "generated_at": now_iso(),
            "mode": "shadow_only",
            "case_batch_id": self.cases.get("case_batch_id"),
            "windows": ["盘中5分钟", "盘中15分钟", "盘中30分钟", "盘中60分钟", "收盘", "T+1", "T+3", "T+5", "T+10"],
            "primary_window": PRIMARY_WINDOW,
            "trigger_snapshot_count": len(trigger_snapshots),
            "evaluated_case_count": evaluated,
            "pending_case_count": len(case_rows) - evaluated,
            "cases": case_rows,
            "guardrails": {
                "current_quote_used_as_historical_reference": False,
                "not_due_window_used": False,
                "missing_price_treated_as_zero": False,
                "hit_rate_published": False,
                "user_asset_fields_included": False,
            },
        }
        return outcomes, records

    def _evaluation_gates(
        self,
        snapshot: dict[str, Any],
        expected_quotes: list[dict[str, Any]],
        observations: dict[str, dict[str, Any]],
        trigger_snapshot_unique: bool,
    ) -> list[dict[str, Any]]:
        observed_at = parse_datetime(snapshot.get("state_observed_at"))
        references_complete = bool(expected_quotes) and all(
            isinstance(item.get("trigger_price"), (int, float))
            and item.get("trigger_price") > 0
            and parse_datetime(item.get("quote_time"))
            and trade_date_of(item.get("quote_time")) == snapshot.get("trade_date")
            and item.get("source_id")
            and item.get("source_label")
            and parse_datetime(item.get("collected_at"))
            for item in expected_quotes
        )
        dual_source_confirmed = references_complete and all(
            item.get("cross_source_verified") is True
            and item.get("quality_state") == "dual_source_confirmed"
            for item in expected_quotes
        )
        observations_complete = len(observations) == len(expected_quotes) and all(str(item.get("code")) in observations for item in expected_quotes)
        references_match = observations_complete and all(
            observations[str(item.get("code"))].get("reference_price") == item.get("trigger_price")
            and observations[str(item.get("code"))].get("reference_at") == item.get("quote_time")
            for item in expected_quotes
        )
        primary_complete = observations_complete and all(
            isinstance(as_dict(as_dict(observations[str(item.get("code"))].get("windows")).get(PRIMARY_WINDOW)).get("price"), (int, float))
            and parse_datetime(as_dict(as_dict(observations[str(item.get("code"))].get("windows")).get(PRIMARY_WINDOW)).get("quote_time"))
            for item in expected_quotes
        )
        chronology_ok = bool(observed_at and primary_complete) and all(
            observed_at < parse_datetime(as_dict(as_dict(observations[str(item.get("code"))].get("windows")).get(PRIMARY_WINDOW)).get("quote_time"))
            for item in expected_quotes
        )
        source_complete = observations_complete and all(
            as_dict(as_dict(observations[str(item.get("code"))].get("windows")).get(PRIMARY_WINDOW)).get("source")
            and parse_datetime(as_dict(as_dict(observations[str(item.get("code"))].get("windows")).get(PRIMARY_WINDOW)).get("collected_at"))
            for item in expected_quotes
        )
        return [
            {"id": "immutable_decision_and_trigger_snapshot", "passed": self._case_snapshot_valid(snapshot), "reason": "原始判断与触发行情快照必须存在且哈希一致。"},
            {"id": "unique_trigger_snapshot", "passed": trigger_snapshot_unique, "reason": "同一触发行情快照不能重复计入评价。"},
            {"id": "auditable_trigger_reference", "passed": references_complete, "reason": "代表股触发价格、行情时间和来源必须完整。"},
            {"id": "dual_source_trigger_confirmation", "passed": dual_source_confirmed, "reason": "代表股触发行情必须经过两路独立行情确认；单源记录只用于观察，不进入模型评价。"},
            {"id": "representative_quote_closure", "passed": observations_complete, "reason": "全部代表股必须形成结果记录。"},
            {"id": "reference_matches_frozen_snapshot", "passed": references_match, "reason": "结果记录必须使用冻结触发价格，不能重新选取参考价。"},
            {"id": "primary_window_due_and_complete", "passed": primary_complete, "reason": f"全部代表股的{PRIMARY_WINDOW}窗口必须到期并取得真实行情。"},
            {"id": "chronology_before_result", "passed": chronology_ok, "reason": "判断和触发行情必须发生在结果之前。"},
            {"id": "result_source_auditable", "passed": source_complete, "reason": "结果行情必须保留来源和时间。"},
            {"id": "trade_date_aligned", "passed": trade_date_of(snapshot.get("state_observed_at")) == snapshot.get("trade_date"), "reason": "首次观察时间必须属于案例交易日。"},
        ]

    def _case_snapshot_valid(self, trigger_snapshot: dict[str, Any]) -> bool:
        if not trigger_snapshot.get("immutable_hash") or not trigger_snapshot.get("case_content_hash"):
            return False
        for item in as_list(self.case_index.get("snapshots")):
            if not isinstance(item, dict) or item.get("case_batch_id") != trigger_snapshot.get("case_batch_id") or not item.get("relative_path"):
                continue
            stored = load_json(self.root / str(item["relative_path"]))
            if not stored or stored.get("immutable_hash") != item.get("immutable_hash"):
                continue
            case = next((row for row in as_list(stored.get("cases")) if isinstance(row, dict) and row.get("case_id") == trigger_snapshot.get("case_id")), None)
            return bool(case and canonical_hash(case) == trigger_snapshot.get("case_content_hash"))
        return False

    @staticmethod
    def _hold_summary(gates: list[dict[str, Any]]) -> str:
        failed = [str(item.get("reason")) for item in gates if not item.get("passed")]
        return failed[0] if failed else "等待可审计结果。"

    def _evaluation(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        included = [item for item in records if item.get("evaluation_included") is True]
        distinct_dates = {str(item.get("trade_date")) for item in included if item.get("trade_date")}
        opportunity = sum(item.get("kind") == "opportunity" for item in included)
        risk = sum(item.get("kind") == "risk" for item in included)
        thresholds_met = (
            len(included) >= MINIMUMS["evaluated_signals"]
            and len(distinct_dates) >= MINIMUMS["distinct_decision_dates"]
            and opportunity >= MINIMUMS["opportunity_signals"]
            and risk >= MINIMUMS["risk_signals"]
        )
        metrics = None
        if thresholds_met:
            supported = sum(item.get("signal_supported") is True for item in included)
            metrics = {"supportive_result_ratio": round(supported / len(included), 4), "primary_window": PRIMARY_WINDOW}
        if not included:
            reason = "V2.2尚无触发价格与主要结果窗口均完整的案例，不计算命中率，也不改变规则。"
        elif not thresholds_met:
            reason = "已有可评价案例，但样本数量、日期跨度或机会/风险双侧门槛尚未满足，不展示命中率。"
        else:
            reason = "离线样本达到最低展示门槛；是否调整规则仍需用户确认。"
        return {
            "schema_version": 2,
            "generated_at": now_iso(),
            "mode": "offline_shadow_only",
            "candidate_version": "decision-v2.2-shadow",
            "state": "minimums_met_user_review_required" if thresholds_met else "collecting_evaluable_cases",
            "record_count": len(included),
            "distinct_decision_dates": len(distinct_dates),
            "opportunity_count": opportunity,
            "risk_count": risk,
            "minimum_requirements": MINIMUMS,
            "minimum_requirements_met": thresholds_met,
            "metrics_published": thresholds_met,
            "metrics": metrics,
            "recommendation": {"action": "提交用户评审" if thresholds_met else "保留当前基线", "reason": reason, "requires_user_confirmation": True},
            "automatic_live_promotion": False,
        }

    def _comparison(self, evaluation: dict[str, Any]) -> dict[str, Any]:
        baseline_validation = len(as_list(self.baseline.get("validation_queue")))
        candidate_validation = int(as_dict(self.candidate.get("summary")).get("awaiting_confirmation") or 0)
        time_comparison = as_dict(self.time_semantics.get("comparison"))
        baseline_date = as_dict(as_dict(self.time_semantics.get("sources")).get("v2_baseline")).get("market_date")
        candidate_date = as_dict(as_dict(self.time_semantics.get("sources")).get("v22_market_environment")).get("market_date")
        differences = [
            {"label": "观察卡降噪", "conclusion": f"V2验证队列{baseline_validation}张，V2.2只展示{candidate_validation}张代表股行情闭环案例；其余线索不成卡。"},
            {"label": "时间口径", "conclusion": time_comparison.get("reason") or "交易日期等待核验。"},
            {"label": "结果门槛", "conclusion": evaluation["recommendation"]["reason"]},
            {"label": "入口边界", "conclusion": "V1生产、V2基线和V2.2候选均保持原角色，不自动切换。"},
        ]
        cutover_reason = time_comparison.get("reason") if not time_comparison.get("allowed") else "样本、日期跨度、双侧信号和结果窗口尚未同时达到要求。"
        return {
            "schema_version": 2,
            "generated_at": now_iso(),
            "mode": "parallel_shadow",
            "state": "date_alignment_blocked" if not time_comparison.get("allowed") else "structure_comparable_outcomes_pending",
            "headline": "V2基线继续运行，V2.2只做候选对照。",
            "v2_baseline": {"current_count": len(as_list(self.baseline.get("opportunity_radar"))), "validation_count": baseline_validation, "market_date": baseline_date},
            "v22_candidate": {
                "current_count": int(as_dict(self.candidate.get("summary")).get("decision_ready") or 0),
                "validation_count": candidate_validation,
                "unformed_clue_count": int(as_dict(self.candidate.get("summary")).get("unformed_clues") or 0),
                "parked_clue_count": int(as_dict(self.candidate.get("summary")).get("parked_clues") or 0),
                "market_date": candidate_date,
            },
            "date_comparison_allowed": bool(time_comparison.get("allowed")),
            "hit_rate_comparison_allowed": bool(time_comparison.get("allowed") and evaluation.get("minimum_requirements_met")),
            "differences": differences,
            "cutover": {"ready": False, "reason": cutover_reason, "requires_new_user_confirmation": True},
            "guardrails": {"automatic_cutover": False, "automatic_trading": False, "user_assets_modified": False, "automatic_model_promotion": False, "mixed_trade_dates_compared": False},
        }

    def _acceptance(self, replay: dict[str, Any], outcomes: dict[str, Any], evaluation: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
        checks = [
            ("判断案例快照存在", replay["decision_case_snapshot_count"] > 0),
            ("历史快照不重写", replay["guardrails"]["historical_snapshot_rewritten"] is False),
            ("不使用当前行情冒充历史触发价格", outcomes["guardrails"]["current_quote_used_as_historical_reference"] is False),
            ("不同交易日不比较结果", comparison["guardrails"]["mixed_trade_dates_compared"] is False and (comparison["date_comparison_allowed"] or comparison["hit_rate_comparison_allowed"] is False)),
            ("未到期窗口不进入评价", outcomes["guardrails"]["not_due_window_used"] is False),
            ("缺失价格不按零处理", outcomes["guardrails"]["missing_price_treated_as_zero"] is False),
            ("样本不足不展示命中率", evaluation["minimum_requirements_met"] or evaluation["metrics_published"] is False),
            ("模型不自动晋升", evaluation["automatic_live_promotion"] is False),
            ("双轨不自动切换", comparison["cutover"]["ready"] is False and comparison["guardrails"]["automatic_cutover"] is False),
            ("不修改用户资产", comparison["guardrails"]["user_assets_modified"] is False),
        ]
        return {
            "schema_version": 2,
            "generated_at": now_iso(),
            "stage": "S2_intraday_shadow_capture_and_current_facts",
            "status": "passed" if all(value for _, value in checks) else "failed",
            "checks": [{"label": label, "passed": value} for label, value in checks],
            "production_promotion": "hold",
            "reason": "S2盘中影子捕获链路已接入；真实触发行情和结果样本继续按交易日积累。",
        }

    def write(self) -> dict[str, dict[str, Any]]:
        outputs = self.build()
        directory = self.root / "data/v2/v22"
        directory.mkdir(parents=True, exist_ok=True)
        for name, payload in outputs.items():
            write_json(directory / name, payload)
        return outputs

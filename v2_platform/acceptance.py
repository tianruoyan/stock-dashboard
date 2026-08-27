from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def git_output(path: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def production_v1_code_state(path: Path, baseline: str, protected_paths: list[str]) -> dict[str, Any]:
    head = git_output(path, "rev-parse", "HEAD") if path.exists() else ""
    if not head or not baseline or not protected_paths:
        return {"passed": False, "head": head, "changed_paths": ["configuration_missing"]}
    baseline_check = subprocess.run(["git", "-C", str(path), "cat-file", "-e", f"{baseline}^{{commit}}"], capture_output=True)
    if baseline_check.returncode != 0:
        return {"passed": False, "head": head, "changed_paths": ["baseline_commit_missing"]}
    committed = git_output(path, "diff", "--name-only", f"{baseline}..HEAD", "--", *protected_paths).splitlines()
    working = git_output(path, "status", "--porcelain", "--", *protected_paths).splitlines()
    changed = sorted({line.strip() for line in [*committed, *working] if line.strip()})
    return {"passed": not changed, "head": head, "changed_paths": changed}


def v22_feature_scope_valid(stage: str, features: dict[str, Any]) -> bool:
    enabled = {str(key) for key, value in features.items() if value is True}
    if stage == "E0_baseline_freeze":
        return not enabled
    if stage == "E1_private_user_asset_foundation":
        return enabled == {"user_asset_store"}
    if stage == "E2_ths_shadow_and_migration_review":
        return enabled == {"user_asset_store", "ths_shadow_sync"}
    if stage == "E3_stock_pool_layers_shadow":
        return enabled == {"user_asset_store", "ths_shadow_sync", "stock_pool_projection"}
    if stage == "E4_market_environment_facts_shadow":
        return enabled == {"user_asset_store", "ths_shadow_sync", "stock_pool_projection", "market_environment"}
    if stage == "E5_environment_state_style_cross_market_g5_shadow":
        return enabled == {
            "user_asset_store", "ths_shadow_sync", "stock_pool_projection", "market_environment",
            "style_and_cross_market_mapping", "environment_state_machine", "g5_environment_gate",
        }
    if stage == "E6_decision_cases_g0_g7_shadow":
        return enabled == {
            "user_asset_store", "ths_shadow_sync", "stock_pool_projection", "market_environment",
            "style_and_cross_market_mapping", "environment_state_machine", "g5_environment_gate",
            "decision_cases", "page_projection",
        }
    if stage == "E7_replay_learning_parallel_acceptance_shadow":
        return enabled == {
            "user_asset_store", "ths_shadow_sync", "stock_pool_projection", "market_environment",
            "style_and_cross_market_mapping", "environment_state_machine", "g5_environment_gate",
            "decision_cases", "page_projection", "replay_learning", "candidate_model_evaluation",
        }
    if stage == "S1_shadow_trigger_quote_and_replay_closure":
        return enabled == {
            "user_asset_store", "ths_shadow_sync", "stock_pool_projection", "market_environment",
            "style_and_cross_market_mapping", "environment_state_machine", "g5_environment_gate",
            "decision_cases", "page_projection", "replay_learning", "candidate_model_evaluation",
            "time_semantics_gate", "trigger_quote_capture", "outcome_price_backfill",
        }
    if stage == "S2_intraday_shadow_capture_and_current_facts":
        return enabled == {
            "user_asset_store", "ths_shadow_sync", "stock_pool_projection", "market_environment",
            "style_and_cross_market_mapping", "environment_state_machine", "g5_environment_gate",
            "decision_cases", "page_projection", "replay_learning", "candidate_model_evaluation",
            "time_semantics_gate", "trigger_quote_capture", "outcome_price_backfill",
            "market_fact_refresh", "intraday_shadow_checkpoints",
        }
    return False


class V2AcceptanceBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.data = self.root / "data" / "v2"
        self.rollout = load_json(self.root / "config" / "v2-rollout.json")

    def build(self) -> dict[str, Any]:
        decision = load_json(self.data / "decision-system.json")
        smoke = load_json(self.data / "smoke-report.json")
        replay = load_json(self.data / "replay-index.json")
        research = load_json(self.data / "research-library.json")
        stock_pool = load_json(self.data / "stock-pool.json")
        build = load_json(self.root / "data" / "build-report.json")
        learning = load_json(self.root / "config" / "v2-learning-policy.json")
        completion = load_json(self.data / "completion-audit.json")
        parallel = load_json(self.data / "parallel-comparison.json")
        v22_flags = load_json(self.root / "config" / "v2-v22-feature-flags.json")
        v22_baseline = load_json(self.data / "v22" / "baseline-audit.json")
        v22_watchlist = load_json(self.data / "v22" / "watchlist-migration-audit.json")
        v22_stock_pool = load_json(self.data / "v22" / "stock-pool-shadow.json")
        v22_environment = load_json(self.data / "v22" / "market-environment.json")
        v22_environment_index = load_json(self.data / "v22" / "environment-snapshot-index.json")
        v22_environment_decision = load_json(self.data / "v22" / "environment-decision.json")
        v22_environment_decision_index = load_json(self.data / "v22" / "environment-decision-snapshot-index.json")
        v22_cases = load_json(self.data / "v22" / "decision-cases.json")
        v22_candidate = load_json(self.data / "v22" / "decision-system-candidate.json")
        v22_case_index = load_json(self.data / "v22" / "decision-case-snapshot-index.json")
        v22_time_semantics = load_json(self.data / "v22" / "time-semantics.json")
        v22_trigger_index = load_json(self.data / "v22" / "trigger-quote-index.json")
        v22_trigger_report = load_json(self.data / "v22" / "trigger-quote-capture-report.json")
        v22_outcome_prices = load_json(self.data / "v22" / "outcome-prices.json")
        v22_outcome_report = load_json(self.data / "v22" / "outcome-price-report.json")
        v22_replay = load_json(self.data / "v22" / "replay-index.json")
        v22_outcomes = load_json(self.data / "v22" / "signal-outcomes.json")
        v22_evaluation = load_json(self.data / "v22" / "model-evaluation.json")
        v22_parallel = load_json(self.data / "v22" / "parallel-comparison.json")
        v22_final_acceptance = load_json(self.data / "v22" / "acceptance-report.json")
        v22_intraday_config = load_json(self.root / "config" / "v2-intraday-shadow.json")
        v22_fact_health = load_json(self.data / "public-market-fact-health.json")
        v22_skill_validation = load_json(self.data / "v22" / "platform-skill-validation.json")
        v22_three_way = load_json(self.data / "v22" / "watchlist-three-way-summary.json")
        v22_runtime_import = load_json(self.data / "v22" / "runtime-import-report.json")
        production_config = self.rollout.get("production_v1") or {}
        operation = self.rollout.get("operation_strategy") or {}
        production = Path(str(production_config.get("path") or ""))
        production_head = git_output(production, "rev-parse", "HEAD") if production.exists() else ""
        baseline = str(production_config.get("baseline_commit") or "")
        protected_paths = [str(item) for item in production_config.get("protected_paths") or []]
        v1_code = production_v1_code_state(production, baseline, protected_paths)
        v22_features = v22_flags.get("features") if isinstance(v22_flags.get("features"), dict) else {}
        v22_boundaries = v22_flags.get("immutable_boundaries") if isinstance(v22_flags.get("immutable_boundaries"), dict) else {}
        v22_stage = str((self.rollout.get("v2_2") or {}).get("stage") or "")
        checks = [
            self._check("v2_shadow_mode", decision.get("system", {}).get("mode") == "shadow_only", "V2仍为影子模式，不触发生产交易或通知。"),
            self._check("parallel_operation", operation.get("mode") == "parallel_shadow" and operation.get("v1_role") == "production_primary" and operation.get("stop_v1_requires_new_user_confirmation") is True, "用户已确认V1/V2双轨并行；停用V1需要再次确认。"),
            self._check("parallel_comparison", parallel.get("state") in {"comparable", "degraded"} and parallel.get("cutover", {}).get("ready") is False, f"双轨对照：{parallel.get('state') or 'missing'}，差异 {len(parallel.get('divergences') or [])} 类。"),
            self._check("static_smoke", smoke.get("status") == "ok", f"V2页面检查：{smoke.get('status') or 'missing'}"),
            self._check("unified_build_not_blocked", build.get("status") != "blocked" and bool(build), f"统一构建：{build.get('status') or 'missing'}"),
            self._check("research_domains", len(research.get("domains") or []) >= 6, f"产业领域：{len(research.get('domains') or [])}"),
            self._check("stock_pool", int(stock_pool.get("stock_count") or 0) > 0, f"统一股票池：{stock_pool.get('stock_count') or 0}只"),
            self._check("immutable_replay", int(replay.get("snapshot_count") or 0) > 0, f"冻结快照：{replay.get('snapshot_count') or 0}个"),
            self._check("no_live_model_weight_change", learning.get("model_change_policy", {}).get("automatic_live_weight_change") is False, "禁止自动修改线上模型权重。"),
            self._check("production_v1_preserved", v1_code["passed"], f"V1程序与入口保持基线 {baseline}；数据提交可继续前进，当前 {production_head[:7] or 'missing'}。"),
            self._check("rollback_entry_exists", (production / str(production_config.get("entry") or "index.html")).exists(), "生产V1入口可作为即时回退入口。"),
            self._check("completion_audit_internal", int(completion.get("counts", {}).get("missing") or 0) == 0 and int(completion.get("counts", {}).get("failed") or 0) == 0, f"完成度审计：{completion.get('completion_state') or 'missing'}"),
            self._check("v22_stage_feature_scope", bool(v22_features) and v22_feature_scope_valid(v22_stage, v22_features), "V2.2只开启当前阶段获准的基础能力。"),
            self._check("v22_immutable_boundaries", bool(v22_boundaries) and all(value is False for value in v22_boundaries.values()), "V2.2不自动交易、不自动修改用户资产、不晋升模型、不停用V1。"),
            self._check("v22_baseline", v22_baseline.get("status") == "passed" and v22_baseline.get("scope", {}).get("user_assets_modified") is False, f"V2.2基线防护：{v22_baseline.get('status') or 'missing'}"),
            self._check("v22_watchlist_shadow_guard", v22_watchlist.get("guardrails", {}).get("migration_applied") is False and v22_watchlist.get("guardrails", {}).get("user_assets_modified") is False and v22_watchlist.get("guardrails", {}).get("delete_applied") is False, "同花顺只生成影子对照，不应用增删。"),
            self._check("v22_stock_pool_layers", v22_stock_pool.get("mode") == "shadow_only" and v22_stock_pool.get("guardrails", {}).get("user_assets_modified") is False and v22_stock_pool.get("guardrails", {}).get("temporary_candidate_auto_upgraded") is False, "五层股票池只生成影子读取模型，不自动扩池。"),
            self._check("v22_market_environment_facts", v22_environment.get("mode") == "shadow_only" and v22_environment.get("facts_only") is True and len(v22_environment.get("dimensions") or []) == 8, "市场环境已生成八维事实影子，不替换现有行动结论。"),
            self._check("v22_market_environment_boundaries", v22_environment.get("guardrails", {}).get("current_v2_action_modified") is False and v22_environment.get("guardrails", {}).get("environment_state_machine_enabled") is False and v22_environment.get("guardrails", {}).get("mixed_trade_dates_used_as_current") is False and v22_environment.get("guardrails", {}).get("missing_facts_ai_filled") is False, "环境事实不混用交易日、不由AI补事实，也不提前启用状态机。"),
            self._check("v22_environment_immutable_snapshot", int(v22_environment_index.get("snapshot_count") or 0) > 0 and any(item.get("environment_snapshot_id") == v22_environment.get("environment_snapshot_id") and item.get("immutable_hash") == v22_environment.get("immutable_hash") for item in v22_environment_index.get("snapshots") or [] if isinstance(item, dict)), "当前环境候选已保存不可覆盖快照。"),
            self._check("v22_environment_state_machine", v22_environment_decision.get("mode") == "shadow_only" and v22_environment_decision.get("primary_state") in {"risk_release", "repair", "rotation_trial", "mainline_confirmed", "diffusion_strengthening", "crowding_divergence", "retreat"} and v22_environment_decision.get("state_transition", {}).get("positive_upgrade_requires_two_checks") is True, "七态环境状态机已启用影子判断，正向升级需要连续确认。"),
            self._check("v22_style_boundaries", {item.get("style_id") for item in v22_environment_decision.get("style_regimes") or [] if isinstance(item, dict)} == {"old_deng", "middle_deng", "small_deng", "microcap"} and all(item.get("user_assets_modified") is False for item in v22_environment_decision.get("style_regimes") or [] if isinstance(item, dict)), "老登、中登、小登与微盘独立观察，均不修改用户资产。"),
            self._check("v22_cross_market_validation", all(item.get("transmission_state") in {"background_only", "pending", "confirmed", "divergent"} and item.get("single_company_event_theme_upgrade") is False for item in v22_environment_decision.get("cross_market_mappings") or [] if isinstance(item, dict)), "外盘映射要求A股代表股兑现，单一公司事件不自动升级主题。"),
            self._check("v22_g5_gate", bool(v22_environment_decision.get("g5_links")) and all(item.get("g5_result") in {"support", "partial_support", "neutral", "suppress", "block"} and item.get("representative_stock_gate_still_required") is True and item.get("position_gate_still_required") is True for item in v22_environment_decision.get("g5_links") or [] if isinstance(item, dict)), "G5环境门禁已形成影子结果，且不能绕过代表股与位置门禁。"),
            self._check("v22_environment_decision_boundaries", v22_environment_decision.get("guardrails", {}).get("automatic_trading") is False and v22_environment_decision.get("guardrails", {}).get("user_assets_modified") is False and v22_environment_decision.get("guardrails", {}).get("model_promoted") is False and v22_environment_decision.get("guardrails", {}).get("g5_bypasses_other_gates") is False, "E5不自动交易、不改用户资产、不晋升模型，也不让G5绕过其他门禁。"),
            self._check("v22_environment_decision_snapshot", int(v22_environment_decision_index.get("snapshot_count") or 0) > 0 and any(item.get("decision_snapshot_id") == v22_environment_decision.get("decision_snapshot_id") and item.get("immutable_hash") == v22_environment_decision.get("immutable_hash") for item in v22_environment_decision_index.get("snapshots") or [] if isinstance(item, dict)), "E5环境决策已保存不可覆盖快照。"),
            self._check("v22_decision_cases", v22_cases.get("mode") == "shadow_only" and int(v22_cases.get("case_count") or 0) > 0 and all({item.get("gate_id") for item in case.get("gates") or [] if isinstance(item, dict)} == {"G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7"} for case in v22_cases.get("cases") or [] if isinstance(case, dict)), "决策案例已去重并逐例运行八道透明门禁。"),
            self._check("v22_candidate_projection", v22_candidate.get("mode") == "shadow_only" and v22_candidate.get("case_batch_id") == v22_cases.get("case_batch_id") and all(item.get("representative_stocks") and all(stock.get("stock_code") and stock.get("stock_change_pct") is not None and stock.get("stock_quote_as_of") and stock.get("stock_quote_source") for stock in item.get("representative_stocks") or [] if isinstance(stock, dict)) for item in [*v22_candidate.get("current_cases", []), *v22_candidate.get("validation_cases", [])] if isinstance(item, dict)), "V2.2候选投影只显示代表股行情闭环的当前或观察案例。"),
            self._check("v22_no_unearned_ready_case", all(not (case.get("maturity") == "decision_ready" and any(gate.get("state") != "pass" for gate in case.get("gates") or [] if isinstance(gate, dict))) for case in v22_cases.get("cases") or [] if isinstance(case, dict)), "任何决策就绪案例均通过G0至G7；已核验不等于决策就绪。"),
            self._check("v22_case_snapshot", int(v22_case_index.get("snapshot_count") or 0) > 0 and any(item.get("case_batch_id") == v22_cases.get("case_batch_id") and item.get("immutable_hash") == v22_cases.get("immutable_hash") for item in v22_case_index.get("snapshots") or [] if isinstance(item, dict)), "当前决策案例批次已保存不可覆盖快照。"),
            self._check("v22_case_boundaries", v22_cases.get("guardrails", {}).get("baseline_v2_output_modified") is False and v22_cases.get("guardrails", {}).get("automatic_trading") is False and v22_cases.get("guardrails", {}).get("user_assets_modified") is False and v22_cases.get("guardrails", {}).get("model_promoted") is False, "E6不改V2基线、不自动交易、不改用户资产、不晋升模型。"),
            self._check("v22_time_semantics", v22_time_semantics.get("mode") == "shadow_only" and v22_time_semantics.get("guardrails", {}).get("mixed_trade_dates_compared") is False and v22_time_semantics.get("guardrails", {}).get("historical_data_rewritten") is False, "交易日、证据时间、行情时间、采集时间和生成时间已分开记录。"),
            self._check("v22_trigger_quote_guard", v22_trigger_index.get("mode") == "shadow_only" and v22_trigger_index.get("guardrails", {}).get("historical_quotes_backfilled") is False and v22_trigger_index.get("guardrails", {}).get("same_state_duplicate_created") is False and v22_trigger_report.get("guardrails", {}).get("user_assets_modified") is False, "触发行情只保存同交易日首次观察，不反向补造历史价格。"),
            self._check("v22_outcome_price_guard", v22_outcome_prices.get("mode") == "shadow_only" and v22_outcome_prices.get("guardrails", {}).get("current_price_used_as_historical_trigger") is False and v22_outcome_prices.get("guardrails", {}).get("not_due_window_filled") is False and v22_outcome_prices.get("guardrails", {}).get("missing_price_treated_as_zero") is False and v22_outcome_report.get("guardrails", {}).get("verified_result_overwritten") is False, "结果回填只处理到期窗口，缺失行情不按零处理且不覆盖已验证结果。"),
            self._check("v22_replay_learning", int(v22_replay.get("snapshot_count") or 0) > 0 and v22_replay.get("guardrails", {}).get("historical_snapshot_rewritten") is False and v22_replay.get("guardrails", {}).get("later_evidence_backfilled_as_known") is False, "V2.2案例快照进入独立回溯索引，不重写当时证据。"),
            self._check("v22_outcome_integrity", v22_outcomes.get("guardrails", {}).get("current_quote_used_as_historical_reference") is False and v22_outcomes.get("guardrails", {}).get("hit_rate_published") is False, "缺少触发时点参考价时不评价，不以当前行情冒充历史参考价。"),
            self._check("v22_offline_evaluation", v22_evaluation.get("mode") == "offline_shadow_only" and v22_evaluation.get("automatic_live_promotion") is False and (int(v22_evaluation.get("record_count") or 0) > 0 or v22_evaluation.get("metrics_published") is False), "候选只做离线评价；样本不足不展示命中率。"),
            self._check("v22_parallel_hold", v22_parallel.get("mode") == "parallel_shadow" and v22_parallel.get("cutover", {}).get("ready") is False and v22_parallel.get("guardrails", {}).get("automatic_cutover") is False, "V2基线与V2.2只做双轨对照，不自动切换。"),
            self._check("v22_final_acceptance", v22_final_acceptance.get("status") == "passed" and v22_final_acceptance.get("production_promotion") == "hold", "V2.2工程链路验收通过，生产晋级保持等待。"),
            self._check("v22_intraday_shadow_guard", v22_intraday_config.get("mode") == "shadow_only" and len(v22_intraday_config.get("checkpoints") or []) >= 7 and all(value is False for value in (v22_intraday_config.get("guardrails") or {}).values()), "盘中影子任务覆盖关键时点，且不改V1、不交易、不改用户资产、不晋升模型。"),
            self._check("v22_public_market_fact_guard", v22_fact_health.get("mode") == "shadow_only" and v22_fact_health.get("state") in {"usable", "degraded", "waiting_update"} and v22_fact_health.get("guardrails", {}).get("public_sources_only") is True and v22_fact_health.get("guardrails", {}).get("user_assets_read") is False and v22_fact_health.get("guardrails", {}).get("missing_facts_ai_filled") is False, "市场事实来自公开行情；备用源、待更新和缺失项显式降级，不由AI补造。"),
            self._check("v22_platform_skills", int(v22_skill_validation.get("skill_count") or 0) == 4 and int(v22_skill_validation.get("scenario_count") or 0) >= 8 and int(v22_skill_validation.get("failed_count") or 0) == 0 and v22_skill_validation.get("guardrails", {}).get("user_assets_modified") is False, "四个高频Skill已按只读边界通过真实场景验收。"),
            self._check("v22_watchlist_three_way_guard", v22_three_way.get("state") in {"source_completeness_blocked", "ready_for_user_migration_review"} and v22_three_way.get("guardrails", {}).get("migration_applied") is False and v22_three_way.get("guardrails", {}).get("deletion_applied") is False and v22_three_way.get("guardrails", {}).get("style_pool_used_as_user_pool") is False, "同花顺、旧观察名单和证券主表已生成三方影子对照；完整性不足时继续阻断迁移。"),
            self._check("v22_runtime_public_import_guard", v22_runtime_import.get("state") == "completed" and v22_runtime_import.get("deployment_fingerprint_verified") is True and v22_runtime_import.get("guardrails", {}).get("private_runtime_data_imported") is False and v22_runtime_import.get("guardrails", {}).get("user_assets_modified") is False, "盘中运行时结果只按部署指纹和公开字段门禁合并回工作树。"),
        ]
        quality_state = decision.get("data_quality_gate", {}).get("state") or "missing"
        promotion_state = "ready_for_user_confirmation" if all(item["passed"] for item in checks) and quality_state == "usable" else "hold"
        confirmation_items = [
            {
                "id": "style_taxonomy",
                "status": "implemented_needs_user_confirmation",
                "question": "确认中登以新能源、电力设备、医药、军工、有色等上一轮成长产业为核心，小登以当前前沿科技为核心。"
            },
            {
                "id": "microcap_proxy",
                "status": "secondary_proxy_active",
                "question": "微盘独立于小登；当前使用新浪公开中证2000行情作为次级宽基代理，纯微盘口径仍等待授权数据源。"
            },
            {
                "id": "research_gaps",
                "status": "templates_ready_mapping_evidence_pending",
                "question": "核聚变和量子研究模板已建立；上市公司映射继续要求公告、订单或收入证据，不按概念标签补齐。"
            },
            {
                "id": "stock_roles",
                "status": "evidence_pending",
                "question": f"股票池有 {stock_pool.get('role_unclassified_count') or 0} 只缺少显式龙头/中军/弹性角色证据，确认继续保持未分类而非AI猜测。"
            },
            {
                "id": "portfolio_and_outcomes",
                "status": "data_authorization_pending",
                "question": "真实持仓、成本、微盘行情、回溯价格及博主账号尚未授权/提供；接入前继续只给规则提示和待验证结果。"
            },
            {
                "id": "production_promotion",
                "status": "parallel_run_confirmed_cutover_deferred",
                "question": "已确认先双轨并行；只有V2稳定且您再次授权后，才切换主入口或停用V1。"
            },
        ]
        return {
            "schema_version": 1,
            "generated_at": now_iso(),
            "shadow_acceptance": "passed" if all(item["passed"] for item in checks) else "failed",
            "production_promotion": promotion_state,
            "production_hold_reason": "关键数据仍为降级状态。" if quality_state != "usable" else None,
            "quality_state": quality_state,
            "checks": checks,
            "rollback_rehearsal": {
                "status": "passed" if v1_code["passed"] else "failed",
                "method": "验证V1程序、入口、脚本和配置相对冻结基线未改变；允许生产数据按原任务继续提交。",
                "production_head": production_head,
                "baseline_commit": baseline,
                "protected_paths": protected_paths,
                "changed_protected_paths": v1_code["changed_paths"],
                "v2_head": git_output(self.root, "rev-parse", "HEAD"),
                "v22_stage": (self.rollout.get("v2_2") or {}).get("stage"),
                "v22_feature_flags": self.rollout.get("v2_2", {}).get("feature_flags"),
            },
            "confirmation_items": confirmation_items,
        }

    @staticmethod
    def _check(check_id: str, passed: bool, detail: str) -> dict[str, Any]:
        return {"id": check_id, "passed": bool(passed), "detail": detail}

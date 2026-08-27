#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_IDS = {
    "data-quality-gate",
    "market-environment",
    "opportunity-risk-radar",
    "validation-queue",
    "style-map",
    "portfolio-risk",
    "research-themes",
    "signal-review",
    "stock-pool",
    "stock-pool-search",
    "governance-status",
    "source-registry",
    "watchlist-sync-shadow",
    "stock-pool-v22",
    "user-asset-layer",
    "formal-observation-layer",
    "temporary-candidate-layer",
    "cockpit-user-assets",
    "cockpit-phase-title",
    "cockpit-phase-view",
    "market-environment-v22",
    "market-environment-v22-summary",
    "market-environment-v22-decision",
    "market-sentiment-v22",
    "market-environment-v22-dimensions",
    "market-environment-v22-sources",
    "style-regime-v22",
    "cross-market-v22",
    "v22-learning-summary",
    "industry-tracking-summary",
    "industry-tracking-cards",
    "logic-search",
    "logic-category-filter",
    "logic-result-summary",
    "logic-catalog",
}
REQUIRED_DATA_KEYS = {
    "system",
    "data_quality_gate",
    "market_environment",
    "opportunity_radar",
    "opportunity_history",
    "validation_queue",
    "style_map",
    "market_structure",
    "portfolio_risk",
    "research_themes",
    "research_library",
    "stock_pool",
    "governance",
    "input_status",
    "model_evaluation",
    "signal_review",
    "source_registry",
}
PAGE_FILES = [
    "v2.html", "v2-trading.html", "v2-premarket.html", "v2-radar.html",
    "v2-midday.html", "v2-postmarket.html", "v2-evening.html", "v2-market.html",
    "v2-research.html", "v2-stock-pool.html", "v2-review.html", "v2-system.html",
    "v2-governance.html", "v2-logic.html",
]


def main() -> int:
    issues: list[dict[str, str]] = []
    pages = {name: (ROOT / name).read_text(encoding="utf-8") for name in PAGE_FILES}
    html = "\n".join(pages.values())
    ids = set(re.findall(r'id="([^"]+)"', html))
    for missing in sorted(REQUIRED_IDS - ids):
        issues.append({"severity": "critical", "code": "missing_v2_container", "message": missing})
    for page_name, page_html in pages.items():
        for href in re.findall(r'href="(v2(?:-[^"]+)?\.html)"', page_html):
            if not (ROOT / href).exists():
                issues.append({"severity": "critical", "code": "broken_v2_page_link", "message": f"{page_name}: {href}"})
    global_labels = ["交易系统", "产业研究", "股票池", "复盘学习", "系统说明"]
    for page_name in ("v2.html", "v2-trading.html", "v2-research.html", "v2-stock-pool.html", "v2-review.html", "v2-system.html"):
        match = re.search(r'<nav class="v2-nav global-nav"[^>]*>(.*?)</nav>', pages[page_name], re.S)
        labels = [] if match is None else [re.sub(r"<[^>]+>", "", value).strip() for value in re.findall(r'<a[^>]*>(.*?)</a>', match.group(1), re.S)]
        if labels[:5] != global_labels or "市场环境" in labels:
            issues.append({"severity": "critical", "code": "v2_global_navigation_contract", "message": page_name})
    daily_labels = ["今日", "盘前预案", "盘中异动", "午盘判断", "盘后复盘", "晚间舆情"]
    for page_name in ("v2-trading.html", "v2-premarket.html", "v2-radar.html", "v2-midday.html", "v2-postmarket.html", "v2-evening.html", "v2-market.html"):
        match = re.search(r'<nav class="trading-nav"[^>]*>(.*?)</nav>', pages[page_name], re.S)
        labels = [] if match is None else [re.sub(r"<[^>]+>", "", value).strip() for value in re.findall(r'<a[^>]*>(.*?)</a>', match.group(1), re.S)]
        if labels != daily_labels:
            issues.append({"severity": "critical", "code": "v2_daily_navigation_contract", "message": page_name})
    node = Path("/Users/sweet_orange/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
    binary = str(node if node.exists() else "node")
    checked = subprocess.run([binary, "--check", str(ROOT / "v2.js")], capture_output=True, text=True)
    if checked.returncode:
        issues.append({"severity": "critical", "code": "v2_js_syntax", "message": checked.stderr.strip()})
    try:
        data = json.loads((ROOT / "data" / "v2" / "decision-system.json").read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append({"severity": "critical", "code": "v2_data_invalid", "message": str(exc)})
        data = {}
    try:
        logic_catalog = json.loads((ROOT / "data" / "v2" / "logic-catalog.json").read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append({"severity": "critical", "code": "v2_logic_catalog_invalid", "message": str(exc)})
        logic_catalog = {}
    try:
        cockpit_phase = json.loads((ROOT / "data" / "v2" / "v22" / "cockpit-phase-view.json").read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append({"severity": "critical", "code": "v22_cockpit_phase_invalid", "message": str(exc)})
        cockpit_phase = {}
    if cockpit_phase.get("mode") != "shadow_only" or cockpit_phase.get("stage") not in {"pre_market", "intraday_validation", "close_validation", "waiting_next_session"}:
        issues.append({"severity": "critical", "code": "v22_cockpit_phase_contract", "message": "交易阶段视图缺失或不是影子结果"})
    cockpit_guardrails = cockpit_phase.get("guardrails") if isinstance(cockpit_phase.get("guardrails"), dict) else {}
    for key in ("automatic_trading", "user_assets_modified", "model_promoted", "v1_modified", "stale_data_used_as_current", "missing_facts_ai_filled"):
        if cockpit_guardrails.get(key) is not False:
            issues.append({"severity": "critical", "code": "v22_cockpit_phase_guardrail", "message": key})
    if len(logic_catalog.get("entries") or []) < 18 or len(logic_catalog.get("categories") or []) < 7:
        issues.append({"severity": "critical", "code": "v2_logic_catalog_incomplete", "message": "统一逻辑目录内容不足"})
    try:
        v22_stock_pool = json.loads((ROOT / "data" / "v2" / "v22" / "stock-pool-shadow.json").read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append({"severity": "critical", "code": "v22_stock_pool_invalid", "message": str(exc)})
        v22_stock_pool = {}
    try:
        v22_industry_tracking = json.loads((ROOT / "data" / "v2" / "v22" / "industry-tracking.json").read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append({"severity": "critical", "code": "v22_industry_tracking_invalid", "message": str(exc)})
        v22_industry_tracking = {}
    tracked_industries = v22_industry_tracking.get("items") or []
    tracked_by_name = {item.get("name"): item for item in tracked_industries if isinstance(item, dict)}
    required_ai_industries = {"AI训练基础设施持续观察", "端侧AI推理持续观察"}
    ai_stocks = [stock for name in required_ai_industries for stock in (tracked_by_name.get(name, {}).get("representative_stocks") or [])]
    if v22_industry_tracking.get("mode") != "shadow_only" or not required_ai_industries.issubset(tracked_by_name) or len(ai_stocks) != 8:
        issues.append({"severity": "critical", "code": "v22_industry_tracking_contract", "message": "AI训练与端侧推理必须保持两条产业链、八只代表股的影子观察"})
    industry_guardrails = v22_industry_tracking.get("guardrails") if isinstance(v22_industry_tracking.get("guardrails"), dict) else {}
    for key in ("automatic_trading", "user_assets_modified", "v1_modified", "automatic_classification_upgrade", "missing_evidence_ai_filled"):
        if industry_guardrails.get(key) is not False:
            issues.append({"severity": "critical", "code": "v22_industry_tracking_guardrail", "message": key})
    try:
        v22_environment = json.loads((ROOT / "data" / "v2" / "v22" / "market-environment.json").read_text(encoding="utf-8"))
        v22_environment_index = json.loads((ROOT / "data" / "v2" / "v22" / "environment-snapshot-index.json").read_text(encoding="utf-8"))
        v22_environment_decision = json.loads((ROOT / "data" / "v2" / "v22" / "environment-decision.json").read_text(encoding="utf-8"))
        v22_environment_decision_index = json.loads((ROOT / "data" / "v2" / "v22" / "environment-decision-snapshot-index.json").read_text(encoding="utf-8"))
        v22_cases = json.loads((ROOT / "data" / "v2" / "v22" / "decision-cases.json").read_text(encoding="utf-8"))
        v22_candidate = json.loads((ROOT / "data" / "v2" / "v22" / "decision-system-candidate.json").read_text(encoding="utf-8"))
        v22_case_index = json.loads((ROOT / "data" / "v2" / "v22" / "decision-case-snapshot-index.json").read_text(encoding="utf-8"))
        v22_time_semantics = json.loads((ROOT / "data" / "v2" / "v22" / "time-semantics.json").read_text(encoding="utf-8"))
        v22_trigger_index = json.loads((ROOT / "data" / "v2" / "v22" / "trigger-quote-index.json").read_text(encoding="utf-8"))
        v22_trigger_report = json.loads((ROOT / "data" / "v2" / "v22" / "trigger-quote-capture-report.json").read_text(encoding="utf-8"))
        v22_outcome_prices = json.loads((ROOT / "data" / "v2" / "v22" / "outcome-prices.json").read_text(encoding="utf-8"))
        v22_outcome_report = json.loads((ROOT / "data" / "v2" / "v22" / "outcome-price-report.json").read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append({"severity": "critical", "code": "v22_environment_invalid", "message": str(exc)})
        v22_environment = {}
        v22_environment_index = {}
        v22_environment_decision = {}
        v22_environment_decision_index = {}
        v22_cases = {}
        v22_candidate = {}
        v22_case_index = {}
        v22_time_semantics = {}
        v22_trigger_index = {}
        v22_trigger_report = {}
        v22_outcome_prices = {}
        v22_outcome_report = {}
    if v22_stock_pool.get("mode") != "shadow_only":
        issues.append({"severity": "critical", "code": "v22_stock_pool_not_shadow", "message": "股票池分层不是影子模式"})
    guardrails = v22_stock_pool.get("guardrails") if isinstance(v22_stock_pool.get("guardrails"), dict) else {}
    if guardrails.get("user_assets_modified") is not False or guardrails.get("temporary_candidate_auto_upgraded") is not False:
        issues.append({"severity": "critical", "code": "v22_stock_pool_guardrail", "message": "用户资产或临时候选边界未保持"})
    public_text = json.dumps(v22_stock_pool, ensure_ascii=False)
    for forbidden in ("user_priority", "user_intent", "user_note", "source_account_id"):
        if forbidden in public_text:
            issues.append({"severity": "critical", "code": "v22_private_field_published", "message": forbidden})
    expected_dimensions = {"index_structure", "liquidity", "market_breadth", "mainline_structure", "sentiment_structure", "style_structure", "position_fragility", "external_constraint"}
    actual_dimensions = {item.get("dimension_code") for item in v22_environment.get("dimensions") or [] if isinstance(item, dict)}
    if v22_environment.get("mode") != "shadow_only" or v22_environment.get("facts_only") is not True or actual_dimensions != expected_dimensions:
        issues.append({"severity": "critical", "code": "v22_environment_contract", "message": "八维环境不是完整的事实影子"})
    environment_guardrails = v22_environment.get("guardrails") if isinstance(v22_environment.get("guardrails"), dict) else {}
    for key in ("current_v2_action_modified", "environment_state_machine_enabled", "mixed_trade_dates_used_as_current", "missing_facts_ai_filled", "user_assets_modified"):
        if environment_guardrails.get(key) is not False:
            issues.append({"severity": "critical", "code": "v22_environment_guardrail", "message": key})
    current_environment_id = v22_environment.get("environment_snapshot_id")
    if not any(item.get("environment_snapshot_id") == current_environment_id and item.get("immutable_hash") == v22_environment.get("immutable_hash") for item in v22_environment_index.get("snapshots") or [] if isinstance(item, dict)):
        issues.append({"severity": "critical", "code": "v22_environment_snapshot_missing", "message": str(current_environment_id or "missing")})
    environment_text = json.dumps(v22_environment, ensure_ascii=False)
    for forbidden in ("user_priority", "user_intent", "user_note", "watchlist_source", "source_account_id"):
        if forbidden in environment_text:
            issues.append({"severity": "critical", "code": "v22_environment_private_field", "message": forbidden})
    valid_states = {"risk_release", "repair", "rotation_trial", "mainline_confirmed", "diffusion_strengthening", "crowding_divergence", "retreat"}
    if v22_environment_decision.get("mode") != "shadow_only" or v22_environment_decision.get("primary_state") not in valid_states:
        issues.append({"severity": "critical", "code": "v22_environment_decision_contract", "message": "七态环境影子结果缺失"})
    if {item.get("style_id") for item in v22_environment_decision.get("style_regimes") or [] if isinstance(item, dict)} != {"old_deng", "middle_deng", "small_deng", "microcap"}:
        issues.append({"severity": "critical", "code": "v22_style_contract", "message": "风格观察未保持四类独立口径"})
    for item in v22_environment_decision.get("cross_market_mappings") or []:
        if isinstance(item, dict) and (item.get("transmission_state") not in {"background_only", "pending", "confirmed", "divergent"} or item.get("single_company_event_theme_upgrade") is not False):
            issues.append({"severity": "critical", "code": "v22_cross_market_contract", "message": str(item.get("mapping_id") or "未知映射")})
    g5_ids = {item.get("opportunity_id") for item in v22_environment_decision.get("g5_links") or [] if isinstance(item, dict)}
    expected_g5_ids = {item.get("id") for item in [*data.get("opportunity_radar", []), *data.get("validation_queue", [])] if isinstance(item, dict) and item.get("id")}
    if g5_ids != expected_g5_ids:
        issues.append({"severity": "critical", "code": "v22_g5_coverage", "message": f"应覆盖{len(expected_g5_ids)}条，实际{len(g5_ids)}条"})
    decision_guardrails = v22_environment_decision.get("guardrails") if isinstance(v22_environment_decision.get("guardrails"), dict) else {}
    for key in ("automatic_trading", "user_assets_modified", "model_promoted", "g5_bypasses_other_gates", "style_pool_used_as_user_pool"):
        if decision_guardrails.get(key) is not False:
            issues.append({"severity": "critical", "code": "v22_environment_decision_guardrail", "message": key})
    current_decision_id = v22_environment_decision.get("decision_snapshot_id")
    if not any(item.get("decision_snapshot_id") == current_decision_id and item.get("immutable_hash") == v22_environment_decision.get("immutable_hash") for item in v22_environment_decision_index.get("snapshots") or [] if isinstance(item, dict)):
        issues.append({"severity": "critical", "code": "v22_environment_decision_snapshot_missing", "message": str(current_decision_id or "missing")})
    decision_text = json.dumps(v22_environment_decision, ensure_ascii=False)
    for forbidden in ("user_priority", "user_intent", "user_note", "watchlist_source", "source_account_id"):
        if forbidden in decision_text:
            issues.append({"severity": "critical", "code": "v22_environment_decision_private_field", "message": forbidden})
    if v22_cases.get("mode") != "shadow_only" or v22_candidate.get("mode") != "shadow_only" or v22_cases.get("case_batch_id") != v22_candidate.get("case_batch_id"):
        issues.append({"severity": "critical", "code": "v22_decision_case_contract", "message": "案例或候选投影不是同一影子批次"})
    expected_gates = {f"G{index}" for index in range(8)}
    for case in v22_cases.get("cases") or []:
        if isinstance(case, dict) and {item.get("gate_id") for item in case.get("gates") or [] if isinstance(item, dict)} != expected_gates:
            issues.append({"severity": "critical", "code": "v22_decision_gate_contract", "message": str(case.get("case_id") or "missing")})
        if isinstance(case, dict) and case.get("maturity") == "decision_ready" and any(item.get("state") != "pass" for item in case.get("gates") or [] if isinstance(item, dict)):
            issues.append({"severity": "critical", "code": "v22_unearned_decision_ready", "message": str(case.get("case_id") or "missing")})
    for card in [*v22_candidate.get("current_cases", []), *v22_candidate.get("validation_cases", [])]:
        if not isinstance(card, dict) or not card.get("representative_stocks"):
            issues.append({"severity": "critical", "code": "v22_visible_case_missing_representatives", "message": str(card.get("title") if isinstance(card, dict) else "invalid")})
            continue
        for stock in card.get("representative_stocks") or []:
            if not isinstance(stock, dict) or any(stock.get(field) is None for field in ("stock_code", "name", "stock_change_pct", "stock_quote_as_of", "stock_quote_source", "role", "basis")):
                issues.append({"severity": "critical", "code": "v22_visible_case_incomplete_quote", "message": str(card.get("title") or "missing")})
    case_guardrails = v22_cases.get("guardrails") if isinstance(v22_cases.get("guardrails"), dict) else {}
    for key in ("baseline_v2_output_modified", "automatic_trading", "user_assets_modified", "temporary_candidate_auto_upgraded", "model_promoted"):
        if case_guardrails.get(key) is not False:
            issues.append({"severity": "critical", "code": "v22_decision_case_guardrail", "message": key})
    if not any(item.get("case_batch_id") == v22_cases.get("case_batch_id") and item.get("immutable_hash") == v22_cases.get("immutable_hash") for item in v22_case_index.get("snapshots") or [] if isinstance(item, dict)):
        issues.append({"severity": "critical", "code": "v22_decision_case_snapshot_missing", "message": str(v22_cases.get("case_batch_id") or "missing")})
    case_text = json.dumps([v22_cases, v22_candidate], ensure_ascii=False)
    for forbidden in ("user_priority", "user_intent", "user_note", "watchlist_source", "source_account_id"):
        if forbidden in case_text:
            issues.append({"severity": "critical", "code": "v22_decision_case_private_field", "message": forbidden})
    time_guardrails = v22_time_semantics.get("guardrails") if isinstance(v22_time_semantics.get("guardrails"), dict) else {}
    time_comparison = v22_time_semantics.get("comparison") if isinstance(v22_time_semantics.get("comparison"), dict) else {}
    if v22_time_semantics.get("mode") != "shadow_only" or time_guardrails.get("mixed_trade_dates_compared") is not False or time_guardrails.get("generated_at_used_as_market_date") is not False:
        issues.append({"severity": "critical", "code": "v22_time_semantics_guardrail", "message": "时间口径门禁未保持"})
    if time_comparison.get("allowed") is not True and time_comparison.get("hit_rate_comparison_allowed") is not False:
        issues.append({"severity": "critical", "code": "v22_cross_date_comparison", "message": "交易日不一致时仍允许比较命中率"})
    trigger_guardrails = v22_trigger_index.get("guardrails") if isinstance(v22_trigger_index.get("guardrails"), dict) else {}
    if v22_trigger_index.get("mode") != "shadow_only" or trigger_guardrails.get("historical_quotes_backfilled") is not False or trigger_guardrails.get("same_state_duplicate_created") is not False:
        issues.append({"severity": "critical", "code": "v22_trigger_quote_guardrail", "message": "触发行情快照边界未保持"})
    if v22_trigger_report.get("guardrails", {}).get("user_assets_modified") is not False:
        issues.append({"severity": "critical", "code": "v22_trigger_user_asset_boundary", "message": "触发行情流程触及用户资产"})
    outcome_guardrails = v22_outcome_prices.get("guardrails") if isinstance(v22_outcome_prices.get("guardrails"), dict) else {}
    required_outcome_guards = ("current_price_used_as_historical_trigger", "not_due_window_filled", "missing_price_treated_as_zero", "verified_result_overwritten", "automatic_trading", "user_assets_modified")
    if v22_outcome_prices.get("mode") != "shadow_only" or any(outcome_guardrails.get(key) is not False for key in required_outcome_guards):
        issues.append({"severity": "critical", "code": "v22_outcome_price_guardrail", "message": "结果价格回填边界未保持"})
    if v22_outcome_report.get("guardrails", {}).get("verified_result_overwritten") is not False:
        issues.append({"severity": "critical", "code": "v22_outcome_overwrite_report", "message": "结果回填报告未声明防覆盖"})
    s1_public_text = json.dumps([v22_time_semantics, v22_trigger_index, v22_trigger_report, v22_outcome_prices, v22_outcome_report], ensure_ascii=False)
    for forbidden in ("user_priority", "user_intent", "user_note", "watchlist_source", "source_account_id"):
        if forbidden in s1_public_text:
            issues.append({"severity": "critical", "code": "v22_s1_private_field", "message": forbidden})
    for missing in sorted(REQUIRED_DATA_KEYS - set(data)):
        issues.append({"severity": "critical", "code": "missing_v2_data_key", "message": missing})
    for card in data.get("opportunity_radar", []):
        for forbidden in ("evidence_score", "signal_score", "signal_grade"):
            if forbidden in card:
                issues.append({"severity": "critical", "code": "abstract_score_exposed", "message": forbidden})
        for required in ("title", "trigger", "action", "evidence", "counter_evidence", "confirm_conditions", "invalidation_conditions"):
            if required not in card:
                issues.append({"severity": "critical", "code": "radar_contract_missing", "message": required})
        if not card.get("representative_stocks"):
            issues.append({"severity": "critical", "code": "radar_missing_representative_basis", "message": str(card.get("title") or "未命名卡片")})
        for stock in card.get("representative_stocks", []):
            if not isinstance(stock, dict) or not stock.get("name") or not stock.get("basis"):
                issues.append({"severity": "critical", "code": "radar_bad_representative_basis", "message": str(card.get("title") or "未命名卡片")})
            if isinstance(stock, dict) and stock.get("stock_change_pct") is not None and not stock.get("stock_quote_as_of"):
                issues.append({"severity": "critical", "code": "stock_quote_time_missing", "message": str(stock.get("name") or "未知标的")})
            if isinstance(stock, dict) and stock.get("stock_change_pct") is not None and not stock.get("stock_quote_source"):
                issues.append({"severity": "critical", "code": "stock_quote_source_missing", "message": str(stock.get("name") or "未知标的")})
    for item in data.get("validation_queue", []):
        if not item.get("risk_factors") or not item.get("invalidation_conditions"):
            issues.append({"severity": "critical", "code": "validation_risk_contract_missing", "message": str(item.get("theme") or "未命名方向")})
    for card in [*data.get("opportunity_radar", []), *data.get("opportunity_history", []), *data.get("validation_queue", [])]:
        for stock in card.get("representative_stocks", []):
            if not isinstance(stock, dict):
                continue
            if not stock.get("stock_code"):
                issues.append({"severity": "critical", "code": "representative_stock_code_missing", "message": str(stock.get("name") or "未知标的")})
            if stock.get("stock_change_pct") is None or not stock.get("stock_quote_as_of") or not stock.get("stock_quote_source"):
                issues.append({"severity": "critical", "code": "representative_stock_quote_incomplete", "message": str(stock.get("name") or "未知标的")})
            if "领跌贡献" in str(stock.get("basis") or ""):
                issues.append({"severity": "critical", "code": "ambiguous_contribution_metric", "message": str(stock.get("name") or "未知标的")})
    if data.get("data_quality_gate", {}).get("state") != "usable":
        if any(card.get("state") == "confirmed" for card in data.get("opportunity_radar", [])):
            issues.append({"severity": "critical", "code": "confirmed_during_degradation", "message": "degraded data contains confirmed opportunity"})
    status = "critical" if any(item["severity"] == "critical" for item in issues) else "ok"
    report = {"status": status, "issues": issues, "required_ids": sorted(REQUIRED_IDS)}
    out = ROOT / "data" / "v2" / "smoke-report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"v2-smoke: {status}, issues={len(issues)}")
    return 1 if status == "critical" else 0


if __name__ == "__main__":
    raise SystemExit(main())

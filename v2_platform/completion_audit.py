from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2_platform.learning import as_dict, as_list, load_json


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def git_output(path: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


class V2CompletionAuditBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.project_root = self.root.parent.parent
        self.data = self.root / "data" / "v2"

    def build(self) -> dict[str, Any]:
        decision = load_json(self.data / "decision-system.json")
        market = as_dict(decision.get("market_structure"))
        research = as_dict(decision.get("research_library"))
        stock_pool = as_dict(decision.get("stock_pool"))
        governance = as_dict(decision.get("governance"))
        review = as_dict(decision.get("signal_review"))
        environment = as_dict(decision.get("market_environment"))
        style = as_dict(decision.get("style_map"))
        sentiment = as_dict(environment.get("sentiment_structure"))
        radar = as_list(decision.get("opportunity_radar"))
        rollout = load_json(self.root / "config" / "v2-rollout.json")
        production = Path(str(as_dict(rollout.get("production_v1")).get("path") or ""))
        checks = [
            self._check("design_document", "proven" if self._doc("AI投资决策系统V2.0_总体设计文档.md") else "missing", "总体设计文档"),
            self._check("migration_audit", "proven" if self._doc("AI投资决策系统V2.0_现状迁移审计_第一批.md") and self._doc("AI投资决策系统V2.0_阶段0审计补充_运行与前端依赖.md") else "missing", "现有模块与运行证据审计"),
            self._check("data_lineage_model", "proven" if self._doc("AI投资决策系统V2.0_数据模型血缘与决策流程.md") else "missing", "数据模型、血缘、时间戳和冲突规范"),
            self._check("phased_route_and_visual", "proven" if self._doc("AI投资决策系统V2.0_分阶段改造路线与视觉方案.md") and (self.root / "v2.html").exists() else "missing", "分阶段路线与V2页面"),
            self._check("data_quality_gate", "proven" if decision.get("data_quality_gate") and not any(item.get("state") == "confirmed" for item in radar) else "failed", "降级时不生成已确认机会"),
            self._check("idempotent_data_publisher", "proven" if (self.root / "v2_platform" / "publishing.py").exists() and (self.root / "tests" / "test_v2_publishing.py").exists() else "missing", "生成/发布分离、allowlist与幂等"),
            self._check("decision_cockpit_radar", "proven" if radar and all(self._radar_contract(item) for item in radar) else "failed", f"机会/风险雷达 {len(radar)} 条"),
            self._check("cross_market", self._cross_market_state(environment), "美股、港股、韩国市场显式覆盖；降级源只作背景"),
            self._check("style_dimensions", "proven" if {item.get("id") for item in as_list(style.get("dimensions"))} == {"old_deng", "middle_deng", "small_deng", "microcap"} else "failed", "老登/中登/小登/微盘独立"),
            self._check("microcap_data", "proven" if market.get("direction") != "unknown" else "data_pending", market.get("conclusion") or "微盘数据状态缺失"),
            self._check("two_sided_sentiment", self._sentiment_state(sentiment), "涨停与跌停梯队、高位亏钱效应均有字段；当前缺失项保持空"),
            self._check("research_room", "proven" if {item.get("id") for item in as_list(research.get("domains"))}.issuperset({"ai_hardware", "ai_software", "embodied_ai", "medicine", "fusion", "quantum"}) else "failed", "六大长期研究域及核聚变/量子模板"),
            self._check("stock_pool", "proven" if int(stock_pool.get("stock_count") or 0) > 0 else "failed", f"统一股票池 {stock_pool.get('stock_count') or 0} 只"),
            self._check("event_source_governance", "proven" if as_dict(governance.get("event_registry")).get("blogger_policy", {}).get("may_support_fact") is False else "failed", "博主内容仅作预期/情绪，事实/推断/建议分层"),
            self._check("event_input", "proven" if as_dict(governance.get("event_registry")).get("event_count") else "data_pending", "用户后续提供的博主账号和规范化事件输入尚未接入"),
            self._check("automation_routing", "proven" if as_dict(governance.get("automation_routing")).get("state") == "valid" and int(as_dict(governance.get("automation_routing")).get("task_count") or 0) >= 6 else "failed", "实时决策/长期研究/后台采集/复盘学习/运维五类归属"),
            self._check("immutable_replay", "proven" if int(review.get("snapshot_count") or 0) > 0 and review.get("hit_rate") is None else "failed", f"判断快照 {review.get('snapshot_count') or 0} 个，样本不足不展示命中率"),
            self._check("outcome_prices", "proven" if int(review.get("evaluated_signal_count") or 0) > 0 else "data_pending", "T+1/T+3/T+5/T+10结果价格尚未接入"),
            self._check("portfolio_authorization", "data_pending" if as_dict(decision.get("portfolio_risk")).get("state") == "rules_only" else "proven", "真实持仓、成本、现金和风险预算未接入"),
            self._check("no_automatic_trading", "proven" if decision.get("system", {}).get("mode") == "shadow_only" and load_json(self.root / "config" / "v2-learning-policy.json").get("model_change_policy", {}).get("automatic_live_weight_change") is False else "failed", "影子模式；不自动交易，不自动修改线上权重"),
            self._check("v1_rollback", "proven" if production.exists() and git_output(production, "rev-parse", "HEAD").startswith(str(as_dict(rollout.get("production_v1")).get("baseline_commit") or "")) else "failed", "生产V1保持冻结基线"),
            self._check("production_cutover", "user_confirmation" if decision.get("system", {}).get("mode") == "shadow_only" else "proven", "生产主入口切换属于重大产品选择，等待用户确认"),
        ]
        counts = {state: sum(item["state"] == state for item in checks) for state in ("proven", "data_pending", "user_confirmation", "missing", "failed")}
        hard_fail = counts["missing"] + counts["failed"]
        completion_state = "failed" if hard_fail else ("implemented_external_inputs_pending" if counts["data_pending"] or counts["user_confirmation"] else "complete")
        return {
            "schema_version": 1,
            "generated_at": now_iso(),
            "objective": "AI辅助投资决策系统V2.0完整重构",
            "completion_state": completion_state,
            "counts": counts,
            "checks": checks,
            "remaining_external_inputs": [item for item in checks if item["state"] in {"data_pending", "user_confirmation"}],
            "claim_guardrail": "只有所有检查均为 proven，才允许声明平台目标完成。",
        }

    def _doc(self, name: str) -> bool:
        return (self.project_root / name).exists()

    @staticmethod
    def _check(check_id: str, state: str, evidence: str) -> dict[str, Any]:
        return {"id": check_id, "state": state, "evidence": evidence}

    @staticmethod
    def _radar_contract(item: dict[str, Any]) -> bool:
        return all(key in item for key in ("trigger", "evidence", "counter_evidence", "confirm_conditions", "invalidation_conditions", "action"))

    @staticmethod
    def _cross_market_state(environment: dict[str, Any]) -> str:
        rows = {item.get("market"): item for item in as_list(environment.get("cross_market")) if isinstance(item, dict)}
        return "proven" if {"US", "HK", "KR"}.issubset(rows) else "failed"

    @staticmethod
    def _sentiment_state(sentiment: dict[str, Any]) -> str:
        required = ("limit_up_ladder", "limit_down_ladder", "high_level_loss_effect")
        if not all(key in sentiment for key in required):
            return "failed"
        if any(as_dict(sentiment.get(key)).get("state") == "data_missing" for key in required):
            return "data_pending"
        return "proven"

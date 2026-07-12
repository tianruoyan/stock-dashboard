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
        production_config = self.rollout.get("production_v1") or {}
        operation = self.rollout.get("operation_strategy") or {}
        production = Path(str(production_config.get("path") or ""))
        production_head = git_output(production, "rev-parse", "HEAD") if production.exists() else ""
        baseline = str(production_config.get("baseline_commit") or "")
        protected_paths = [str(item) for item in production_config.get("protected_paths") or []]
        v1_code = production_v1_code_state(production, baseline, protected_paths)
        checks = [
            self._check("v2_shadow_mode", decision.get("system", {}).get("mode") == "shadow_only", "V2仍为影子模式，不触发生产交易或通知。"),
            self._check("parallel_operation", operation.get("mode") == "parallel_shadow" and operation.get("v1_role") == "production_primary" and operation.get("stop_v1_requires_new_user_confirmation") is True, "用户已确认V1/V2双轨并行；停用V1需要再次确认。"),
            self._check("static_smoke", smoke.get("status") == "ok", f"V2页面检查：{smoke.get('status') or 'missing'}"),
            self._check("unified_build_not_blocked", build.get("status") != "blocked" and bool(build), f"统一构建：{build.get('status') or 'missing'}"),
            self._check("research_domains", len(research.get("domains") or []) >= 6, f"产业领域：{len(research.get('domains') or [])}"),
            self._check("stock_pool", int(stock_pool.get("stock_count") or 0) > 0, f"统一股票池：{stock_pool.get('stock_count') or 0}只"),
            self._check("immutable_replay", int(replay.get("snapshot_count") or 0) > 0, f"冻结快照：{replay.get('snapshot_count') or 0}个"),
            self._check("no_live_model_weight_change", learning.get("model_change_policy", {}).get("automatic_live_weight_change") is False, "禁止自动修改线上模型权重。"),
            self._check("production_v1_preserved", v1_code["passed"], f"V1程序与入口保持基线 {baseline}；数据提交可继续前进，当前 {production_head[:7] or 'missing'}。"),
            self._check("rollback_entry_exists", (production / str(production_config.get("entry") or "index.html")).exists(), "生产V1入口可作为即时回退入口。"),
            self._check("completion_audit_internal", int(completion.get("counts", {}).get("missing") or 0) == 0 and int(completion.get("counts", {}).get("failed") or 0) == 0, f"完成度审计：{completion.get('completion_state') or 'missing'}"),
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
            },
            "confirmation_items": confirmation_items,
        }

    @staticmethod
    def _check(check_id: str, passed: bool, detail: str) -> dict[str, Any]:
        return {"id": check_id, "passed": bool(passed), "detail": detail}

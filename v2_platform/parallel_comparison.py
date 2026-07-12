from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2_platform.learning import as_dict, as_list, load_json, write_json


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def git_head(path: Path) -> str:
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


class V2ParallelComparisonBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        rollout = load_json(self.root / "config" / "v2-rollout.json")
        self.operation = as_dict(rollout.get("operation_strategy"))
        self.v1_root = Path(str(as_dict(rollout.get("production_v1")).get("path") or ""))

    def build(self) -> dict[str, Any]:
        v1 = self._side(self.v1_root, "V1", decision_path=self.v1_root / "data" / "decision-feed.json")
        v2 = self._side(self.root, "V2", decision_path=self.root / "data" / "v2" / "decision-system.json")
        v1_feed = load_json(self.v1_root / "data" / "decision-feed.json")
        v2_feed = load_json(self.root / "data" / "decision-feed.json")
        v1_titles = self._titles(v1_feed)
        v2_titles = self._titles(v2_feed)
        divergences = []
        if v1["market_date"] != v2["market_date"]:
            divergences.append({"id": "market_date", "level": "must_explain", "conclusion": f"V1市场日为 {v1['market_date'] or '未知'}，V2为 {v2['market_date'] or '未知'}。", "action": "以交易所日历核验；日期未统一前不得比较命中率或切换主入口。"})
        if v1["automation_state"] != v2["automation_state"]:
            divergences.append({"id": "automation_state", "level": "must_explain", "conclusion": f"V1自动化状态 {v1['automation_state']}，V2为 {v2['automation_state']}。", "action": "展开两边任务诊断；不得把周末无产出误判成交易日故障。"})
        if v1["quality_issue_count"] != v2["quality_issue_count"]:
            divergences.append({"id": "quality_issues", "level": "observe", "conclusion": f"V1记录 {v1['quality_issue_count']} 个质量问题，V2记录 {v2['quality_issue_count']} 个。", "action": "只比较问题分类与证据，不以问题更少直接证明判断更优。"})
        only_v1 = sorted(v1_titles - v2_titles)
        only_v2 = sorted(v2_titles - v1_titles)
        if only_v1 or only_v2:
            divergences.append({"id": "signal_titles", "level": "observe", "conclusion": f"仅V1 {len(only_v1)} 条、仅V2 {len(only_v2)} 条。", "action": "逐条核对触发原因、来源和失效条件。", "only_v1": only_v1[:12], "only_v2": only_v2[:12]})
        consensus = sorted(v1_titles & v2_titles)
        cutover_ready = False
        return {
            "schema_version": 1,
            "generated_at": now_iso(),
            "mode": self.operation.get("mode"),
            "state": "comparable" if v1["entry_ok"] and v2["entry_ok"] else "degraded",
            "headline": "V1继续生产，V2继续影子；差异只用于解释和回溯。",
            "v1": v1,
            "v2": v2,
            "consensus": {"signal_title_count": len(consensus), "titles": consensus[:16], "note": "标题相同不代表证据链、行动条件或质量状态相同。"},
            "divergences": divergences,
            "cutover": {
                "ready": cutover_ready,
                "state": "hold_parallel",
                "reason": "用户已确认先并行；结果窗口、来源稳定性和差异解释尚未达到停用V1条件。",
                "requires_new_user_confirmation": True,
            },
            "guardrails": ["不以问题数量替代投资判断质量", "不自动停用V1", "不自动交易", "不同市场日的数据禁止直接比较命中率"],
        }

    def write(self) -> dict[str, Any]:
        payload = self.build()
        write_json(self.root / "data" / "v2" / "parallel-comparison.json", payload)
        return payload

    def _side(self, root: Path, label: str, *, decision_path: Path) -> dict[str, Any]:
        quality = load_json(root / "data" / "quality-report.json")
        automation = load_json(root / "data" / "automation-health.json")
        build = load_json(root / "data" / "build-report.json")
        runtime = load_json(root / "data" / "runtime-smoke-report.json")
        feed = load_json(root / "data" / "decision-feed.json")
        decision = load_json(decision_path)
        if label == "V2":
            radar = as_list(decision.get("opportunity_radar"))
            opportunities = sum(item.get("kind") == "opportunity" for item in radar if isinstance(item, dict))
            risks = sum(item.get("kind") == "risk" for item in radar if isinstance(item, dict))
        else:
            opportunities = len(as_list(feed.get("opportunities")))
            risks = len(as_list(feed.get("risks")))
        counts = as_dict(quality.get("counts"))
        return {
            "label": label,
            "role": self.operation.get("v1_role" if label == "V1" else "v2_role"),
            "git_head": git_head(root),
            "entry_ok": (root / ("index.html" if label == "V1" else "v2.html")).exists(),
            "market_date": quality.get("current_signal_date") or feed.get("current_signal_date"),
            "quality_state": quality.get("status") or "missing",
            "quality_issue_count": sum(int(counts.get(key) or 0) for key in ("critical", "warning")),
            "price_review_count": int(counts.get("price_review") or 0),
            "automation_state": automation.get("overall_status") or "missing",
            "build_state": build.get("status") or "missing",
            "runtime_state": runtime.get("status") or "missing",
            "opportunity_count": opportunities,
            "risk_count": risks,
            "evidence_as_of": quality.get("timestamp") or feed.get("timestamp"),
        }

    @staticmethod
    def _titles(feed: dict[str, Any]) -> set[str]:
        return {
            str(item.get("title")).strip()
            for section in ("opportunities", "risks", "verifications")
            for item in as_list(feed.get(section))
            if isinstance(item, dict) and item.get("title")
        }

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKILLS = Path.home() / ".codex/skills"


def run_json(script: Path, *args: str) -> dict[str, Any]:
    process = subprocess.run(
        [sys.executable, str(script), "--root", str(ROOT), *args],
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr or process.stdout or f"failed:{script}")
    value = json.loads(process.stdout)
    if not isinstance(value, dict):
        raise ValueError(f"invalid_object:{script}")
    return value


def check(checks: list[dict[str, Any]], label: str, passed: bool, detail: str) -> None:
    checks.append({"label": label, "passed": bool(passed), "detail": detail})


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def historical_case_without_trigger_result() -> str | None:
    outcomes = load_object(ROOT / "data/v2/v22/signal-outcomes.json")
    outcome_ids = {
        str(item.get("case_id"))
        for item in outcomes.get("cases") or []
        if isinstance(item, dict) and item.get("case_id")
    }
    replay = load_object(ROOT / "data/v2/v22/replay-index.json")
    for snapshot in replay.get("snapshots") or []:
        if not isinstance(snapshot, dict) or not snapshot.get("relative_path"):
            continue
        payload = load_object(ROOT / str(snapshot["relative_path"]))
        for case in payload.get("cases") or []:
            if isinstance(case, dict) and case.get("case_id") and str(case["case_id"]) not in outcome_ids:
                return str(case["case_id"])
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="核验四个V2平台只读Skill及真实场景输出。")
    parser.add_argument("--skills-root", type=Path, default=DEFAULT_SKILLS)
    parser.add_argument("--output", type=Path, default=ROOT / "data/v2/v22/platform-skill-validation.json")
    args = parser.parse_args()
    skills = args.skills_root.expanduser().resolve()
    names = [
        "intraday-decision-cockpit",
        "industry-logic-validator",
        "leader-stock-identifier",
        "trade-replay-review",
    ]
    checks: list[dict[str, Any]] = []
    for name in names:
        base = skills / name
        required = [base / "SKILL.md", base / "agents/openai.yaml", base / "references/output-contract.md"]
        check(checks, f"{name}结构", all(path.exists() for path in required), "说明、界面元数据和输出合同均存在。")
        body = (base / "SKILL.md").read_text(encoding="utf-8") if (base / "SKILL.md").exists() else ""
        check(checks, f"{name}只读边界", "Read only" in body or "Read-only" in body or "read-only" in body, "Skill明确禁止写入和越权动作。")

    cockpit = run_json(skills / "intraday-decision-cockpit/scripts/read_current_context.py")
    check(checks, "驾驶舱场景一：八维风险", len((cockpit.get("市场快照") or {}).get("维度") or []) == 8, "当前快照包含完整八维事实与缺失证据。")
    check(checks, "驾驶舱场景二：周末不补造", (cockpit.get("盘中任务状态") or {}).get("说明") is not None and (cockpit.get("市场快照") or {}).get("交易日") is not None, "输出最近交易日与盘中任务状态，不生成历史触发价。")

    hbm = run_json(skills / "industry-logic-validator/scripts/validate_theme.py", "--topic", "HBM")
    pharma = run_json(skills / "industry-logic-validator/scripts/validate_theme.py", "--topic", "创新药")
    check(checks, "产业验证场景一：HBM证据链", bool(hbm.get("研究资料")) and bool(hbm.get("上市公司映射")), "HBM研究、A股映射和交易证据分层返回。")
    pharma_text = json.dumps(pharma, ensure_ascii=False)
    contaminants = [value for value in ("Micron", "HBM", "半导体设备", "雅克科技", "美光") if value in pharma_text]
    check(checks, "产业验证场景二：医药无污染", not contaminants, f"无关证据命中：{contaminants or '无'}。")

    theme_roles = run_json(skills / "leader-stock-identifier/scripts/read_role_evidence.py", "--theme", "半导体设备")
    one_role = run_json(skills / "leader-stock-identifier/scripts/read_role_evidence.py", "--stock", "兆易创新")
    check(checks, "角色识别场景一：同主题比较", len(theme_roles.get("候选") or []) >= 2, "半导体设备返回多个可比较候选及角色证据。")
    unclassified = next(iter(one_role.get("候选") or []), {})
    check(checks, "角色识别场景二：证据不足不硬判", "未分类" in str(unclassified.get("证据判断")), "兆易创新证据不足时保持未分类。")

    replay = run_json(skills / "trade-replay-review/scripts/read_replay.py")
    historical_case_id = historical_case_without_trigger_result()
    replay_case = (
        run_json(skills / "trade-replay-review/scripts/read_replay.py", "--case-id", historical_case_id)
        if historical_case_id
        else {}
    )
    check(checks, "交易复盘场景一：样本不足不报命中率", replay.get("是否允许展示命中率") is False, "受治理门槛未满足，不发布命中率。")
    case_rows = replay_case.get("案例结果") or []
    check(
        checks,
        "交易复盘场景二：不补历史触发价",
        historical_case_id is not None and not case_rows,
        f"旧案例 {historical_case_id or '未找到'} 没有受治理触发结果，因此未生成评价记录。",
    )

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "mode": "read_only_validation",
        "skill_count": len(names),
        "scenario_count": 8,
        "passed_count": sum(item["passed"] for item in checks),
        "failed_count": sum(not item["passed"] for item in checks),
        "checks": checks,
        "guardrails": {
            "automatic_trading": False,
            "user_assets_modified": False,
            "model_promoted": False,
            "v1_modified": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("skill_count", "scenario_count", "passed_count", "failed_count")}, ensure_ascii=False))
    return 0 if report["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

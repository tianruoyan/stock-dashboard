#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
NODE_BIN = Path("/Users/sweet_orange/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")


STEPS = [
    ("opportunity-watch:pre", ["python3", "scripts/build_opportunity_watch.py"], False),
    ("theme-shifts:pre", ["python3", "scripts/build_theme_shifts.py"], False),
    ("decision-feed:pre", ["python3", "scripts/build_decision_feed.py"], False),
    ("automation-health:pre", ["python3", "scripts/build_automation_health.py"], False),
    ("audit", ["python3", "scripts/audit_dashboard_data.py"], True),
    ("alert-recovery-readiness", ["python3", "scripts/build_alert_recovery_readiness.py"], False),
    ("automation-health:post-audit", ["python3", "scripts/build_automation_health.py"], False),
    ("opportunity-watch:post-audit", ["python3", "scripts/build_opportunity_watch.py"], False),
    ("theme-shifts:post-audit", ["python3", "scripts/build_theme_shifts.py"], False),
    ("decision-feed:post-audit", ["python3", "scripts/build_decision_feed.py"], False),
    ("data-trust", ["python3", "scripts/build_data_trust.py"], False),
    ("monitoring-coverage", ["python3", "scripts/build_monitoring_coverage.py"], False),
    ("section-health", ["python3", "scripts/build_section_health.py"], False),
    ("v2-market-structure", ["python3", "scripts/build_v2_market_structure.py"], False),
    ("v2-research", ["python3", "scripts/build_v2_research.py"], False),
    ("v2-governance", ["python3", "scripts/build_v2_governance.py"], False),
    ("v2-learning", ["python3", "scripts/build_v2_learning.py"], False),
    ("v2-decision-system", ["python3", "scripts/build_v2_decision_system.py"], False),
    ("v2-static-smoke", ["python3", "scripts/smoke_v2_static.py"], False),
    ("v2-completion-audit", ["python3", "scripts/audit_v2_completion.py"], False),
    ("static-smoke", ["python3", "scripts/smoke_dashboard_static.py"], True),
    ("runtime-smoke", [str(NODE_BIN if NODE_BIN.exists() else "node"), "scripts/smoke_dashboard_runtime.js"], True),
]


def main() -> int:
    results = []
    critical_failure = False
    degraded = False
    for name, command, gates_publish in STEPS:
        result = run_step(name, command)
        results.append(result)
        write_report("running", "统一构建进行中。", results)
        if gates_publish and result["blocking"]:
            critical_failure = True
        if result["status"] not in {"ok", "waiting"}:
            degraded = True
    status = "blocked" if critical_failure else ("degraded" if degraded else "ok")
    summary = (
        "统一构建发现阻断项，禁止发布。"
        if critical_failure
        else ("统一构建完成，但存在降权/需复核项。" if degraded else "统一构建完成，未发现发布阻断项。")
    )
    write_report(status, summary, results)
    print(f"build-dashboard: {status} - {summary}")
    return 1 if critical_failure else 0


def write_report(status: str, summary: str, results: list[dict[str, object]]) -> None:
    report = {
        "status": status,
        "summary": summary,
        "steps": results,
        "rules": [
            "先把盘前/晚间/专题线索生成 opportunity-watch，再生成 theme-shifts 和 decision-feed。",
            "先生成 theme-shifts 和 decision-feed，再审计。",
            "审计会更新 quality-report，因此审计后必须重刷异动恢复就绪、automation-health、opportunity-watch、theme-shifts、decision-feed、data-trust、monitoring、section-health。",
            "audit/static-smoke/runtime-smoke 出现 critical 才阻断发布；degraded 只作为看板降权提示。",
        ],
    }
    (DATA_DIR / "build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_step(name: str, command: list[str]) -> dict[str, object]:
    try:
        proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        print(message, file=sys.stderr)
        return {
            "name": name,
            "command": " ".join(command),
            "returncode": 127,
            "status": "script_error",
            "blocking": True,
            "stdout_tail": "",
            "stderr_tail": tail(message),
        }
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    status = infer_status(name, proc.returncode)
    blocking = is_blocking(name, status, proc.returncode)
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    return {
        "name": name,
        "command": " ".join(command),
        "returncode": proc.returncode,
        "status": status,
        "blocking": blocking,
        "stdout_tail": tail(stdout),
        "stderr_tail": tail(stderr),
    }


def infer_status(name: str, returncode: int) -> str:
    if returncode != 0:
        return "script_error"
    if name.startswith("automation-health"):
        data = load_json(DATA_DIR / "automation-health.json")
        return data.get("overall_status") or ("error" if returncode else "ok")
    if name == "audit":
        data = load_json(DATA_DIR / "quality-report.json")
        return data.get("status") or ("critical" if returncode else "ok")
    if name == "static-smoke":
        data = load_json(DATA_DIR / "smoke-report.json")
        return data.get("status") or ("critical" if returncode else "ok")
    if name == "runtime-smoke":
        data = load_json(DATA_DIR / "runtime-smoke-report.json")
        return data.get("status") or ("critical" if returncode else "ok")
    return "error" if returncode else "ok"


def is_blocking(name: str, status: str, returncode: int) -> bool:
    if returncode != 0 or status == "script_error":
        return True
    if name == "audit":
        return status == "critical"
    if name in {"static-smoke", "runtime-smoke"}:
        return status == "critical" or returncode != 0
    return returncode != 0


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def tail(text: str, limit: int = 600) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[-limit:]


if __name__ == "__main__":
    raise SystemExit(main())

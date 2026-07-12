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
}
REQUIRED_DATA_KEYS = {
    "system",
    "data_quality_gate",
    "market_environment",
    "opportunity_radar",
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


def main() -> int:
    issues: list[dict[str, str]] = []
    html = (ROOT / "v2.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))
    for missing in sorted(REQUIRED_IDS - ids):
        issues.append({"severity": "critical", "code": "missing_v2_container", "message": missing})
    for anchor in re.findall(r'href="#([^"]+)"', html):
        if anchor not in ids:
            issues.append({"severity": "critical", "code": "broken_v2_anchor", "message": anchor})
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
    for missing in sorted(REQUIRED_DATA_KEYS - set(data)):
        issues.append({"severity": "critical", "code": "missing_v2_data_key", "message": missing})
    for card in data.get("opportunity_radar", []):
        for forbidden in ("evidence_score", "signal_score", "signal_grade"):
            if forbidden in card:
                issues.append({"severity": "critical", "code": "abstract_score_exposed", "message": forbidden})
        for required in ("title", "trigger", "action", "evidence", "counter_evidence", "confirm_conditions", "invalidation_conditions"):
            if required not in card:
                issues.append({"severity": "critical", "code": "radar_contract_missing", "message": required})
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

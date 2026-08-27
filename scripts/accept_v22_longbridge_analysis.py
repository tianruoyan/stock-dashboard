#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.longbridge_analysis import LongbridgeAnalysisPolicy, atomic_write_json, build_acceptance_report


def main() -> int:
    report = build_acceptance_report(ROOT)
    policy = LongbridgeAnalysisPolicy.load(ROOT / "config/v2-longbridge-analysis-policy.json")
    output = ROOT / str(policy.payload["acceptance_output"])
    atomic_write_json(output, report)
    print(json.dumps({"status": report["status"], **report["summary"], "output": str(output)}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

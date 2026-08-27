#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.v22_baseline import V22BaselineBuilder


def main() -> int:
    parser = argparse.ArgumentParser(description="只读核验并冻结V2.2 E0基线。")
    parser.add_argument("--check", action="store_true", help="只核验，不写入基线报告。")
    parser.add_argument("--output", type=Path, default=ROOT / "data/v2/v22/baseline-audit.json")
    args = parser.parse_args()

    builder = V22BaselineBuilder(ROOT)
    payload = builder.build() if args.check else builder.write(args.output)
    print(json.dumps({
        "stage": payload.get("stage"),
        "status": payload.get("status"),
        "baseline_id": payload.get("baseline_id"),
        "check_count": len(payload.get("checks") or []),
        "failed_checks": [item.get("id") for item in payload.get("checks") or [] if not item.get("passed")],
        "mode": "check" if args.check else "write",
    }, ensure_ascii=False))
    return 0 if payload.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.longbridge_analysis import LongbridgeAnalysisImporter


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Longbridge institutional analysis as V2.2 shadow references")
    parser.add_argument("--input", type=Path, help="Structured local JSON; defaults to local_inputs/longbridge-analysis.json")
    parser.add_argument("--check", action="store_true", help="Validate without writing public artifacts")
    args = parser.parse_args()
    input_path = args.input.resolve() if args.input else None
    report, artifact = LongbridgeAnalysisImporter(ROOT, input_path).run(write=not args.check)
    print(
        json.dumps(
            {
                "status": report["status"],
                "input_state": report["input_state"],
                "accepted": report["summary"]["accepted"],
                "review_required": report["summary"]["review_required"],
                "rejected": report["summary"]["rejected"],
                "public_reference_count": artifact.get("reference_count", 0),
                "mode": "shadow_reference_only",
                "trading_enabled": False,
                "watchlist_sync_changed": False,
            },
            ensure_ascii=False,
        )
    )
    return 1 if report["status"] == "invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())

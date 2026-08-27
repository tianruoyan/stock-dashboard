#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.v1_public_baseline import V1PublicBaselineImporter


def main() -> int:
    parser = argparse.ArgumentParser(description="只读导入V1公开日常结果，供V2同日对照")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = V1PublicBaselineImporter(ROOT).run(dry_run=args.dry_run)
    blocked = [item for item in report["files"] if item["state"] == "blocked_sensitive_fields"]
    print(json.dumps({
        "state": "blocked" if blocked else "completed",
        "imported_count": report["imported_count"],
        "blocked_count": len(blocked),
    }, ensure_ascii=False))
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())

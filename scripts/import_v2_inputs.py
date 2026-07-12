#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.input_imports import V2InputImporter


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and import V2 local data inputs")
    parser.add_argument("--input-dir", type=Path)
    args = parser.parse_args()
    report = V2InputImporter(ROOT, args.input_dir).run()
    print(json.dumps({"status": report["status"], "contracts": {item["id"]: item["status"] for item in report["contracts"]}}, ensure_ascii=False))
    return 1 if report["status"] == "invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())

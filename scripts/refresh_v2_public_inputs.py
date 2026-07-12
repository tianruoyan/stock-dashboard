#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.public_refresh import V2PublicInputRefresher


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh public V2 market and official event inputs")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    report = V2PublicInputRefresher(ROOT).run(args.date, force=args.force)
    print(json.dumps({"state": report["state"], "trade_date": report["trade_date"], "collectors": {item["id"]: item["state"] for item in report["collectors"]}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

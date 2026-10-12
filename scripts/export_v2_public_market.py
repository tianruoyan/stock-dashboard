#!/usr/bin/env python3
"""Audit/apply the narrow public facts projection; never commits or publishes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.public_market_export import export_public_market_facts


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview a public market-facts-only export; no Git or network operations")
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--target", type=Path, required=True, help="Separate local public-share directory")
    parser.add_argument("--apply", action="store_true", help="Explicitly replace only the approved local JSON output")
    args = parser.parse_args()
    report = export_public_market_facts(args.source, args.target, apply=args.apply)
    print(json.dumps(report, ensure_ascii=False))
    return 1 if report["state"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

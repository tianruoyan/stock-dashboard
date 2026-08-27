#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.market_fact_collector import V2MarketFactCollector


def main() -> int:
    parser = argparse.ArgumentParser(description="采集V2市场宽度、流动性、主线分布和外盘公开事实")
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--observed-at", type=datetime.fromisoformat)
    args = parser.parse_args()
    try:
        report = V2MarketFactCollector(ROOT).collect(args.date, observed_at=args.observed_at)
    except Exception as exc:
        print(json.dumps({"state": "failed", "error": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps({"state": report["state"], "trade_date": report["trade_date"], "outputs": report["outputs"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

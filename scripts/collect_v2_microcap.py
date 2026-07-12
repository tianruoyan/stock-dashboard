#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.learning import TradingCalendar, load_json
from v2_platform.microcap_collector import V2MicrocapCollector


def latest_open_day(today: date) -> date:
    calendar = TradingCalendar(load_json(ROOT / "config" / "v2-market-calendar.json"), "CN")
    cursor = today
    for _ in range(15):
        if calendar.is_open(cursor) is True:
            return cursor
        cursor -= timedelta(days=1)
    raise RuntimeError("no_verified_open_day")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect CSI 2000 public proxy quote")
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    trade_date = args.date or latest_open_day(date.today())
    payload = V2MicrocapCollector().collect(trade_date)
    path = ROOT / "local_inputs" / "microcap-observation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    item = payload["observations"][0]
    print(f"v2-microcap-collector: date={trade_date} close={item['close']} change={item['change_pct']:.2f}% source=sina_secondary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

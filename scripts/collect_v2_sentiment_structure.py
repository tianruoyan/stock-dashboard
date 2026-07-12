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
from v2_platform.sentiment_collector import V2SentimentCollector


def latest_open_day(today: date) -> date:
    calendar = TradingCalendar(load_json(ROOT / "config" / "v2-market-calendar.json"), "CN")
    cursor = today
    for _ in range(15):
        if calendar.is_open(cursor) is True:
            return cursor
        cursor -= timedelta(days=1)
    raise RuntimeError("no_verified_open_day")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect auditable A-share limit-up/down ladders")
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    trade_date = args.date or latest_open_day(date.today())
    payload = V2SentimentCollector(ROOT).collect(trade_date)
    path = ROOT / "local_inputs" / "sentiment-structure.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"v2-sentiment-collector: date={trade_date} up={payload['limit_up_ladder']['filtered_count']} down={payload['limit_down_ladder']['filtered_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

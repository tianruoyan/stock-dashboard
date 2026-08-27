#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.industry_tracking import V22IndustryTrackingBuilder


def main() -> int:
    payload = V22IndustryTrackingBuilder(ROOT).write()
    current_quotes = sum(
        item.get("quote_state") == "当前交易日已核验"
        for theme in payload["items"]
        for item in theme["representative_stocks"]
    )
    print(
        f"V2行业持续跟踪：行业{payload['tracking_count']}条；"
        f"当前交易日代表股行情{current_quotes}只；用户资产和V1未修改"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

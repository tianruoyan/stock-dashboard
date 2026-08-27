#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.stock_pool_v22 import V22StockPoolBuilder


def main() -> int:
    payload = V22StockPoolBuilder(ROOT).write()
    print(
        "V2.2股票池影子投影："
        f"正式观察{payload['formal_observation']['active_count']}只；"
        f"研究待补{payload['formal_observation']['near_ready_count']}只；"
        f"系统发现{payload['temporary_candidates']['count']}只；"
        "用户资产未修改"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

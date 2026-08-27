#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.market_environment import V22MarketEnvironmentBuilder


def main() -> int:
    payload = V22MarketEnvironmentBuilder(ROOT).write()
    summary = payload["dimension_summary"]
    print(
        "V2.2市场环境事实影子："
        f"支持{summary['support'] + summary['partial_support']}项；"
        f"抑制{summary['suppress'] + summary['risk_release']}项；"
        f"待补{summary['unknown']}项；"
        f"冲突{len(payload['conflicts'])}项；"
        "未改变现有行动结论"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

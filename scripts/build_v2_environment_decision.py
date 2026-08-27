#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.environment_decision import V22EnvironmentDecisionBuilder


def main() -> int:
    payload = V22EnvironmentDecisionBuilder(ROOT).write()
    summary = payload.get("summary") or {}
    print(
        "V2.2环境决策影子："
        f"状态{payload.get('primary_state')}；"
        f"风格走强{len(summary.get('strengthening_styles') or [])}类、走弱{len(summary.get('weakening_styles') or [])}类；"
        f"外盘确认{summary.get('confirmed_external_count') or 0}条；"
        f"G5抑制{summary.get('g5_suppress') or 0}条；"
        "未修改用户资产和生产入口"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

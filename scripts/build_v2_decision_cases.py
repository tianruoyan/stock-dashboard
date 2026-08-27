#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.decision_cases import V22DecisionCaseBuilder


def main() -> int:
    payload, candidate = V22DecisionCaseBuilder(ROOT).write()
    summary = candidate["summary"]
    print(
        "V2.2决策案例影子："
        f"去重后{payload['case_count']}个；"
        f"决策就绪{summary['decision_ready']}个；"
        f"等待确认{summary['awaiting_confirmation']}个；"
        f"未成卡线索{summary['unformed_clues']}个；"
        f"历史待补{summary['parked_clues']}个；"
        f"合并重复触发{summary['deduplicated_occurrences']}个；"
        "未修改V2基线与用户资产"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

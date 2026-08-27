#!/usr/bin/env python3
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.v22_outcome_collector import V22OutcomePriceCollector


if __name__ == "__main__":
    report = V22OutcomePriceCollector(ROOT).collect()
    print(f"V2.2结果回填影子：状态{report['state']}；结果窗口{report['completed_window_count']}个；失败{report['failure_count']}个。")

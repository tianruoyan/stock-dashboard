#!/usr/bin/env python3
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.v22_time_semantics import V22TimeSemanticsBuilder


if __name__ == "__main__":
    payload = V22TimeSemanticsBuilder(ROOT).write()
    comparison = payload["comparison"]
    print(f"V2.2时间口径：双轨日期{'一致' if comparison['allowed'] else '未统一'}；{comparison['reason']}")

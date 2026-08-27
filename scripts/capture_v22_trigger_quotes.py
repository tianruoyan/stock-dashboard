#!/usr/bin/env python3
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.v22_trigger_quotes import V22TriggerQuoteCapture


if __name__ == "__main__":
    _, report = V22TriggerQuoteCapture(ROOT).capture()
    print(f"V2.2触发行情影子：新增{report['created_snapshot_count']}个；累计{report['total_snapshot_count']}个；等待{report['hold_count']}个。")

#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.parallel_comparison import V2ParallelComparisonBuilder


if __name__ == "__main__":
    report = V2ParallelComparisonBuilder(ROOT).write()
    print(f"v2-parallel-comparison: state={report['state']} divergences={len(report['divergences'])} consensus={report['consensus']['signal_title_count']}")

#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.outcome_price_collector import V2OutcomePriceCollector


if __name__ == "__main__":
    report = V2OutcomePriceCollector(ROOT).collect()
    print(f"v2-outcome-price: state={report['state']} observations={report['observation_count']} windows={report['evaluated_window_input_count']} failures={report['failure_count']}")

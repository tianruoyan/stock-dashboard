#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.decision_system import V2DecisionSystemBuilder
from v2_platform.learning import V2LearningBuilder


def main() -> int:
    decision = V2DecisionSystemBuilder(ROOT).build()
    index, review, path = V2LearningBuilder(ROOT).build(decision)
    print(
        f"v2-learning: snapshots={index['snapshot_count']} pending={review['pending_signal_count']} "
        f"path={path.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

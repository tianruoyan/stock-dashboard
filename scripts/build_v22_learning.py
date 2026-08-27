#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.v22_learning import V22LearningBuilder

outputs = V22LearningBuilder(ROOT).write()
evaluation = outputs["model-evaluation.json"]
comparison = outputs["parallel-comparison.json"]
print(f"V2.2回溯影子：可评价{evaluation['record_count']}例；命中率不展示；生产切换{'允许' if comparison['cutover']['ready'] else '继续保持'}")

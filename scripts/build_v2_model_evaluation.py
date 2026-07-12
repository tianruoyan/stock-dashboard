#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.model_evaluation import V2ModelEvaluator


def main() -> int:
    payload = V2ModelEvaluator(ROOT).build()
    path = ROOT / "data" / "v2" / "model-evaluation.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"v2-model-evaluation: state={payload['state']} records={payload['record_count']} recommendation={payload['recommendation']['action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

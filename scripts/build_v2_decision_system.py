#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.decision_system import V2DecisionSystemBuilder


def main() -> int:
    output = ROOT / "data" / "v2" / "decision-system.json"
    payload = V2DecisionSystemBuilder(ROOT).build()
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(output)
    print(
        f"v2-decision-system: quality={payload['data_quality_gate']['state']} "
        f"radar={len(payload['opportunity_radar'])} validation={len(payload['validation_queue'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

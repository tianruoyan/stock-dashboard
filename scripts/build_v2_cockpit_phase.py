#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.cockpit_phase import CockpitPhaseViewBuilder


def main() -> int:
    output = ROOT / "data/v2/v22/cockpit-phase-view.json"
    payload = CockpitPhaseViewBuilder(ROOT).build()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(temporary.read_text(encoding="utf-8"))
    temporary.replace(output)
    print(f"v2-cockpit-phase: {payload['stage_label']} / {payload['status_label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

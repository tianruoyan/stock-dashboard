#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.governance import V2GovernanceBuilder


def main() -> int:
    payload = V2GovernanceBuilder(ROOT).build()
    path = ROOT / "data" / "v2" / "governance.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"v2-governance: events={payload['event_registry']['event_count']} tasks={payload['automation_routing']['task_count']}")
    return 0 if payload["automation_routing"]["state"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.acceptance import V2AcceptanceBuilder


def main() -> int:
    report = V2AcceptanceBuilder(ROOT).build()
    path = ROOT / "data" / "v2" / "acceptance-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"v2-acceptance: shadow={report['shadow_acceptance']} "
        f"promotion={report['production_promotion']} rollback={report['rollback_rehearsal']['status']}"
    )
    return 0 if report["shadow_acceptance"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

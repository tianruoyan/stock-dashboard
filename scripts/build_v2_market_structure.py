#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.market_structure import V2MarketStructureBuilder


def main() -> int:
    payload = V2MarketStructureBuilder(ROOT).build()
    path = ROOT / "data" / "v2" / "market-structure.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"v2-market-structure: state={payload['state']} direction={payload['direction']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

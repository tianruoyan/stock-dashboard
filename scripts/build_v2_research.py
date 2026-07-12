#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.research import V2ResearchSystemBuilder


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def main() -> int:
    research, stock_pool = V2ResearchSystemBuilder(ROOT).build()
    write_json(ROOT / "data" / "v2" / "research-library.json", research)
    write_json(ROOT / "data" / "v2" / "stock-pool.json", stock_pool)
    print(
        f"v2-research: domains={len(research['domains'])} stocks={stock_pool['stock_count']} "
        f"role_gaps={stock_pool['role_unclassified_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

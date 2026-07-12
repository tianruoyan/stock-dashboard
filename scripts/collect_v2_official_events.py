#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.official_event_collector import V2OfficialEventCollector


def main() -> int:
    payload = V2OfficialEventCollector(ROOT).collect()
    path = ROOT / "local_inputs" / "events.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            existing = {item.get("event_id"): item for item in current.get("events", []) if isinstance(item, dict) and item.get("event_id")}
        except Exception:
            existing = {}
    for item in payload["events"]:
        existing[item["event_id"]] = item
    payload["events"] = sorted(existing.values(), key=lambda item: str(item.get("published_at") or ""), reverse=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"v2-official-events: state={payload['collection_state']} events={len(payload['events'])} failures={len(payload['collection_failures'])}")
    return 0 if payload["events"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

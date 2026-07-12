#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.completion_audit import V2CompletionAuditBuilder


def main() -> int:
    payload = V2CompletionAuditBuilder(ROOT).build()
    path = ROOT / "data" / "v2" / "completion-audit.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"v2-completion-audit: state={payload['completion_state']} counts={payload['counts']}")
    return 1 if payload["completion_state"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

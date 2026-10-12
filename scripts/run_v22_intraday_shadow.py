#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.intraday_shadow import V22IntradayShadowRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="运行V2.2盘中影子检查点")
    parser.add_argument("--at", type=datetime.fromisoformat)
    parser.add_argument("--force-checkpoint", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # The runner owns the verified exchange calendar, timezone and all configured
    # windows. A second host-local gate silently skipped legitimate checkpoints.
    try:
        report = V22IntradayShadowRunner(ROOT).run(at=args.at, force_checkpoint=args.force_checkpoint, dry_run=args.dry_run)
    except Exception as exc:
        print(json.dumps({"state": "failed", "message": "盘中影子任务未完成", "detail": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False))
        return 1
    if report.get("state") != "skipped":
        print(json.dumps({
            "state": report.get("state"),
            "trade_date": report.get("trade_date"),
            "checkpoint": (report.get("checkpoint") or {}).get("label"),
            "reason": report.get("reason"),
            "summary": report.get("summary"),
        }, ensure_ascii=False))
    return 1 if report.get("state") in {"failed", "waiting_update"} else 0


if __name__ == "__main__":
    raise SystemExit(main())


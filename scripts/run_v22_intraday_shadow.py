#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time
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
    wall_clock = datetime.now().astimezone()
    if (
        args.at is None
        and not args.force_checkpoint
        and (wall_clock.weekday() >= 5 or not (time(9, 20) <= wall_clock.time() <= time(15, 10)))
    ):
        return 0
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
    return 1 if report.get("state") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

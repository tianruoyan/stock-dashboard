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

from v2_platform.evening_sentiment import EveningSentimentRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="生成V2晚间舆情并在断网恢复后自动补跑")
    parser.add_argument("--at", type=datetime.fromisoformat)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    wall_clock = datetime.now().astimezone()
    in_evening_window = time(19, 30) <= wall_clock.time() <= time(22, 30)
    in_morning_retry_window = time(7, 30) <= wall_clock.time() <= time(8, 30)
    if args.at is None and not args.force and (wall_clock.weekday() >= 5 or not (in_evening_window or in_morning_retry_window)):
        return 0
    try:
        report = EveningSentimentRunner(ROOT, now=args.at).run(force=args.force, dry_run=args.dry_run)
    except Exception as exc:
        print(json.dumps({
            "state": "failed",
            "summary": "晚间舆情任务未完成，旧结果保持不变。",
            "error": f"{type(exc).__name__}:{exc}",
        }, ensure_ascii=False))
        return 1
    if report.get("state") != "current":
        print(json.dumps(report, ensure_ascii=False))
    return 1 if report.get("state") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

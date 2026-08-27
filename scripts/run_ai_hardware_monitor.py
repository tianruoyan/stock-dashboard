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

from ai_hardware_monitor.engine.intraday_trigger import IntradayTriggerRunner
from ai_hardware_monitor.engine.io import load_json
from ai_hardware_monitor.engine.runner import MonitorRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="运行AI硬件二次启动雷达V1")
    parser.add_argument("--live", action="store_true", help="采集公开实时事实（默认）")
    parser.add_argument("--input", type=Path, help="读取标准化输入快照")
    parser.add_argument("--at", type=datetime.fromisoformat, help="指定带时区运行时间")
    parser.add_argument("--force-checkpoint", action="store_true", help="测试/验收时强制选择最近检查点")
    parser.add_argument("--refresh-checkpoint", action="store_true", help="显式重跑当日同一检查点")
    parser.add_argument("--watch", action="store_true", help="在固定检查点之外运行盘中即时触发巡检")
    parser.add_argument("--force-trigger", action="store_true", help="测试/验收时强制运行一次盘中触发巡检")
    args = parser.parse_args()
    wall_clock = datetime.now().astimezone()
    if (
        args.at is None
        and not args.force_checkpoint
        and not args.force_trigger
        and (wall_clock.weekday() >= 5 or not (time(9, 20) <= wall_clock.time() <= time(15, 10)))
    ):
        return 0
    try:
        report = MonitorRunner(ROOT).run(
            now=args.at,
            input_path=args.input.resolve() if args.input else None,
            force_checkpoint=args.force_checkpoint,
            refresh_checkpoint=args.refresh_checkpoint,
        )
        if args.watch:
            trigger_snapshot = None
            trigger_evaluation = None
            if report.get("state") == "completed":
                trigger_snapshot = load_json(ROOT / "ai_hardware_monitor" / "data" / "input-snapshot.json")
                trigger_evaluation = load_json(ROOT / "ai_hardware_monitor" / "data" / "status.json")
            trigger_report = IntradayTriggerRunner(ROOT).run(
                now=args.at,
                snapshot=trigger_snapshot,
                evaluation=trigger_evaluation,
                force=args.force_trigger,
            )
            report = {"state": "watch_cycle", "checkpoint": report, "intraday_trigger": trigger_report}
    except Exception as exc:
        print(json.dumps({"state": "failed", "message": "AI硬件雷达运行失败", "detail": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False))
        return 1
    failed = report.get("state") == "failed"
    if report.get("state") == "watch_cycle":
        failed = any(
            isinstance(report.get(part), dict) and report[part].get("state") == "failed"
            for part in ("checkpoint", "intraday_trigger")
        )
        routine_states = {"waiting", "already_completed", "throttled", "not_sent"}
        routine = all(
            isinstance(report.get(part), dict) and report[part].get("state") in routine_states
            for part in ("checkpoint", "intraday_trigger")
        )
    else:
        routine = report.get("state") in {"waiting", "already_completed", "throttled", "not_sent"}
    if failed or not routine:
        print(json.dumps(report, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

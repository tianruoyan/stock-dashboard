#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.publishing import PublishPolicy, V2Publisher


def main() -> int:
    parser = argparse.ArgumentParser(description="V2 allowlisted publisher; defaults to shadow mode")
    parser.add_argument("--mode", choices=("shadow", "commit", "publish"), default="shadow")
    parser.add_argument("--policy", type=Path, default=ROOT / "config" / "v2-publish-policy.json")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--message", default="Publish generated dashboard data")
    parser.add_argument("--report", type=Path, default=ROOT / "logs" / "v2-publisher-status.json")
    args = parser.parse_args()

    policy = PublishPolicy.load(args.policy)
    publisher = V2Publisher(ROOT, policy)
    build = None if args.skip_build else ["python3", "scripts/build_dashboard_reports.py"]
    result = publisher.run(mode=args.mode, build_command=build, commit_message=args.message)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.report.with_suffix(args.report.suffix + ".tmp")
    tmp.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(args.report)
    print(json.dumps({"state": result.state, "detail": result.detail}, ensure_ascii=False))
    return 0 if result.state not in {"build_failed", "blocked_pre_staged"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

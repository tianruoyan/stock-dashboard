#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.watchlist_migration import WatchlistMigrationAuditBuilder


def main() -> int:
    parser = argparse.ArgumentParser(description="生成V2.2用户资产迁移预览；E2不应用变更")
    parser.add_argument("--check", action="store_true", help="只读检查，不写报告")
    parser.add_argument("--apply", action="store_true", help="保留参数；E2阶段始终拒绝执行")
    args = parser.parse_args()
    if args.apply:
        print("E2阶段不允许应用用户资产迁移；请保留影子核对。", file=sys.stderr)
        return 3
    builder = WatchlistMigrationAuditBuilder(ROOT)
    if args.check:
        public, _private = builder.build()
    else:
        public = builder.write()
    print(json.dumps({
        "状态": public["user_view"]["状态"],
        "现有个人观察": public["counts"]["watch_only"],
        "当前影子读取": public["user_view"]["当前读取数量"],
        "疑似缺失": public["user_view"]["疑似缺失数量"],
        "应用状态": public["user_view"]["应用状态"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.user_asset_store import UserAssetStore


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化或检查V2本机私有用户资产结构")
    parser.add_argument("--check", action="store_true", help="只检查，不创建或修改")
    args = parser.parse_args()
    store = UserAssetStore(ROOT)
    if args.check:
        summary = store.integrity_summary()
        ready = summary.get("status") == "ready"
        print(
            "用户资产结构检查："
            + ("正常" if ready else "未就绪")
            + f"；结构版本={','.join(summary.get('schema_versions') or []) or '无'}"
        )
        return 0 if ready else 1
    summary = store.initialize()
    print(
        "用户资产空结构已就绪；"
        f"结构版本={','.join(summary.get('schema_versions') or [])}；"
        f"用户资产数量={summary.get('user_asset_count') or 0}；"
        "未导入真实自选"
    )
    return 0 if summary.get("status") == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.import_ths_watchlist import (
    DEFAULT_SOURCE,
)
from v2_platform.user_asset_store import UserAssetStore
from v2_platform.watchlist_migration import WatchlistMigrationAuditBuilder
from v2_platform.watchlist_sync import (
    ShadowSource,
    build_shadow_result,
    latest_source_identity_hash,
    record_shadow_result,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_watch_only() -> list[dict]:
    payload = json.loads((ROOT / "config/watchlist.json").read_text(encoding="utf-8"))
    return list((payload.get("watch_only") or {}).get("stocks") or [])


def isolated_ths_read(timeout_seconds: int = 15) -> tuple[list[dict], str]:
    code = """
import hashlib, json
from scripts.import_ths_watchlist import fetch_ths_watchlist, load_ths_cookies
cookies = load_ths_cookies()
rows = fetch_ths_watchlist()
identity = hashlib.sha256(str(cookies.get('userid') or '').encode('utf-8')).hexdigest()
print(json.dumps({'rows': rows, 'identity': 'sha256:' + identity}, ensure_ascii=False))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise RuntimeError("ths_isolated_read_failed")
    payload = json.loads(completed.stdout)
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    return rows, str(payload.get("identity") or "")


def isolated_file_read(file_path: Path, timeout_seconds: int = 10) -> tuple[list[dict], str, float]:
    code = """
import json, sys
from datetime import datetime, timezone
from pathlib import Path
from scripts.import_ths_watchlist import parse_source
path = Path(sys.argv[1]).expanduser()
stat = path.stat()
rows = parse_source(path.read_text(encoding='utf-8-sig'))
source_as_of = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).astimezone().isoformat(timespec='seconds')
age_seconds = max(0.0, datetime.now(timezone.utc).timestamp() - stat.st_mtime)
print(json.dumps({'rows': rows, 'source_as_of': source_as_of, 'age_seconds': age_seconds}, ensure_ascii=False))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(file_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise RuntimeError("file_isolated_read_failed")
    payload = json.loads(completed.stdout)
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    return rows, str(payload.get("source_as_of") or ""), float(payload.get("age_seconds") or 0)


def read_source(mode: str, file_path: Path) -> ShadowSource:
    observed_at = now_iso()
    if mode in {"auto", "ths"}:
        try:
            rows, identity = isolated_ths_read()
            return ShadowSource(
                watchlist_source="ths_cloud",
                source_mode="full",
                records=tuple(rows),
                source_as_of=observed_at,
                observed_at=observed_at,
                source_identity_hash=identity,
                completeness_claimed=False,
            )
        except Exception:
            if mode == "ths":
                return ShadowSource(
                    watchlist_source="ths_cloud",
                    source_mode="full",
                    records=tuple(),
                    source_as_of=None,
                    observed_at=observed_at,
                    fetch_error="同花顺数据未成功读取",
                )
    try:
        rows, source_as_of, age_seconds = isolated_file_read(file_path)
        return ShadowSource(
            watchlist_source="ths_cloud",
            source_mode="file_fallback",
            records=tuple(rows),
            source_as_of=source_as_of,
            observed_at=observed_at,
            completeness_claimed=False,
            stale=age_seconds > 6 * 3600,
        )
    except (OSError, UnicodeError):
        return ShadowSource(
            watchlist_source="ths_cloud",
            source_mode="file_fallback",
            records=tuple(),
            source_as_of=None,
            observed_at=observed_at,
            fetch_error="同花顺和备用文件均未成功读取",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="V2.2同花顺影子同步；不会应用用户资产变更")
    parser.add_argument("--mode", choices=["auto", "ths", "file"], default="auto")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--record-shadow", action="store_true", help="只记录私有影子批次和脱敏摘要")
    args = parser.parse_args()
    store = UserAssetStore(ROOT)
    store.initialize()
    source = read_source(args.mode, Path(args.source).expanduser())
    result = build_shadow_result(
        load_watch_only(),
        source,
        previous_source_identity_hash=latest_source_identity_hash(store),
    )
    recorded = {"created": False}
    if args.record_shadow:
        recorded = record_shadow_result(store, result)
        WatchlistMigrationAuditBuilder(ROOT, store).write()
    output = result.public_summary()
    output["记录状态"] = "已写入私有影子批次" if recorded.get("created") else ("重复批次未新增" if args.record_shadow else "只读演练，未写入")
    print(json.dumps(output, ensure_ascii=False))
    return 2 if result.batch_state == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

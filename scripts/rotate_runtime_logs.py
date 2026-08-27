#!/usr/bin/env python3
"""Bound local runtime logs without deleting the active log file."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / ".log-maintenance.lock"
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_BACKUPS = 3


def configured_logs() -> list[Path]:
    home = Path.home()
    paths = list((home / "stock-dashboard" / "logs").glob("*.log"))
    paths.extend((home / "stock-dashboard-v2-local" / "logs").glob("*.log"))
    paths.extend(
        [
            home / "Documents" / "投资" / "monitor.log",
            home / "Documents" / "投资" / "dashboard-server.log",
        ]
    )
    return sorted({path.resolve() for path in paths if path.exists() and path.is_file()})


def rotate_copytruncate(path: Path, *, max_bytes: int, backups: int, dry_run: bool = False) -> dict:
    size = path.stat().st_size
    result = {"path": str(path), "size_before": size, "rotated": False}
    if size <= max_bytes:
        return result
    result["rotated"] = True
    if dry_run:
        return result

    for index in range(backups, 1, -1):
        source = path.with_name(f"{path.name}.{index - 1}")
        target = path.with_name(f"{path.name}.{index}")
        if not source.exists():
            continue
        target.unlink(missing_ok=True)
        source.replace(target)

    first_backup = path.with_name(f"{path.name}.1")
    temporary = path.with_name(f".{path.name}.rotate-{os.getpid()}")
    shutil.copy2(path, temporary)
    temporary.replace(first_backup)
    with path.open("r+b") as handle:
        handle.truncate(0)
    return result


def maintain(paths: Iterable[Path], *, max_bytes: int, backups: int, dry_run: bool = False) -> dict:
    rotated = []
    errors = []
    for path in paths:
        try:
            item = rotate_copytruncate(path, max_bytes=max_bytes, backups=backups, dry_run=dry_run)
            if item["rotated"]:
                rotated.append(item)
        except OSError as exc:
            errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
    return {
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "max_bytes": max_bytes,
        "backups": backups,
        "dry_run": dry_run,
        "rotated": rotated,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="轮转投资决策系统本地运行日志")
    parser.add_argument("--max-mb", type=int, default=DEFAULT_MAX_BYTES // (1024 * 1024))
    parser.add_argument("--backups", type=int, default=DEFAULT_BACKUPS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    max_bytes = max(1, args.max_mb) * 1024 * 1024
    backups = max(1, min(args.backups, 10))

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        report = maintain(configured_logs(), max_bytes=max_bytes, backups=backups, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

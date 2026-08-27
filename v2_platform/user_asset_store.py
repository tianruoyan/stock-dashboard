from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


DEFAULT_DATABASE = ".v2_private/user-assets.sqlite3"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "sql"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class UserAssetStoreError(RuntimeError):
    pass


class UserAssetStore:
    """Private SQLite store for user-confirmed assets.

    This class owns schema installation, read-only connections, integrity
    summaries and backups. It never imports existing watchlists by itself.
    """

    def __init__(self, root: Path, database_path: Path | None = None) -> None:
        self.root = root.resolve()
        self.path = (database_path or (self.root / DEFAULT_DATABASE)).resolve()

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def _open(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            if not self.exists:
                raise UserAssetStoreError("用户资产存储尚未初始化")
            connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5)
            connection.execute("PRAGMA query_only = ON")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass
            connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def connection(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._open(readonly=readonly)
        try:
            yield connection
            if not readonly:
                connection.commit()
        except Exception:
            if not readonly:
                connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> dict[str, Any]:
        with self.connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                str(row["version"])
                for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = migration.stem
                if version in applied:
                    continue
                sql = migration.read_text(encoding="utf-8")
                applied_at = now_iso()
                quoted_version = version.replace("'", "''")
                quoted_time = applied_at.replace("'", "''")
                connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + sql
                    + "\nINSERT INTO schema_migrations(version, applied_at) VALUES "
                    + f"('{quoted_version}', '{quoted_time}');\n"
                    + "COMMIT;"
                )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return self.integrity_summary()

    def schema_versions(self) -> list[str]:
        if not self.exists:
            return []
        with self.connection(readonly=True) as connection:
            rows = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        return [str(row["version"]) for row in rows]

    def table_count(self, table: str) -> int:
        allowed = {
            "security_master",
            "user_watchlist_asset",
            "watchlist_source_link",
            "watchlist_sync_batch",
            "watchlist_sync_event",
            "user_asset_change_log",
        }
        if table not in allowed:
            raise UserAssetStoreError("不允许读取未登记的数据表")
        with self.connection(readonly=True) as connection:
            row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"] if row else 0)

    def integrity_summary(self) -> dict[str, Any]:
        if not self.exists:
            return {
                "status": "not_initialized",
                "integrity": "unknown",
                "schema_versions": [],
                "logical_hash": None,
            }
        with self.connection(readonly=True) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            tables = [
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
            logical_rows: dict[str, list[dict[str, Any]]] = {}
            for table in tables:
                rows = connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
                logical_rows[table] = [dict(row) for row in rows]
        versions = [str(row["version"]) for row in logical_rows.get("schema_migrations", [])]
        digest = hashlib.sha256(canonical_json(logical_rows)).hexdigest()
        return {
            "status": "ready" if integrity == "ok" else "damaged",
            "integrity": integrity,
            "schema_versions": versions,
            "security_count": len(logical_rows.get("security_master", [])),
            "user_asset_count": len(logical_rows.get("user_watchlist_asset", [])),
            "logical_hash": f"sha256:{digest}",
        }

    def backup_to(self, destination: Path) -> dict[str, Any]:
        if not self.exists:
            raise UserAssetStoreError("用户资产存储尚未初始化")
        destination = destination.resolve()
        if destination.exists():
            raise UserAssetStoreError("备份目标已存在，未覆盖")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(readonly=True) as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
        try:
            os.chmod(destination, 0o600)
        except OSError:
            pass
        restored = UserAssetStore(self.root, destination).integrity_summary()
        current = self.integrity_summary()
        if restored["logical_hash"] != current["logical_hash"]:
            raise UserAssetStoreError("备份校验失败")
        return restored

    @classmethod
    def restore_backup(cls, root: Path, backup: Path, destination: Path) -> "UserAssetStore":
        backup_store = cls(root, backup)
        if backup_store.integrity_summary().get("status") != "ready":
            raise UserAssetStoreError("备份文件未通过完整性检查")
        destination = destination.resolve()
        if destination.exists():
            raise UserAssetStoreError("恢复目标已存在，未覆盖")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(f"file:{backup.resolve()}?mode=ro", uri=True)
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
        restored = cls(root, destination)
        if restored.integrity_summary()["logical_hash"] != backup_store.integrity_summary()["logical_hash"]:
            raise UserAssetStoreError("恢复校验失败")
        return restored

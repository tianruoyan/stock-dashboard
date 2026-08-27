from __future__ import annotations

import fcntl
import fnmatch
import hashlib
import json
import os
import subprocess
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from uuid import uuid4


POLICY_SCHEMA_VERSION = 1
PUBLISH_SCHEMA_VERSION = 1


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


@dataclass(frozen=True)
class PublishPolicy:
    name: str
    version: str
    include_globs: tuple[str, ...]
    exclude_globs: tuple[str, ...]
    target_remote: str
    target_branch: str
    max_push_attempts: int
    deny_globs: tuple[str, ...] = ()
    sensitive_json_keys: tuple[str, ...] = ()
    schema_version: int = POLICY_SCHEMA_VERSION

    @classmethod
    def load(cls, path: Path) -> "PublishPolicy":
        value = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            name=str(value["name"]),
            version=str(value["version"]),
            include_globs=tuple(str(item) for item in value.get("include_globs", [])),
            exclude_globs=tuple(str(item) for item in value.get("exclude_globs", [])),
            target_remote=str(value.get("target_remote", "origin")),
            target_branch=str(value.get("target_branch", "main")),
            max_push_attempts=max(1, int(value.get("max_push_attempts", 3))),
            deny_globs=tuple(str(item) for item in value.get("deny_globs", [])),
            sensitive_json_keys=tuple(str(item) for item in value.get("sensitive_json_keys", [])),
            schema_version=int(value.get("schema_version", POLICY_SCHEMA_VERSION)),
        )

    @staticmethod
    def normalize_path(path: str) -> str:
        normalized = path.replace(os.sep, "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized

    def allows(self, path: str) -> bool:
        normalized = self.normalize_path(path)
        included = any(fnmatch.fnmatchcase(normalized, pattern) for pattern in self.include_globs)
        excluded = any(fnmatch.fnmatchcase(normalized, pattern) for pattern in self.exclude_globs)
        denied = any(fnmatch.fnmatchcase(normalized, pattern) for pattern in self.deny_globs)
        return included and not excluded and not denied

    def hard_blocks_path(self, path: str) -> bool:
        normalized = self.normalize_path(path)
        return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in self.deny_globs)


@dataclass(frozen=True)
class ScopeAudit:
    changed_paths: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    blocked_paths: tuple[str, ...]
    pre_staged_paths: tuple[str, ...]
    hard_blocked_paths: tuple[str, ...] = ()

    @property
    def safe_to_stage(self) -> bool:
        return not self.pre_staged_paths and not self.hard_blocked_paths

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"safe_to_stage": self.safe_to_stage}


@dataclass(frozen=True)
class PublishArtifact:
    artifact_id: str
    generation_key: str
    policy_name: str
    policy_version: str
    source_head: str
    changed_files: tuple[dict[str, Any], ...]
    created_at: str
    schema_version: int = PUBLISH_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PublishResult:
    publish_run_id: str
    mode: str
    state: str
    detail: str
    scope: ScopeAudit
    artifact: PublishArtifact | None
    build: dict[str, Any] | None
    commit_sha: str | None
    push_attempts: int
    started_at: str
    finished_at: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope"] = self.scope.to_dict()
        value["artifact"] = self.artifact.to_dict() if self.artifact else None
        return value


class PublishLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    def append(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class V2Publisher:
    def __init__(
        self,
        repo: Path,
        policy: PublishPolicy,
        *,
        ledger_path: Path | None = None,
        lock_path: Path | None = None,
    ) -> None:
        self.repo = repo.resolve()
        self.policy = policy
        self.ledger = PublishLedger(ledger_path or self.repo / "logs" / "v2-publisher-ledger.jsonl")
        self.lock_path = lock_path or self.repo / ".v2-publish.lock"

    def run(
        self,
        *,
        mode: str = "shadow",
        build_command: Sequence[str] | None = None,
        commit_message: str = "Publish generated dashboard data",
    ) -> PublishResult:
        if mode not in {"shadow", "commit", "publish"}:
            raise ValueError(f"unsupported publish mode: {mode}")
        publish_run_id = f"publish_{uuid4().hex}"
        started = utc_now()
        with self._exclusive_lock():
            self.ledger.append(
                {
                    "schema_version": PUBLISH_SCHEMA_VERSION,
                    "event_type": "publish_started",
                    "publish_run_id": publish_run_id,
                    "mode": mode,
                    "occurred_at": started.isoformat(),
                }
            )
            build = self._run_build(build_command) if build_command else None
            if build and build["returncode"] != 0:
                return self._finish(
                    publish_run_id,
                    mode,
                    "build_failed",
                    "build command failed; nothing was staged",
                    self.audit_scope(),
                    None,
                    build,
                    None,
                    0,
                    started,
                )

            scope = self.audit_scope()
            artifact = self.freeze_artifact(scope.allowed_paths) if scope.allowed_paths else None
            if scope.hard_blocked_paths:
                return self._finish(
                    publish_run_id,
                    mode,
                    "blocked_sensitive_scope",
                    "private, raw-sync, account identifier, or user note data detected; nothing was staged",
                    scope,
                    artifact,
                    build,
                    None,
                    0,
                    started,
                )
            if scope.pre_staged_paths:
                return self._finish(
                    publish_run_id,
                    mode,
                    "blocked_pre_staged",
                    "git index already contains changes; automated publisher will not mix ownership",
                    scope,
                    artifact,
                    build,
                    None,
                    0,
                    started,
                )
            if not scope.allowed_paths:
                state = "scope_warning" if scope.blocked_paths else "no_change"
                detail = (
                    "only non-publishable changes exist; no files were staged"
                    if scope.blocked_paths
                    else "no generated data changes"
                )
                return self._finish(
                    publish_run_id, mode, state, detail, scope, None, build, None, 0, started
                )
            if mode == "shadow":
                return self._finish(
                    publish_run_id,
                    mode,
                    "shadow_ready",
                    "publishable data identified; shadow mode made no git changes",
                    scope,
                    artifact,
                    build,
                    None,
                    0,
                    started,
                )

            self._stage_allowed(scope.allowed_paths)
            staged = tuple(self._git_paths("diff", "--cached", "--name-only", "-z"))
            if tuple(sorted(staged)) != tuple(sorted(scope.allowed_paths)):
                raise RuntimeError("staged file set differs from audited publish allowlist")
            commit = self._git("commit", "-m", commit_message).stdout.strip()
            commit_sha = self._git("rev-parse", "HEAD").stdout.strip()
            self.ledger.append(
                {
                    "schema_version": PUBLISH_SCHEMA_VERSION,
                    "event_type": "artifact_committed",
                    "publish_run_id": publish_run_id,
                    "artifact_id": artifact.artifact_id if artifact else None,
                    "commit_sha": commit_sha,
                    "occurred_at": utc_now().isoformat(),
                    "git_output": commit[-500:],
                }
            )
            if mode == "commit":
                return self._finish(
                    publish_run_id,
                    mode,
                    "committed",
                    "allowlisted generated data committed; blocked paths remain untouched",
                    scope,
                    artifact,
                    build,
                    commit_sha,
                    0,
                    started,
                )

            attempts = self._push_frozen_commit(publish_run_id, artifact, commit_sha)
            return self._finish(
                publish_run_id,
                mode,
                "published",
                f"frozen commit published to {self.policy.target_remote}/{self.policy.target_branch}",
                scope,
                artifact,
                build,
                commit_sha,
                attempts,
                started,
            )

    def audit_scope(self) -> ScopeAudit:
        unstaged = set(self._git_paths("diff", "--name-only", "-z"))
        staged = set(self._git_paths("diff", "--cached", "--name-only", "-z"))
        untracked = set(self._git_paths("ls-files", "--others", "--exclude-standard", "-z"))
        changed = tuple(sorted(unstaged | staged | untracked))
        hard_blocked = tuple(
            path
            for path in changed
            if self.policy.hard_blocks_path(path)
            or (self.policy.allows(path) and self._contains_sensitive_json_key(path))
        )
        allowed = tuple(path for path in changed if path not in hard_blocked and self.policy.allows(path))
        blocked = tuple(path for path in changed if path not in allowed)
        return ScopeAudit(
            changed,
            allowed,
            blocked,
            tuple(sorted(staged)),
            tuple(sorted(hard_blocked)),
        )

    def _contains_sensitive_json_key(self, relative: str) -> bool:
        if not self.policy.sensitive_json_keys or not relative.lower().endswith(".json"):
            return False
        path = self.repo / relative
        if not path.is_file():
            return False
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        sensitive = set(self.policy.sensitive_json_keys)
        stack = [value]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                if any(str(key) in sensitive for key in current):
                    return True
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)
        return False

    def freeze_artifact(self, paths: Iterable[str]) -> PublishArtifact:
        files: list[dict[str, Any]] = []
        for relative in sorted(set(paths)):
            path = self.repo / relative
            if path.is_file():
                digest = sha256_bytes(path.read_bytes())
                state = "present"
            else:
                digest = sha256_bytes(b"<deleted>")
                state = "deleted"
            files.append({"path": relative, "state": state, "content_hash": digest})
        generation_key = sha256_bytes(
            canonical_json(
                {
                    "policy": self.policy.name,
                    "policy_version": self.policy.version,
                    "files": files,
                }
            )
        )
        artifact_id = f"publish_artifact_{generation_key.split(':', 1)[1]}"
        return PublishArtifact(
            artifact_id=artifact_id,
            generation_key=generation_key,
            policy_name=self.policy.name,
            policy_version=self.policy.version,
            source_head=self._git("rev-parse", "HEAD").stdout.strip(),
            changed_files=tuple(files),
            created_at=utc_now().isoformat(),
        )

    def _stage_allowed(self, paths: Sequence[str]) -> None:
        if not paths:
            return
        self._git("add", "--", *paths)

    def _push_frozen_commit(
        self,
        publish_run_id: str,
        artifact: PublishArtifact | None,
        commit_sha: str,
    ) -> int:
        target = f"{commit_sha}:refs/heads/{self.policy.target_branch}"
        for attempt in range(1, self.policy.max_push_attempts + 1):
            proc = subprocess.run(
                ["git", "push", self.policy.target_remote, target],
                cwd=self.repo,
                text=True,
                capture_output=True,
            )
            self.ledger.append(
                {
                    "schema_version": PUBLISH_SCHEMA_VERSION,
                    "event_type": "push_attempt",
                    "publish_run_id": publish_run_id,
                    "artifact_id": artifact.artifact_id if artifact else None,
                    "commit_sha": commit_sha,
                    "attempt": attempt,
                    "returncode": proc.returncode,
                    "stderr_tail": proc.stderr.strip()[-500:],
                    "occurred_at": utc_now().isoformat(),
                }
            )
            if proc.returncode == 0:
                return attempt
            if attempt < self.policy.max_push_attempts:
                time.sleep(attempt * 2)
        raise RuntimeError(
            f"push failed after {self.policy.max_push_attempts} attempts; frozen commit {commit_sha} retained"
        )

    def _run_build(self, command: Sequence[str]) -> dict[str, Any]:
        started = utc_now()
        proc = subprocess.run(command, cwd=self.repo, text=True, capture_output=True)
        return {
            "command": list(command),
            "started_at": started.isoformat(),
            "finished_at": utc_now().isoformat(),
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout.strip()[-1000:],
            "stderr_tail": proc.stderr.strip()[-1000:],
        }

    def _finish(
        self,
        publish_run_id: str,
        mode: str,
        state: str,
        detail: str,
        scope: ScopeAudit,
        artifact: PublishArtifact | None,
        build: dict[str, Any] | None,
        commit_sha: str | None,
        attempts: int,
        started: datetime,
    ) -> PublishResult:
        result = PublishResult(
            publish_run_id=publish_run_id,
            mode=mode,
            state=state,
            detail=detail,
            scope=scope,
            artifact=artifact,
            build=build,
            commit_sha=commit_sha,
            push_attempts=attempts,
            started_at=started.isoformat(),
            finished_at=utc_now().isoformat(),
        )
        self.ledger.append(
            {
                "schema_version": PUBLISH_SCHEMA_VERSION,
                "event_type": "publish_finished",
                "publish_run_id": publish_run_id,
                "state": state,
                "artifact_id": artifact.artifact_id if artifact else None,
                "commit_sha": commit_sha,
                "occurred_at": result.finished_at,
            }
        )
        return result

    @contextmanager
    def _exclusive_lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("another V2 publisher is active") from exc
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(["git", *args], cwd=self.repo, text=True, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc

    def _git_paths(self, *args: str) -> list[str]:
        output = self._git(*args).stdout
        return [item for item in output.split("\0") if item]

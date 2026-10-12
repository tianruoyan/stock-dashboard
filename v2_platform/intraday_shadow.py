from __future__ import annotations

import fcntl
import json
import hashlib
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, time, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator
from zoneinfo import ZoneInfo

from v2_platform.learning import TradingCalendar, as_list, load_json, write_json


STATUS_OUTPUT = "data/v2/v22/intraday-shadow-status.json"
RUNTIME_STATE = ".v2_runtime/v22-intraday-shadow-state.json"
LOCK_FILE = ".v2_runtime/v22-intraday-shadow.lock"
MARKET_OUTPUTS = {
    "local_inputs/market-breadth.json": ("as_of",),
    "local_inputs/market-liquidity.json": ("as_of",),
    "data/v2/decision-system.json": ("system", "decision_as_of"),
    "data/v2/v22/market-environment.json": ("as_of",),
    "data/v2/v22/decision-cases.json": ("as_of",),
}
FACT_HEALTH = "data/v2/public-market-fact-health.json"
STATUS_ARTIFACTS = ("data/v2/v22/time-semantics.json", "data/v2/v22/cockpit-phase-view.json")
TRIGGER_REPORT = "data/v2/v22/trigger-quote-capture-report.json"


def now_local(timezone_name: str = "Asia/Shanghai") -> datetime:
    return datetime.now(timezone.utc).astimezone(ZoneInfo(timezone_name))


def parse_hhmm(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


class V22IntradayShadowRunner:
    """Run the governed V2.2 intraday chain at explicit checkpoints only."""

    def __init__(
        self,
        root: Path,
        *,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.root = root.resolve()
        self.config = load_json(self.root / "config/v2-intraday-shadow.json")
        self.calendar = TradingCalendar(load_json(self.root / "config/v2-market-calendar.json"), str(self.config.get("market") or "CN"))
        self.timezone = ZoneInfo(str(self.config.get("timezone") or "Asia/Shanghai"))
        self.command_runner = command_runner

    def run(
        self,
        *,
        at: datetime | None = None,
        force_checkpoint: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        observed = at or now_local(str(self.config.get("timezone") or "Asia/Shanghai"))
        if observed.tzinfo is None:
            raise ValueError("runner_time_timezone_required")
        observed = observed.astimezone(self.timezone)
        open_state = self.calendar.is_open(observed.date())
        if open_state is not True:
            return self._skip("non_trading_day" if open_state is False else "calendar_unverified", observed)
        runtime = load_json(self.root / RUNTIME_STATE)
        checkpoint = self._checkpoint(observed)
        if not checkpoint:
            checkpoint = self._recovery_checkpoint(observed, runtime)
        if not checkpoint:
            return self._skip("outside_checkpoint", observed)
        completed = runtime.get("completed") if isinstance(runtime.get("completed"), dict) else {}
        key = f"{observed.date().isoformat()}:{checkpoint['id']}"
        if completed.get(key) == "completed" and not force_checkpoint:
            return self._skip("checkpoint_already_completed", observed, checkpoint)
        commands = self._commands(checkpoint, observed)
        if dry_run:
            return {
                "schema_version": 1,
                "mode": "shadow_only",
                "state": "dry_run",
                "trade_date": observed.date().isoformat(),
                "checkpoint": checkpoint,
                "observed_at": observed.isoformat(timespec="seconds"),
                "commands": [" ".join(command) for _, command in commands],
                "guardrails": self.config.get("guardrails"),
            }
        with self._lock():
            # Another invocation may have completed while this one selected a slot.
            runtime = load_json(self.root / RUNTIME_STATE)
            completed = runtime.get("completed") if isinstance(runtime.get("completed"), dict) else {}
            if completed.get(key) == "completed" and not force_checkpoint:
                return self._skip("checkpoint_already_completed", observed, checkpoint)
            paths = (*MARKET_OUTPUTS, FACT_HEALTH, *STATUS_ARTIFACTS, TRIGGER_REPORT)
            before = {path: self._artifact_signature(path) for path in paths}
            results = []
            failed = False
            for name, command in commands:
                try:
                    result = self.command_runner(command, cwd=self.root, capture_output=True, text=True)
                except (OSError, subprocess.SubprocessError) as exc:
                    result = subprocess.CompletedProcess(command, 1, "", type(exc).__name__)
                producer = self._producer_status(result.stdout)
                producer_state = producer.get("state")
                row = {
                    "name": name,
                    "returncode": result.returncode,
                    "state": "process_completed" if result.returncode == 0 else "failed",
                    "producer_state": producer_state,
                    "stdout_tail": (result.stdout or "")[-500:].strip(),
                    "stderr_tail": (result.stderr or "")[-500:].strip(),
                }
                results.append(row)
                if result.returncode != 0 or producer_state in {"failed", "blocked", "error"}:
                    row["state"] = "failed"
                    failed = True
                    break
            finished_at = now_local(str(self.timezone)) if at is None else observed
            freshness = self._freshness(checkpoint, finished_at, before)
            waiting = not failed and (not freshness["verified"] or any(
                row.get("producer_state") in {"waiting_update", "retained", "stale"} for row in results
            ))
            trigger_updated = before[TRIGGER_REPORT] != self._artifact_signature(TRIGGER_REPORT)
            trigger_report = load_json(self.root / TRIGGER_REPORT) if trigger_updated else {}
            time_semantics = load_json(self.root / STATUS_ARTIFACTS[0])
            state = "failed" if failed else "waiting_update" if waiting else "completed"
            recovery = checkpoint.get("recovery") is True
            report = {
                "schema_version": 1,
                "version": self.config.get("version"),
                "mode": "shadow_only",
                "state": state,
                "trade_date": observed.date().isoformat(),
                "checkpoint": {"id": checkpoint.get("id"), "label": checkpoint.get("label")},
                "observed_at": observed.isoformat(timespec="seconds"),
                "finished_at": finished_at.isoformat(timespec="seconds"),
                "steps": results,
                "freshness": freshness,
                "reason": "source_outputs_not_fresh" if waiting else None,
                "trigger_capture": {
                    "created_snapshot_count": int(trigger_report.get("created_snapshot_count") or 0),
                    "total_snapshot_count": int(trigger_report.get("total_snapshot_count") or 0),
                    "hold_count": int(trigger_report.get("hold_count") or 0),
                    "summary": trigger_report.get("summary") or "本检查点没有生成触发行情快照。",
                },
                "same_day_comparison": {
                    "allowed": state == "completed" and freshness["state"] == "fresh" and bool((time_semantics.get("comparison") or {}).get("allowed")),
                    "reason": (time_semantics.get("comparison") or {}).get("reason") or "尚未形成同日双轨证据。",
                },
                "summary": (
                    "行情或产物尚未更新，保留原始证据时间，等待重试。"
                    if waiting
                    else "断线恢复补采完成。"
                    if recovery and not failed
                    else "断线恢复补采失败，保留上一次成功结果。"
                    if recovery
                    else "盘中影子检查完成。"
                    if not failed
                    else "盘中影子检查失败，保留上一次成功结果。"
                ),
                "guardrails": self.config.get("guardrails"),
            }
            write_json(self.root / STATUS_OUTPUT, report)
            history = self.root / "data/v2/v22/intraday-shadow-runs" / observed.date().isoformat() / f"{checkpoint['id']}.json"
            if not history.exists() or state == "completed":
                write_json(history, report)
            if state == "completed":
                completed[key] = "completed"
                write_json(self.root / RUNTIME_STATE, {
                    "schema_version": 1,
                    "updated_at": observed.isoformat(timespec="seconds"),
                    "completed": completed,
                    "last_market_completed_at": (
                        observed.isoformat(timespec="seconds") if freshness["state"] == "fresh"
                        else runtime.get("last_market_completed_at")
                    ),
                })
            return report

    @staticmethod
    def _producer_status(stdout: str | None) -> dict[str, Any]:
        for line in reversed((stdout or "").splitlines()):
            try:
                value = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                return value
        return {}

    def _artifact_signature(self, relative: str) -> tuple[Any, ...] | None:
        path = self.root / relative
        try:
            stat = path.stat()
            # Atomic replacement is evidence of an actual producer write even if
            # a verified unchanged quote has identical bytes. It is never a market time.
            return (stat.st_ino, stat.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        except OSError:
            return None

    def _freshness(self, checkpoint: dict[str, Any], observed: datetime, before: dict[str, Any]) -> dict[str, Any]:
        status_only = checkpoint.get("pipeline") == "status_only"
        required = STATUS_ARTIFACTS if status_only else (*MARKET_OUTPUTS, FACT_HEALTH)
        issues = []
        sources = []
        for relative in required:
            signature = self._artifact_signature(relative)
            payload = load_json(self.root / relative)
            if signature is None or not payload:
                issues.append({"path": relative, "reason": "missing_or_invalid_output"})
                continue
            if signature == before.get(relative):
                issues.append({"path": relative, "reason": "output_not_produced_this_run"})
            if relative not in MARKET_OUTPUTS:
                continue
            raw: Any = payload
            for key in MARKET_OUTPUTS[relative]:
                raw = raw.get(key) if isinstance(raw, dict) else None
            try:
                source_at = datetime.fromisoformat(str(raw))
                if source_at.tzinfo is None:
                    raise ValueError("source_timezone_required")
                source_at = source_at.astimezone(self.timezone)
            except (TypeError, ValueError):
                issues.append({"path": relative, "reason": "source_as_of_missing_or_naive"})
                continue
            age = (observed - source_at).total_seconds()
            # After the cash session ends, its closing quote remains valid for
            # close_freeze. A newly built report cannot refresh an older quote.
            reference = observed
            if observed.timetz().replace(tzinfo=None) >= time(15, 0):
                reference = observed.replace(hour=15, minute=0, second=0, microsecond=0)
            max_age = max(60, int((self.config.get("recovery") or {}).get("stale_after_seconds") or 600))
            reason = None
            if source_at.date() != observed.date() or (payload.get("trade_date") and payload["trade_date"] != observed.date().isoformat()):
                reason = "source_trade_date_mismatch"
            elif age < 0:
                reason = "source_in_future"
            elif checkpoint.get("pipeline") == "close" and source_at < reference:
                reason = "close_source_before_1500_cutoff"
            elif (reference - source_at).total_seconds() > max_age:
                reason = "source_stale"
            if reason:
                issues.append({"path": relative, "reason": reason})
            sources.append({"path": relative, "source_as_of": raw, "age_seconds": age})
        if not status_only:
            health = load_json(self.root / FACT_HEALTH)
            if health.get("state") not in {"usable", "degraded"} or (health.get("guardrails") or {}).get("retained_previous_same_day_facts"):
                issues.append({"path": FACT_HEALTH, "reason": "source_not_refreshed"})
            if health.get("trade_date") != observed.date().isoformat():
                issues.append({"path": FACT_HEALTH, "reason": "source_trade_date_mismatch"})
        return {
            "state": "status_only" if status_only and not issues else "fresh" if not issues else "waiting_update",
            "verified": not issues,
            "market_data_refreshed": not status_only and not issues,
            "sources": sources,
            "issues": issues,
            "generated_at_used_as_source_time": False,
        }

    def _checkpoint(self, observed: datetime) -> dict[str, Any] | None:
        current = observed.timetz().replace(tzinfo=None, second=0, microsecond=0)
        for item in as_list(self.config.get("checkpoints")):
            if not isinstance(item, dict):
                continue
            if parse_hhmm(str(item.get("start"))) <= current <= parse_hhmm(str(item.get("end"))):
                return item
        for item in as_list(self.config.get("rapid_candidate_windows")):
            if not isinstance(item, dict):
                continue
            start = parse_hhmm(str(item.get("start")))
            end = parse_hhmm(str(item.get("end")))
            if not start <= current <= end:
                continue
            interval = int(item.get("interval_seconds") or self.config.get("interval_seconds") or 60)
            if interval <= 0:
                continue
            window_start = observed.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
            elapsed = max(0, int((observed - window_start).total_seconds()))
            bucket = window_start + timedelta(seconds=(elapsed // interval) * interval)
            bucket_id = bucket.strftime("%H%M%S")
            return {
                "id": f"{item.get('id') or 'rapid_candidate'}_{bucket_id}",
                "label": f"{item.get('label') or '快速候选'} {bucket.strftime('%H:%M')}",
                "start": item.get("start"),
                "end": item.get("end"),
                "pipeline": item.get("pipeline") or "market",
                "capture": item.get("capture") is not False,
                "rapid_candidate": True,
                "purpose": item.get("purpose"),
            }
        return None

    def _recovery_checkpoint(self, observed: datetime, runtime: dict[str, Any]) -> dict[str, Any] | None:
        recovery = self.config.get("recovery")
        if not isinstance(recovery, dict) or recovery.get("enabled") is not True:
            return None
        current = observed.timetz().replace(tzinfo=None, second=0, microsecond=0)
        active = False
        active_start = None
        for item in as_list(recovery.get("active_windows")):
            if not isinstance(item, dict):
                continue
            start = parse_hhmm(str(item.get("start")))
            end = parse_hhmm(str(item.get("end")))
            if start <= current <= end:
                active = True
                active_start = start
                break
        if not active or active_start is None:
            return None
        last_success = None
        try:
            last_success = datetime.fromisoformat(str(runtime.get("last_market_completed_at", runtime.get("updated_at")) or ""))
            if last_success.tzinfo is None:
                last_success = last_success.replace(tzinfo=self.timezone)
            last_success = last_success.astimezone(self.timezone)
        except (TypeError, ValueError):
            last_success = None
        stale_after = max(60, int(recovery.get("stale_after_seconds") or 600))
        if (
            last_success is not None
            and last_success.date() == observed.date()
            and (observed - last_success).total_seconds() < stale_after
        ):
            return None
        interval = max(60, int(recovery.get("interval_seconds") or 300))
        window_start = observed.replace(
            hour=active_start.hour,
            minute=active_start.minute,
            second=0,
            microsecond=0,
        )
        elapsed = max(0, int((observed - window_start).total_seconds()))
        bucket = window_start + timedelta(seconds=(elapsed // interval) * interval)
        return {
            "id": f"recovery_{bucket.strftime('%H%M%S')}",
            "label": f"断线恢复补采 {observed.strftime('%H:%M')}",
            "start": bucket.strftime("%H:%M"),
            "end": observed.strftime("%H:%M"),
            "pipeline": "market",
            "capture": True,
            "recovery": True,
            "purpose": recovery.get("purpose"),
        }

    def _commands(self, checkpoint: dict[str, Any], observed: datetime) -> list[tuple[str, list[str]]]:
        python = sys.executable or "python3"
        if checkpoint.get("pipeline") == "status_only":
            return [
                ("time-semantics", [python, "scripts/build_v22_time_semantics.py"]),
                ("cockpit-phase", [python, "scripts/build_v2_cockpit_phase.py"]),
            ]
        trade_date = observed.date().isoformat()
        observed_at = observed.isoformat(timespec="seconds")
        commands = [
            ("intraday-indices", [python, "scripts/update_intraday_market.py"]),
            ("public-inputs", [python, "scripts/refresh_v2_public_inputs.py", "--date", trade_date, "--force"]),
            ("market-facts", [python, "scripts/collect_v2_market_facts.py", "--date", trade_date, "--observed-at", observed_at]),
            ("input-import", [python, "scripts/import_v2_inputs.py"]),
            ("market-structure", [python, "scripts/build_v2_market_structure.py"]),
            ("representative-quotes", [python, "scripts/collect_v2_representative_quotes.py"]),
            ("v2-baseline", [python, "scripts/build_v2_decision_system.py"]),
            ("stock-pool", [python, "scripts/build_v2_stock_pool.py"]),
            ("market-environment", [python, "scripts/build_v2_market_environment.py"]),
            ("environment-decision", [python, "scripts/build_v2_environment_decision.py"]),
            ("decision-cases", [python, "scripts/build_v2_decision_cases.py"]),
            ("cockpit-phase", [python, "scripts/build_v2_cockpit_phase.py"]),
            ("time-semantics", [python, "scripts/build_v22_time_semantics.py"]),
        ]
        if checkpoint.get("capture") is True:
            commands.append(("trigger-quotes", [python, "scripts/capture_v22_trigger_quotes.py"]))
        if checkpoint.get("pipeline") == "close":
            commands.extend([
                ("outcome-prices", [python, "scripts/collect_v22_outcome_prices.py"]),
                ("replay-learning", [python, "scripts/build_v22_learning.py"]),
            ])
        return commands

    @contextmanager
    def _lock(self) -> Iterator[None]:
        path = self.root / LOCK_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("intraday_shadow_already_running") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _skip(self, reason: str, observed: datetime, checkpoint: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "mode": "shadow_only",
            "state": "skipped",
            "reason": reason,
            "trade_date": observed.date().isoformat(),
            "checkpoint": {"id": checkpoint.get("id"), "label": checkpoint.get("label")} if checkpoint else None,
            "observed_at": observed.isoformat(timespec="seconds"),
            "guardrails": self.config.get("guardrails"),
        }


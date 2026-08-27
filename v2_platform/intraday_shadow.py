from __future__ import annotations

import fcntl
import json
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
            results = []
            failed = False
            for name, command in commands:
                result = self.command_runner(command, cwd=self.root, capture_output=True, text=True)
                row = {
                    "name": name,
                    "returncode": result.returncode,
                    "state": "completed" if result.returncode == 0 else "failed",
                    "stdout_tail": (result.stdout or "")[-500:].strip(),
                    "stderr_tail": (result.stderr or "")[-500:].strip(),
                }
                results.append(row)
                if result.returncode != 0:
                    failed = True
                    break
            trigger_report = load_json(self.root / "data/v2/v22/trigger-quote-capture-report.json")
            time_semantics = load_json(self.root / "data/v2/v22/time-semantics.json")
            state = "failed" if failed else "completed"
            recovery = checkpoint.get("recovery") is True
            report = {
                "schema_version": 1,
                "version": self.config.get("version"),
                "mode": "shadow_only",
                "state": state,
                "trade_date": observed.date().isoformat(),
                "checkpoint": {"id": checkpoint.get("id"), "label": checkpoint.get("label")},
                "observed_at": observed.isoformat(timespec="seconds"),
                "steps": results,
                "trigger_capture": {
                    "created_snapshot_count": int(trigger_report.get("created_snapshot_count") or 0),
                    "total_snapshot_count": int(trigger_report.get("total_snapshot_count") or 0),
                    "hold_count": int(trigger_report.get("hold_count") or 0),
                    "summary": trigger_report.get("summary") or "本检查点没有生成触发行情快照。",
                },
                "same_day_comparison": {
                    "allowed": bool((time_semantics.get("comparison") or {}).get("allowed")),
                    "reason": (time_semantics.get("comparison") or {}).get("reason") or "尚未形成同日双轨证据。",
                },
                "summary": (
                    "断线恢复补采完成。"
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
            if not history.exists() or not failed:
                write_json(history, report)
            if not failed:
                completed[key] = "completed"
                write_json(self.root / RUNTIME_STATE, {
                    "schema_version": 1,
                    "updated_at": observed.isoformat(timespec="seconds"),
                    "completed": completed,
                })
            return report

    def _checkpoint(self, observed: datetime) -> dict[str, Any] | None:
        current = observed.timetz().replace(tzinfo=None)
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
        current = observed.timetz().replace(tzinfo=None)
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
            last_success = datetime.fromisoformat(str(runtime.get("updated_at") or ""))
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

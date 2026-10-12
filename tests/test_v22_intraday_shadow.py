from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch
import importlib.util

from v2_platform.intraday_shadow import V22IntradayShadowRunner, MARKET_OUTPUTS, FACT_HEALTH, STATUS_ARTIFACTS
from v2_platform.learning import write_json


ROOT = Path(__file__).resolve().parents[1]
CHINA = ZoneInfo("Asia/Shanghai")


class V22IntradayShadowTests(unittest.TestCase):
    def prepare(self, root: Path) -> None:
        (root / "config").mkdir(parents=True)
        for filename in ("v2-market-calendar.json", "v2-intraday-shadow.json"):
            (root / "config" / filename).write_text((ROOT / "config" / filename).read_text(encoding="utf-8"), encoding="utf-8")

    def produce(self, root: Path, at: datetime) -> None:
        for relative, keys in MARKET_OUTPUTS.items():
            payload = {"trade_date": at.date().isoformat(), "as_of": at.isoformat()}
            if len(keys) > 1:
                payload = {"system": {"decision_as_of": at.isoformat()}}
            write_json(root / relative, payload)
        write_json(root / FACT_HEALTH, {"state": "usable", "trade_date": at.date().isoformat()})
        for relative in STATUS_ARTIFACTS:
            write_json(root / relative, {"generated_at": at.isoformat()})

    def test_non_trading_day_skips_without_running_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            calls = []
            def runner(*args, **kwargs):
                calls.append(args)
                return subprocess.CompletedProcess(args[0], 0, "", "")
            report = V22IntradayShadowRunner(root, command_runner=runner).run(at=datetime(2026, 7, 19, 10, 0, tzinfo=CHINA))
            self.assertEqual(report["state"], "skipped")
            self.assertEqual(report["reason"], "non_trading_day")
            self.assertEqual(calls, [])
            self.assertFalse((root / "data/v2/v22/intraday-shadow-status.json").exists())

    def test_due_checkpoint_runs_once_and_preserves_guardrails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                if "scripts/build_v22_time_semantics.py" in command:
                    self.produce(root, at)
                return subprocess.CompletedProcess(command, 0, "ok", "")
            at = datetime(2026, 7, 20, 10, 1, tzinfo=CHINA)
            first = V22IntradayShadowRunner(root, command_runner=runner).run(at=at)
            second = V22IntradayShadowRunner(root, command_runner=runner).run(at=at)
            self.assertEqual(first["state"], "completed")
            self.assertGreater(len(calls), 10)
            self.assertEqual(second["reason"], "checkpoint_already_completed")
            self.assertFalse(first["guardrails"]["automatic_trading"])
            self.assertFalse(first["guardrails"]["automatic_user_asset_mutation"])

    def test_dry_run_lists_same_day_pipeline_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            report = V22IntradayShadowRunner(root).run(at=datetime(2026, 7, 20, 14, 47, tzinfo=CHINA), dry_run=True)
            self.assertEqual(report["state"], "dry_run")
            joined = "\n".join(report["commands"])
            self.assertIn("collect_v2_market_facts.py --date 2026-07-20", joined)
            self.assertIn("capture_v22_trigger_quotes.py", joined)
            self.assertFalse((root / ".v2_runtime").exists())

    def test_rapid_candidate_window_runs_between_fixed_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            calls = []

            def runner(command, **kwargs):
                calls.append(command)
                if "scripts/build_v22_time_semantics.py" in command:
                    self.produce(root, at)
                return subprocess.CompletedProcess(command, 0, "ok", "")

            at = datetime(2026, 7, 20, 10, 24, tzinfo=CHINA)
            first = V22IntradayShadowRunner(root, command_runner=runner).run(at=at)
            second = V22IntradayShadowRunner(root, command_runner=runner).run(at=at)
            self.assertEqual(first["state"], "completed")
            self.assertEqual(first["checkpoint"]["id"], "morning_rapid_candidate_102400")
            self.assertIn("快速候选", first["checkpoint"]["label"])
            self.assertEqual(second["reason"], "checkpoint_already_completed")
            joined = "\n".join(" ".join(command) for command in calls)
            self.assertIn("capture_v22_trigger_quotes.py", joined)

    def test_failed_step_stops_pipeline_and_does_not_mark_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            def runner(command, **kwargs):
                code = 1 if any(value.endswith("collect_v2_market_facts.py") for value in command) else 0
                return subprocess.CompletedProcess(command, code, "", "source failed" if code else "")
            report = V22IntradayShadowRunner(root, command_runner=runner).run(at=datetime(2026, 7, 20, 9, 37, tzinfo=CHINA))
            self.assertEqual(report["state"], "failed")
            state = json.loads((root / "data/v2/v22/intraday-shadow-status.json").read_text())
            self.assertEqual(state["summary"], "盘中影子检查失败，保留上一次成功结果。")
            self.assertFalse((root / ".v2_runtime/v22-intraday-shadow-state.json").exists())

    def test_stale_runtime_recovers_between_regular_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            (root / ".v2_runtime").mkdir(parents=True)
            (root / ".v2_runtime/v22-intraday-shadow-state.json").write_text(json.dumps({
                "schema_version": 1,
                "updated_at": "2026-07-20T14:10:00+08:00",
                "completed": {},
            }), encoding="utf-8")
            calls = []

            def runner(command, **kwargs):
                calls.append(command)
                if "scripts/build_v22_time_semantics.py" in command:
                    self.produce(root, at)
                return subprocess.CompletedProcess(command, 0, "ok", "")

            at = datetime(2026, 7, 20, 14, 35, tzinfo=CHINA)
            report = V22IntradayShadowRunner(root, command_runner=runner).run(at=at)
            self.assertEqual(report["state"], "completed")
            self.assertTrue(report["checkpoint"]["id"].startswith("recovery_"))
            self.assertEqual(report["summary"], "断线恢复补采完成。")
            self.assertGreater(len(calls), 10)

    def test_recent_success_does_not_create_unneeded_recovery_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            (root / ".v2_runtime").mkdir(parents=True)
            (root / ".v2_runtime/v22-intraday-shadow-state.json").write_text(json.dumps({
                "schema_version": 1,
                "updated_at": "2026-07-20T14:29:00+08:00",
                "completed": {},
            }), encoding="utf-8")
            calls = []

            def runner(command, **kwargs):
                calls.append(command)
                if "scripts/build_v22_time_semantics.py" in command:
                    self.produce(root, at)
                return subprocess.CompletedProcess(command, 0, "ok", "")

            at = datetime(2026, 7, 20, 14, 35, tzinfo=CHINA)
            report = V22IntradayShadowRunner(root, command_runner=runner).run(at=at)
            self.assertEqual(report["state"], "skipped")
            self.assertEqual(report["reason"], "outside_checkpoint")
            self.assertEqual(calls, [])

    def test_configured_boundary_minutes_and_timezone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            for hh, mm, ss, expected in [(9, 15, 0, "pre_open_status"), (15, 11, 0, "close_freeze"), (15, 20, 0, "close_freeze"), (15, 20, 59, "close_freeze")]:
                at = datetime(2026, 7, 20, hh, mm, ss, tzinfo=CHINA)
                with self.subTest(at=at):
                    report = V22IntradayShadowRunner(root).run(at=at.astimezone(timezone.utc), dry_run=True)
                    self.assertEqual(report["checkpoint"]["id"], expected)
            self.assertEqual(V22IntradayShadowRunner(root).run(at=datetime(2026, 7, 20, 15, 21, tzinfo=CHINA))["reason"], "outside_checkpoint")

    def test_holiday_and_calendar_gap_stay_closed_even_when_forced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            for at, reason in [(datetime(2026, 10, 1, 15, 11, tzinfo=CHINA), "non_trading_day"), (datetime(2027, 1, 4, 10, 0, tzinfo=CHINA), "calendar_unverified")]:
                report = V22IntradayShadowRunner(root).run(at=at, force_checkpoint=True, dry_run=True)
                self.assertEqual(report["reason"], reason)

    def test_cli_does_not_apply_host_wall_clock_gate(self) -> None:
        spec = importlib.util.spec_from_file_location("intraday_cli", ROOT / "scripts/run_v22_intraday_shadow.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module, "V22IntradayShadowRunner") as factory, patch("sys.argv", ["runner"]):
            factory.return_value.run.return_value = {"state": "skipped"}
            self.assertEqual(module.main(), 0)
            factory.return_value.run.assert_called_once_with(at=None, force_checkpoint=False, dry_run=False)

    def test_zero_exit_with_missing_or_unchanged_old_outputs_is_retryable(self) -> None:
        for preexisting in [False, True]:
            with self.subTest(preexisting=preexisting), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.prepare(root)
                at = datetime(2026, 7, 20, 10, 1, tzinfo=CHINA)
                if preexisting:
                    self.produce(root, at - timedelta(days=1))
                runner = lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "ok", "")
                first = V22IntradayShadowRunner(root, command_runner=runner).run(at=at)
                second = V22IntradayShadowRunner(root, command_runner=runner).run(at=at)
                self.assertEqual(first["state"], "waiting_update")
                self.assertEqual(second["state"], "waiting_update")
                self.assertFalse(first["freshness"]["market_data_refreshed"])
                self.assertFalse((root / ".v2_runtime/v22-intraday-shadow-state.json").exists())

    def test_rebuilt_reports_cannot_refresh_old_source_timestamps(self) -> None:
        for offset in [-86400, -1800, 1, 60, 600]:
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.prepare(root)
                at = datetime(2026, 7, 20, 10, 1, tzinfo=CHINA)
                def runner(command, **kwargs):
                    self.produce(root, at + timedelta(seconds=offset))
                    return subprocess.CompletedProcess(command, 0, "ok", "")
                report = V22IntradayShadowRunner(root, command_runner=runner).run(at=at)
                self.assertEqual(report["state"], "waiting_update")
                self.assertFalse(report["same_day_comparison"]["allowed"])

    def test_retained_same_day_collector_zero_exit_is_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            at = datetime(2026, 7, 20, 10, 1, tzinfo=CHINA)
            def runner(command, **kwargs):
                self.produce(root, at)
                write_json(root / FACT_HEALTH, {"state": "waiting_update", "trade_date": at.date().isoformat(), "generated_at": at.isoformat(), "guardrails": {"retained_previous_same_day_facts": True}})
                return subprocess.CompletedProcess(command, 0, '{"state":"waiting_update"}', "")
            report = V22IntradayShadowRunner(root, command_runner=runner).run(at=at)
            self.assertEqual(report["state"], "waiting_update")
            self.assertFalse((root / ".v2_runtime/v22-intraday-shadow-state.json").exists())

    def test_usable_close_quote_at_1500_completes_at_1520(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            at = datetime(2026, 7, 20, 15, 20, tzinfo=CHINA)
            def runner(command, **kwargs):
                self.produce(root, at.replace(minute=0))
                return subprocess.CompletedProcess(command, 0, "ok", "")
            report = V22IntradayShadowRunner(root, command_runner=runner).run(at=at)
            self.assertEqual(report["state"], "completed")
            self.assertEqual(report["freshness"]["state"], "fresh")
            self.assertEqual(report["freshness"]["sources"][0]["source_as_of"], "2026-07-20T15:00:00+08:00")

    def test_close_freeze_rejects_pre_close_quotes_even_when_newly_written(self) -> None:
        for hh, mm, ss in [(14, 50, 0), (14, 59, 59)]:
            with self.subTest(source=(hh, mm, ss)), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.prepare(root)
                at = datetime(2026, 7, 20, 15, 20, tzinfo=CHINA)
                def runner(command, **kwargs):
                    self.produce(root, at.replace(hour=hh, minute=mm, second=ss))
                    return subprocess.CompletedProcess(command, 0, "ok", "")
                report = V22IntradayShadowRunner(root, command_runner=runner).run(at=at)
                self.assertEqual(report["state"], "waiting_update")
                self.assertTrue(any(row["reason"] == "close_source_before_1500_cutoff" for row in report["freshness"]["issues"]))
                self.assertFalse((root / ".v2_runtime/v22-intraday-shadow-state.json").exists())

    def test_status_only_success_does_not_claim_market_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            at = datetime(2026, 7, 20, 9, 15, tzinfo=CHINA)
            def runner(command, **kwargs):
                for relative in STATUS_ARTIFACTS:
                    write_json(root / relative, {"generated_at": at.isoformat()})
                return subprocess.CompletedProcess(command, 0, "ok", "")
            report = V22IntradayShadowRunner(root, command_runner=runner).run(at=at)
            self.assertEqual(report["state"], "completed")
            self.assertEqual(report["freshness"]["state"], "status_only")
            self.assertFalse(report["freshness"]["market_data_refreshed"])
            self.assertFalse(report["same_day_comparison"]["allowed"])

    def test_command_launch_error_records_failure_and_remains_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            def runner(*args, **kwargs):
                raise OSError("missing script")
            report = V22IntradayShadowRunner(root, command_runner=runner).run(at=datetime(2026, 7, 20, 10, 1, tzinfo=CHINA))
            self.assertEqual(report["state"], "failed")
            self.assertEqual(report["steps"][0]["stderr_tail"], "OSError")
            self.assertFalse((root / ".v2_runtime/v22-intraday-shadow-state.json").exists())

    def test_explicit_failed_json_with_zero_exit_stops_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            runner = lambda command, **kwargs: subprocess.CompletedProcess(command, 0, '{"state":"failed"}', "")
            report = V22IntradayShadowRunner(root, command_runner=runner).run(at=datetime(2026, 7, 20, 10, 1, tzinfo=CHINA))
            self.assertEqual(report["state"], "failed")
            self.assertEqual(len(report["steps"]), 1)


if __name__ == "__main__":
    unittest.main()


from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from v2_platform.intraday_shadow import V22IntradayShadowRunner


ROOT = Path(__file__).resolve().parents[1]
CHINA = ZoneInfo("Asia/Shanghai")


class V22IntradayShadowTests(unittest.TestCase):
    def prepare(self, root: Path) -> None:
        (root / "config").mkdir(parents=True)
        for filename in ("v2-market-calendar.json", "v2-intraday-shadow.json"):
            (root / "config" / filename).write_text((ROOT / "config" / filename).read_text(encoding="utf-8"), encoding="utf-8")

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
                return subprocess.CompletedProcess(command, 0, "ok", "")

            report = V22IntradayShadowRunner(root, command_runner=runner).run(
                at=datetime(2026, 7, 20, 14, 35, tzinfo=CHINA)
            )
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
                return subprocess.CompletedProcess(command, 0, "ok", "")

            report = V22IntradayShadowRunner(root, command_runner=runner).run(
                at=datetime(2026, 7, 20, 14, 35, tzinfo=CHINA)
            )
            self.assertEqual(report["state"], "skipped")
            self.assertEqual(report["reason"], "outside_checkpoint")
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()

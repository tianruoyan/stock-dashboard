from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v2_platform.v1_public_baseline import PUBLIC_RESULT_PATHS, V1PublicBaselineImporter


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class V1PublicBaselineImporterTests(unittest.TestCase):
    def test_empty_current_alert_keeps_expired_v2_history_for_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "v1"
            self.prepare(root, source)
            for relative in PUBLIC_RESULT_PATHS:
                payload = {"timestamp": "2026-08-24T21:00:00+08:00"}
                if relative == "data/alert.json":
                    payload.update({"alerts": [], "note": "今天原时点数据缺失"})
                    write(root / relative, {
                        "timestamp": "2026-08-11T11:00:00+08:00",
                        "alerts": [{"id": "old", "time": "2026-08-11T10:30:00+08:00", "valid_until": "2026-08-11T10:35:00+08:00"}],
                    })
                write(source / relative, payload)

            report = V1PublicBaselineImporter(root).run()
            alert = json.loads((root / "data/alert.json").read_text(encoding="utf-8"))
            row = next(item for item in report["files"] if item["path"] == "data/alert.json")
            self.assertEqual(row["state"], "imported_with_alert_history")
            self.assertEqual(alert["timestamp"], "2026-08-24T21:00:00+08:00")
            self.assertEqual(alert["alerts"], [])
            self.assertEqual([item["id"] for item in alert["historical_alerts"]], ["old"])
            self.assertTrue(alert["history_retained"])

    def prepare(self, root: Path, source: Path) -> None:
        write(root / "config/v2-rollout.json", {"production_v1": {"path": str(source)}})
        write(root / "config/v2-publish-policy.json", {
            "name": "test-public-data",
            "version": "test-1",
            "include_globs": ["data/**/*.json"],
            "exclude_globs": [],
            "deny_globs": [".v2_private/**"],
            "sensitive_json_keys": ["user_note", "user_priority"],
            "target_remote": "origin",
            "target_branch": "main",
            "max_push_attempts": 1,
        })

    def test_imports_only_newer_public_results_without_writing_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "v2"
            source = Path(tmp) / "v1"
            self.prepare(root, source)
            before = {}
            for relative in PUBLIC_RESULT_PATHS:
                payload = {"timestamp": "2026-07-30T10:00:00+08:00", "summary": relative}
                write(source / relative, payload)
                write(root / relative, {"timestamp": "2026-07-29T10:00:00+08:00"})
                before[relative] = (source / relative).read_bytes()
            report = V1PublicBaselineImporter(root).run()
            self.assertEqual(report["imported_count"], len(PUBLIC_RESULT_PATHS))
            for relative in PUBLIC_RESULT_PATHS:
                self.assertEqual((source / relative).read_bytes(), before[relative])
                self.assertEqual(json.loads((root / relative).read_text())["summary"], relative)
            self.assertFalse(report["guardrails"]["user_assets_read"])

    def test_sensitive_fields_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "v2"
            source = Path(tmp) / "v1"
            self.prepare(root, source)
            write(source / "data/premarket.json", {
                "timestamp": "2026-07-30T09:20:00+08:00",
                "nested": {"user_note": "private"},
            })
            report = V1PublicBaselineImporter(root).run()
            row = next(item for item in report["files"] if item["path"] == "data/premarket.json")
            self.assertEqual(row["state"], "blocked_sensitive_fields")
            self.assertFalse((root / "data/premarket.json").exists())

    def test_older_source_never_overwrites_newer_v2_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "v2"
            source = Path(tmp) / "v1"
            self.prepare(root, source)
            write(source / "data/intraday.json", {"timestamp": "2026-07-29T10:00:00+08:00", "value": "old"})
            write(root / "data/intraday.json", {"timestamp": "2026-07-30T10:00:00+08:00", "value": "new"})
            report = V1PublicBaselineImporter(root).run()
            row = next(item for item in report["files"] if item["path"] == "data/intraday.json")
            self.assertEqual(row["state"], "kept_newer_destination")
            self.assertEqual(json.loads((root / "data/intraday.json").read_text())["value"], "new")

    def test_quote_refresh_does_not_make_stale_analysis_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "v2"
            source = Path(tmp) / "v1"
            self.prepare(root, source)
            write(source / "data/intraday.json", {
                "timestamp": "2026-07-29T15:00:00+08:00",
                "market_data_as_of": "2026-07-30T15:00:00+08:00",
                "value": "stale_analysis_with_fresh_quotes",
            })
            write(root / "data/intraday.json", {
                "timestamp": "2026-07-30T14:30:00+08:00",
                "market_data_as_of": "2026-07-30T14:30:00+08:00",
                "value": "current_analysis",
            })

            report = V1PublicBaselineImporter(root).run()

            row = next(item for item in report["files"] if item["path"] == "data/intraday.json")
            self.assertEqual(row["state"], "kept_newer_destination")
            self.assertEqual(json.loads((root / "data/intraday.json").read_text())["value"], "current_analysis")
            self.assertFalse(report["guardrails"]["quote_refresh_treated_as_new_analysis"])


if __name__ == "__main__":
    unittest.main()

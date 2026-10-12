from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from v2_platform.public_market_export import OUTPUT, UNAPPROVED, export_public_market_facts

NOW = datetime(2026, 7, 20, 10, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
AS_OF = "2026-07-20T10:08:00+08:00"
CANARY = "PRIVATE_SECRET_CANARY_DO_NOT_PUBLISH"


def write(root: Path, relative: str, value: dict) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class PublicMarketExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / "source"
        self.target = Path(self.tmp.name) / "target"
        self.breadth = {
            "trade_date": "2026-07-20", "as_of": AS_OF,
            "source_id": "eastmoney_a_share_universe_live", "quality_state": "usable",
            "universe_definition_id": "cn_a_sh_sz_bj_valid_quote_v2",
            "advance_count": 2100, "decline_count": 2400, "flat_count": 100,
            "total_count": 4600, "missing_quote_count": 5,
        }
        self.liquidity = {
            "trade_date": "2026-07-20", "as_of": AS_OF,
            "source_id": "eastmoney_a_share_universe_live_turnover", "quality_state": "degraded",
            "total_turnover": 9000.25, "unit": "亿元",
        }
        self.health = {"state": "usable", "trade_date": "2026-07-20", "guardrails": {"public_sources_only": True, "user_assets_read": False, "user_assets_modified": False}}
        self.seed()

    def seed(self):
        write(self.source, "local_inputs/market-breadth.json", self.breadth)
        write(self.source, "local_inputs/market-liquidity.json", self.liquidity)
        write(self.source, "data/v2/public-market-fact-health.json", self.health)

    def run_export(self, apply=True):
        return export_public_market_facts(self.source, self.target, apply=apply, now=NOW)

    def read_output(self):
        return json.loads((self.target / OUTPUT).read_text())

    def test_default_preview_performs_no_writes(self):
        result = self.run_export(apply=False)
        self.assertEqual(result["state"], "ready")
        self.assertFalse(result["applied"])
        self.assertFalse(self.target.exists())

    def test_applies_only_approved_file_and_preserves_other_projections(self):
        originals = {}
        for path in UNAPPROVED:
            write(self.target, path, {"retained": path, "as_of": "2026-07-18T15:00:00+08:00"})
            originals[path] = (self.target / path).read_bytes()
        result = self.run_export()
        self.assertEqual(result["state"], "updated")
        self.assertEqual(result["mode"], "partial_public_facts")
        self.assertEqual(len(result["skipped"]), 7)
        self.assertFalse(result["decision_readiness"])
        for path, data in originals.items():
            self.assertEqual((self.target / path).read_bytes(), data)
        payload = self.read_output()
        self.assertEqual(payload["as_of"], AS_OF)
        self.assertEqual(payload["public_export"]["source_as_of"]["liquidity"], AS_OF)
        self.assertEqual(len(payload["dimensions"]), 2)
        self.assertEqual(payload["primary_state"], "unknown")
        self.assertFalse(payload["public_export"]["decision_readiness"])
        self.assertNotEqual(payload["built_at"], payload["as_of"])

    def test_private_canaries_are_not_copied_at_any_depth(self):
        private = {"user_note": CANARY, "holdings": [{"account_id": CANARY}], "api_key": CANARY}
        self.breadth.update(private)
        self.breadth.update(source_name=CANARY, source_url=CANARY, conclusion=CANARY, evidence=private, nested={"facts": private})
        self.liquidity.update(private)
        self.liquidity.update(quality_note=CANARY, comparison_method=CANARY, unexpected=private)
        self.health.update(source_error=CANARY, outputs=[private])
        self.seed()
        for name in UNAPPROVED:
            write(self.source, name, private)
        write(self.source, ".v2_private/user-assets.json", private)
        result = self.run_export()
        self.assertEqual(result["state"], "updated")
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertNotIn(CANARY, (self.target / OUTPUT).read_text())
        self.assertEqual(sorted(p.relative_to(self.target).as_posix() for p in self.target.rglob("*.json")), [OUTPUT])

    def test_string_secret_in_numeric_field_blocks_without_echo(self):
        self.breadth["advance_count"] = CANARY
        self.seed()
        result = self.run_export()
        self.assertEqual(result["state"], "blocked")
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertFalse((self.target / OUTPUT).exists())

    def test_source_identifier_cannot_smuggle_secret(self):
        self.breadth["source_id"] = CANARY
        self.seed()
        result = self.run_export()
        self.assertEqual(result["reason"], "public_source_not_allowlisted")
        self.assertNotIn(CANARY, json.dumps(result))

    def test_missing_and_malformed_source_retain_existing_bytes(self):
        self.run_export()
        original = (self.target / OUTPUT).read_bytes()
        path = self.source / "local_inputs/market-breadth.json"
        path.unlink()
        self.assertEqual(self.run_export()["state"], "blocked")
        path.write_text('{"oops":')
        self.assertEqual(self.run_export()["state"], "blocked")
        self.assertEqual((self.target / OUTPUT).read_bytes(), original)

    def test_naive_missing_future_stale_cross_day_source_blocks(self):
        cases = [(None, "source_as_of_required"), ("2026-07-20T10:08:00", "source_timezone_required"), ("bad", "source_as_of_invalid"), ("2026-07-20T10:11:00+08:00", "source_in_future"), ("2026-07-20T09:00:00+08:00", "source_stale"), ("2026-07-19T15:00:00+08:00", "source_trade_date_mismatch")]
        for stamp, reason in cases:
            with self.subTest(stamp=stamp):
                self.breadth["as_of"] = stamp
                self.seed()
                result = self.run_export()
                self.assertEqual(result["reason"], reason)
                self.assertFalse((self.target / OUTPUT).exists())

    def test_generated_at_does_not_refresh_old_source(self):
        self.breadth.update(as_of="2026-07-20T09:00:00+08:00", generated_at=NOW.isoformat(), built_at=NOW.isoformat())
        self.seed()
        self.assertEqual(self.run_export()["reason"], "source_stale")

    def test_existing_newer_or_equal_is_never_replaced(self):
        for stamp in [AS_OF, "2026-07-20T10:09:00+08:00", "2026-07-21T09:30:00+08:00"]:
            with self.subTest(stamp=stamp):
                write(self.target, OUTPUT, {"as_of": stamp, "important": "keep"})
                original = (self.target / OUTPUT).read_bytes()
                self.assertEqual(self.run_export()["state"], "retained")
                self.assertEqual((self.target / OUTPUT).read_bytes(), original)

    def test_existing_newer_individual_source_is_retained(self):
        write(self.target, OUTPUT, {"as_of": "2026-07-20T10:00:00+08:00", "dimensions": [{"dimension_code": "liquidity", "as_of": "2026-07-20T10:09:00+08:00"}]})
        self.assertEqual(self.run_export()["reason"], "existing_source_newer_retained")

    def test_existing_unknown_date_or_bad_json_is_not_overwritten(self):
        write(self.target, OUTPUT, {"built_at": NOW.isoformat()})
        original = (self.target / OUTPUT).read_bytes()
        self.assertEqual(self.run_export()["reason"], "existing_output_date_unverified")
        self.assertEqual((self.target / OUTPUT).read_bytes(), original)
        (self.target / OUTPUT).write_text("broken")
        self.assertEqual(self.run_export()["reason"], "existing_output_date_unverified")
        self.assertEqual((self.target / OUTPUT).read_text(), "broken")

    def test_count_errors_boolean_and_nonfinite_are_rejected(self):
        for value in [-1, True, float("nan"), float("inf"), 1.5, 30000, 2101]:
            with self.subTest(value=value):
                self.breadth["advance_count"] = value
                self.seed()
                self.assertEqual(self.run_export()["state"], "blocked")

    def test_retained_facts_and_private_provenance_are_blocked(self):
        self.health["state"] = "waiting_update"
        self.seed()
        self.assertEqual(self.run_export()["reason"], "source_not_refreshed")
        self.health["state"] = "usable"
        self.health["guardrails"]["user_assets_read"] = True
        self.seed()
        self.assertEqual(self.run_export()["reason"], "public_provenance_unverified")

    def test_source_and_target_must_be_separate(self):
        for target in [self.source, self.source / "public", self.source.parent]:
            result = export_public_market_facts(self.source, target, apply=True, now=NOW)
            self.assertEqual(result["reason"], "source_target_must_be_separate")

    def test_source_and_destination_symlinks_are_rejected(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "market-breadth.json").write_text(json.dumps(self.breadth))
        source = self.source / "local_inputs/market-breadth.json"
        source.unlink()
        source.symlink_to(outside / "market-breadth.json")
        self.assertEqual(self.run_export()["reason"], "symlink_not_allowed")
        source.unlink()
        self.seed()
        self.target.mkdir()
        (self.target / "data").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.run_export()["reason"], "symlink_not_allowed")
        self.assertFalse((outside / "v2").exists())

    def test_mismatched_snapshot_and_unverified_scope_are_blocked(self):
        self.liquidity["as_of"] = "2026-07-20T10:07:00+08:00"
        self.seed()
        self.assertEqual(self.run_export()["reason"], "source_snapshot_mismatch")
        self.liquidity["as_of"] = AS_OF
        self.liquidity["unit"] = "dollars"
        self.seed()
        self.assertEqual(self.run_export()["reason"], "fact_scope_unverified")

    def test_source_files_are_never_modified(self):
        before = {p: p.read_bytes() for p in self.source.rglob("*.json")}
        self.run_export()
        self.assertEqual({p: p.read_bytes() for p in self.source.rglob("*.json")}, before)


if __name__ == "__main__":
    unittest.main()

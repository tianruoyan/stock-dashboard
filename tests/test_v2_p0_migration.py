from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class V2P0MigrationTests(unittest.TestCase):
    def test_applied_migration_keeps_raw_snapshots_and_one_evaluation_snapshot_per_group(self) -> None:
        index = json.loads((ROOT / "data/v2/replay-index.json").read_text(encoding="utf-8"))
        audit = json.loads((ROOT / "data/v2/p0-migration-audit.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(index["snapshot_count"], 6)
        eligible = [item for item in index["snapshots"] if item.get("evaluation_eligible") is True]
        self.assertEqual(index["evaluation_snapshot_count"], len(eligible))
        self.assertEqual(len({item["canonical_key"] for item in eligible}), len(eligible))
        for canonical_key in {item["canonical_key"] for item in index["snapshots"]}:
            group = [item for item in index["snapshots"] if item["canonical_key"] == canonical_key]
            self.assertLessEqual(sum(item.get("evaluation_eligible") is True for item in group), 1)
        self.assertFalse(audit["original_snapshots_deleted"])
        self.assertEqual(audit["before"]["raw_snapshot_count"], 6)
        self.assertTrue((ROOT / audit["backup_dir"]).is_dir())

    def test_derived_results_only_include_canonical_snapshot(self) -> None:
        index = json.loads((ROOT / "data/v2/replay-index.json").read_text(encoding="utf-8"))
        outcomes = json.loads((ROOT / "data/v2/signal-outcomes.json").read_text(encoding="utf-8"))
        review = json.loads((ROOT / "data/v2/signal-review.json").read_text(encoding="utf-8"))
        canonical_ids = {
            item["snapshot_id"]
            for item in index["snapshots"]
            if item.get("evaluation_eligible") is True
        }
        self.assertTrue(outcomes["signals"])
        self.assertEqual({item["snapshot_id"] for item in outcomes["signals"]}, canonical_ids)
        self.assertEqual(review["snapshot_count"], len(canonical_ids))
        self.assertEqual(
            review["pending_signal_count"] + review["evaluated_signal_count"],
            len(outcomes["signals"]),
        )


if __name__ == "__main__":
    unittest.main()

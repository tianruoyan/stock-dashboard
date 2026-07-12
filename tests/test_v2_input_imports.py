from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v2_platform.input_imports import V2InputImporter


ROOT = Path(__file__).resolve().parents[1]


class V2InputImporterTests(unittest.TestCase):
    def prepare(self, root: Path) -> Path:
        (root / "config").mkdir(parents=True)
        (root / "config" / "v2-input-contracts.json").write_text((ROOT / "config" / "v2-input-contracts.json").read_text(encoding="utf-8"), encoding="utf-8")
        input_dir = root / "local_inputs"
        input_dir.mkdir()
        return input_dir

    def test_missing_inputs_are_pending_not_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self.prepare(root)
            report = V2InputImporter(root, input_dir).run()
            self.assertEqual(report["status"], "no_change")
            self.assertTrue(all(item["status"] == "pending" for item in report["contracts"]))

    def test_valid_microcap_input_is_atomic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self.prepare(root)
            payload = {"observations": [{
                "source_id": "csi2000_official_proxy", "trade_date": "2026-07-10",
                "as_of": "2026-07-10T15:00:00+08:00", "close": 3000.0, "change_pct": -0.5,
                "source_url": "https://example.com/source"
            }]}
            (input_dir / "microcap-observation.json").write_text(json.dumps(payload), encoding="utf-8")
            first = V2InputImporter(root, input_dir).run()
            second = V2InputImporter(root, input_dir).run()
            self.assertEqual(next(item for item in first["contracts"] if item["id"] == "microcap_observation")["status"], "updated")
            self.assertEqual(next(item for item in second["contracts"] if item["id"] == "microcap_observation")["status"], "unchanged")
            self.assertEqual(json.loads((root / "data/v2/inputs/microcap-observation.json").read_text()), payload)

    def test_invalid_input_never_overwrites_previous_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self.prepare(root)
            target = root / "data/v2/inputs/microcap-observation.json"
            target.parent.mkdir(parents=True)
            previous = {"observations": [{"preserved": True}]}
            target.write_text(json.dumps(previous), encoding="utf-8")
            invalid = {"observations": [{"source_id": "x", "trade_date": "bad", "as_of": "no-timezone", "close": -1}]}
            (input_dir / "microcap-observation.json").write_text(json.dumps(invalid), encoding="utf-8")
            report = V2InputImporter(root, input_dir).run()
            self.assertEqual(report["status"], "invalid")
            self.assertEqual(json.loads(target.read_text()), previous)


if __name__ == "__main__":
    unittest.main()

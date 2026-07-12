from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v2_platform.outcome_price_collector import V2OutcomePriceCollector


class OutcomePriceCollectorTests(unittest.TestCase):
    def test_backfills_reference_and_only_due_windows_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snap = root / "data" / "v2" / "snapshots" / "2026-07-10" / "snapshot_a.json"
            snap.parent.mkdir(parents=True)
            snap.write_text(json.dumps({"snapshot_id":"snapshot_a","decision_date":"2026-07-10","decision_as_of":"2026-07-10T14:56:00+08:00","signals":[{"signal_id":"s1","securities":[{"code":"sh600000"}],"outcome_windows":[{"window":"T+1","target_date":"2026-07-13"},{"window":"T+3","target_date":"2026-07-15"}]}]}), encoding="utf-8")
            (root / "data" / "v2" / "replay-index.json").write_text(json.dumps({"snapshots":[{"path":str(snap.relative_to(root))}]}), encoding="utf-8")
            (root / "data" / "v2" / "public-input-health.json").write_text(json.dumps({"state":"usable","collectors":[]}), encoding="utf-8")
            bars = json.dumps([{"day":"2026-07-10","close":"10.00"},{"day":"2026-07-13","close":"10.50"}]).encode()
            collector = V2OutcomePriceCollector(root, fetcher=lambda _url: bars)
            first = collector.collect()
            second = collector.collect()
            payload = json.loads((root / "data" / "v2" / "outcome-prices.json").read_text())
            row = payload["observations"][0]
            self.assertEqual(first["state"], "updated")
            self.assertEqual(second["state"], "current")
            self.assertEqual(row["reference_price"], 10.0)
            self.assertEqual(row["windows"]["T+1"]["price"], 10.5)
            self.assertNotIn("T+3", row["windows"])
            health = json.loads((root / "data" / "v2" / "public-input-health.json").read_text())
            self.assertEqual(health["collectors"][0]["id"], "outcome_prices")
            self.assertEqual(health["collectors"][0]["state"], "current")

    def test_preserves_non_public_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "data" / "v2"
            out.mkdir(parents=True)
            (out / "replay-index.json").write_text('{"snapshots":[]}', encoding="utf-8")
            manual = {"observations":[{"snapshot_id":"a","signal_id":"b","code":"c","source":"licensed","reference_price":1,"windows":{}}]}
            (out / "outcome-prices.json").write_text(json.dumps(manual), encoding="utf-8")
            V2OutcomePriceCollector(root, fetcher=lambda _url: b"[]").collect()
            payload = json.loads((out / "outcome-prices.json").read_text())
            self.assertEqual(payload["observations"][0]["source"], "licensed")


if __name__ == "__main__":
    unittest.main()

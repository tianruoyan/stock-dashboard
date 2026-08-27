from __future__ import annotations

import tempfile
import unittest
import json
from datetime import date
from pathlib import Path

from v2_platform.public_refresh import V2PublicInputRefresher


ROOT = Path(__file__).resolve().parents[1]


class V2PublicRefreshTests(unittest.TestCase):
    def prepare(self, root: Path) -> None:
        (root / "config").mkdir()
        (root / "config/v2-market-calendar.json").write_text((ROOT / "config/v2-market-calendar.json").read_text(encoding="utf-8"), encoding="utf-8")

    def test_refresh_is_idempotent_for_same_trade_date(self) -> None:
        calls = {"micro":0,"sentiment":0,"events":0}
        def micro(day):
            calls["micro"] += 1
            return {"observations":[{"trade_date":day.isoformat()}]}
        def sentiment(day):
            calls["sentiment"] += 1
            return {"trade_date":day.isoformat()}
        def events():
            calls["events"] += 1
            return {"events":[{"event_id":"e1","published_at":"2026-01-01T00:00:00+08:00"}],"collection_state":"usable"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            refresher = V2PublicInputRefresher(root, microcap_collector=micro, sentiment_collector=sentiment, official_event_collector=events)
            first = refresher.run(date(2026,7,12))
            second = refresher.run(date(2026,7,12))
            self.assertEqual(first["state"], "usable")
            self.assertTrue(all(item["state"] == "updated" for item in first["collectors"]))
            self.assertTrue(all(item["state"] == "current" for item in second["collectors"]))
            self.assertEqual(calls, {"micro":1,"sentiment":1,"events":1})

    def test_failed_refresh_preserves_previous_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            path = root / "local_inputs/microcap-observation.json"
            path.parent.mkdir()
            path.write_text('{"observations":[{"trade_date":"2026-07-09"}]}', encoding="utf-8")
            def fail(day): raise RuntimeError("network")
            refresher = V2PublicInputRefresher(root, microcap_collector=fail, sentiment_collector=lambda day:{"trade_date":day.isoformat()}, official_event_collector=lambda:{"events":[{"event_id":"e1","published_at":"x"}]})
            report = refresher.run(date(2026,7,12))
            micro = next(item for item in report["collectors"] if item["id"] == "microcap")
            self.assertEqual(micro["state"], "failed")
            self.assertTrue(micro["previous_input_preserved"])
            self.assertIn("2026-07-09", path.read_text())

    def test_refresh_preserves_other_collector_health_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            health_path = root / "data/v2/public-input-health.json"
            health_path.parent.mkdir(parents=True)
            health_path.write_text(json.dumps({
                "state": "usable",
                "collectors": [{"id": "outcome_prices", "state": "current", "observation_count": 2}],
            }), encoding="utf-8")
            refresher = V2PublicInputRefresher(
                root,
                microcap_collector=lambda day: {"observations": [{"trade_date": day.isoformat()}]},
                sentiment_collector=lambda day: {"trade_date": day.isoformat()},
                official_event_collector=lambda: {"events": [{"event_id": "e1", "published_at": "x"}]},
            )
            report = refresher.run(date(2026, 7, 12))
            outcome = next(item for item in report["collectors"] if item["id"] == "outcome_prices")
            self.assertEqual(outcome["state"], "current")
            self.assertEqual(outcome["observation_count"], 2)


if __name__ == "__main__":
    unittest.main()

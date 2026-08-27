from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from v2_platform.market_structure import V2MarketStructureBuilder


ROOT = Path(__file__).resolve().parents[1]


class V2MarketStructureTests(unittest.TestCase):
    def make_root(self) -> tempfile.TemporaryDirectory:
        return tempfile.TemporaryDirectory()

    def copy_configs(self, root: Path) -> None:
        (root / "config").mkdir(parents=True)
        for name in ("v2-market-structure-sources.json", "v2-market-calendar.json"):
            (root / "config" / name).write_text((ROOT / "config" / name).read_text(encoding="utf-8"), encoding="utf-8")

    def test_missing_quote_never_fabricates_direction(self) -> None:
        with self.make_root() as tmp:
            root = Path(tmp)
            self.copy_configs(root)
            payload = V2MarketStructureBuilder(root, today=date(2026, 7, 12)).build()
            self.assertEqual(payload["state"], "proxy_configured_data_pending")
            self.assertEqual(payload["direction"], "unknown")
            self.assertIsNone(payload["selected_observation"])

    def test_complete_latest_official_proxy_observation_is_usable(self) -> None:
        with self.make_root() as tmp:
            root = Path(tmp)
            self.copy_configs(root)
            path = root / "data" / "v2" / "inputs" / "microcap-observation.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"observations": [{
                "source_id": "csi2000_official_proxy",
                "trade_date": "2026-07-10",
                "as_of": "2026-07-10T15:00:00+08:00",
                "close": 3123.45,
                "change_pct": -0.42,
                "source_url": "https://www.csindex.com.cn/"
            }]}), encoding="utf-8")
            payload = V2MarketStructureBuilder(root, today=date(2026, 7, 12)).build()
            self.assertEqual(payload["state"], "usable_proxy")
            self.assertEqual(payload["direction"], "down")
            self.assertEqual(payload["selected_observation"]["quality_state"], "usable")
            self.assertIn("不等于纯微盘", payload["proxy"]["scope_note"])

    def test_stale_or_naive_timestamp_is_rejected(self) -> None:
        with self.make_root() as tmp:
            root = Path(tmp)
            self.copy_configs(root)
            path = root / "data" / "v2" / "inputs" / "microcap-observation.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"observations": [{
                "source_id": "csi2000_official_proxy",
                "trade_date": "2026-07-09",
                "as_of": "2026-07-09T15:00:00",
                "close": 3100.0,
                "change_pct": 1.0,
                "source_url": "https://www.csindex.com.cn/"
            }]}), encoding="utf-8")
            payload = V2MarketStructureBuilder(root, today=date(2026, 7, 12)).build()
            self.assertEqual(payload["direction"], "unknown")
            flags = payload["observation_checks"][0]["quality_flags"]
            self.assertIn("timezone_missing", flags)
            self.assertIn("not_latest_expected_trade_date", flags)

    def test_premarket_uses_latest_completed_trade_date(self) -> None:
        with self.make_root() as tmp:
            root = Path(tmp)
            self.copy_configs(root)
            path = root / "data" / "v2" / "inputs" / "microcap-observation.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"observations": [{
                "source_id": "csi2000_official_proxy",
                "trade_date": "2026-08-10",
                "as_of": "2026-08-10T15:00:00+08:00",
                "close": 3120.83,
                "change_pct": 1.15,
                "source_url": "https://www.csindex.com.cn/"
            }]}), encoding="utf-8")
            payload = V2MarketStructureBuilder(
                root,
                now=datetime.fromisoformat("2026-08-11T08:30:00+08:00"),
            ).build()
            self.assertEqual(payload["expected_trade_date"], "2026-08-10")
            self.assertEqual(payload["state"], "usable_proxy")
            self.assertEqual(payload["selected_observation"]["trade_date"], "2026-08-10")


if __name__ == "__main__":
    unittest.main()

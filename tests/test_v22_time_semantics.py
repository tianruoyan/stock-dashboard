from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v2_platform.v22_time_semantics import V22TimeSemanticsBuilder


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class V22TimeSemanticsTests(unittest.TestCase):
    def test_different_market_dates_block_result_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "data/v2/decision-system.json", {"system": {"decision_as_of": "2026-07-13T10:00:00+08:00", "latest_source_at": "2026-07-18T18:00:00+08:00", "generated_at": "2026-07-18T18:01:00+08:00"}})
            write(root / "data/v2/v22/market-environment.json", {"trade_date": "2026-07-17", "as_of": "2026-07-17T15:00:00+08:00"})
            write(root / "data/v2/v22/decision-cases.json", {"trade_date": "2026-07-17", "as_of": "2026-07-17T15:00:00+08:00", "built_at": "2026-07-18T18:00:00+08:00"})
            payload = V22TimeSemanticsBuilder(root).build()
            self.assertFalse(payload["comparison"]["allowed"])
            self.assertFalse(payload["comparison"]["hit_rate_comparison_allowed"])
            self.assertIn("交易日未统一", payload["comparison"]["reason"])
            self.assertEqual(payload["sources"]["v2_baseline"]["market_date"], "2026-07-13")
            self.assertEqual(payload["field_definitions"]["generated_at"], "报告或投影生成时间")

    def test_generated_at_is_not_used_as_market_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "data/v2/decision-system.json", {"system": {"decision_as_of": "2026-07-17T14:00:00+08:00", "generated_at": "2026-07-18T18:01:00+08:00"}})
            write(root / "data/v2/v22/market-environment.json", {"trade_date": "2026-07-17", "as_of": "2026-07-17T15:00:00+08:00"})
            write(root / "data/v2/v22/decision-cases.json", {"trade_date": "2026-07-17", "as_of": "2026-07-17T14:30:00+08:00"})
            payload = V22TimeSemanticsBuilder(root).build()
            self.assertTrue(payload["comparison"]["allowed"])
            self.assertFalse(payload["guardrails"]["generated_at_used_as_market_date"])


if __name__ == "__main__":
    unittest.main()

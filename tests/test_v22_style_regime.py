from __future__ import annotations

import json
import unittest
from pathlib import Path

from v2_platform.style_regime import V22StyleRegimeBuilder


ROOT = Path(__file__).resolve().parents[1]


class V22StyleRegimeTests(unittest.TestCase):
    def test_four_independent_style_observations_are_built(self) -> None:
        environment = json.loads((ROOT / "data/v2/v22/market-environment.json").read_text(encoding="utf-8"))
        rows = V22StyleRegimeBuilder(ROOT).build(environment)
        self.assertEqual({item["style_id"] for item in rows}, {"old_deng", "middle_deng", "small_deng", "microcap"})
        self.assertTrue(all(item["user_assets_modified"] is False for item in rows))

    def test_microcap_is_not_derived_from_small_deng(self) -> None:
        environment = json.loads((ROOT / "data/v2/v22/market-environment.json").read_text(encoding="utf-8"))
        rows = {item["style_id"]: item for item in V22StyleRegimeBuilder(ROOT).build(environment)}
        self.assertEqual(rows["microcap"]["member_count"], 0)
        self.assertEqual(rows["microcap"]["breadth_state"], "proxy_only")
        self.assertIn("不等于纯微盘", rows["microcap"]["conclusion"])
        self.assertNotEqual(rows["microcap"]["representative_securities"], rows["small_deng"]["representative_securities"])

    def test_backfilled_style_baskets_have_price_breadth_and_turnover(self) -> None:
        environment = json.loads((ROOT / "data/v2/v22/market-environment.json").read_text(encoding="utf-8"))
        rows = {item["style_id"]: item for item in V22StyleRegimeBuilder(ROOT).build(environment)}
        for style_id in ("old_deng", "middle_deng", "small_deng"):
            self.assertEqual(rows[style_id]["turnover_state"], "observed")
            self.assertEqual(rows[style_id]["quality_state"], "usable")
            self.assertEqual(rows[style_id]["observed_count"], rows[style_id]["member_count"])
            self.assertNotIn("篮子成交额", rows[style_id]["conclusion"])
            self.assertNotIn("完整覆盖", rows[style_id]["conclusion"])
            self.assertTrue(any(term in rows[style_id]["conclusion"] for term in ("代表股", "资金", "抛压", "方向")))
        self.assertEqual(rows["microcap"]["turnover_state"], "unknown")
        self.assertEqual(rows["microcap"]["quality_state"], "degraded")


if __name__ == "__main__":
    unittest.main()

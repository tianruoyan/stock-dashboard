from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


FEED = load_script("build_decision_feed_for_test", "scripts/build_decision_feed.py")
SMOKE = load_script("smoke_dashboard_static_for_test", "scripts/smoke_dashboard_static.py")


class RelativeTradingDayTests(unittest.TestCase):
    def test_friday_plan_may_refer_to_next_monday(self) -> None:
        for module in (FEED, SMOKE):
            self.assertFalse(module.has_stale_relative_time("周一看核心股承接", "2026-08-07"))

    def test_previous_weekday_is_stale(self) -> None:
        for module in (FEED, SMOKE):
            self.assertTrue(module.has_stale_relative_time("周四数据待复核", "2026-08-07"))


if __name__ == "__main__":
    unittest.main()

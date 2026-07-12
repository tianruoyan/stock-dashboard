from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dashboard_audit", ROOT / "scripts" / "audit_dashboard_data.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class DashboardAuditSourceTests(unittest.TestCase):
    def test_historical_failures_are_retained_but_not_current_price_warnings(self) -> None:
        issues = []
        MODULE.validate_source_health(
            {
                "sources": {
                    "old": {"status": "failed", "last_check": "2026-07-09T10:00:00+08:00"},
                    "monitor_alert_quote_audit_1400": {"status": "failed", "checked_at": "2026-07-10T14:00:00+08:00"},
                    "monitor_alert_quote_audit_1430": {"status": "failed", "checked_at": "2026-07-10T14:30:00+08:00"},
                }
            },
            issues,
            "2026-07-10",
        )
        self.assertEqual(sum(item["code"] == "source_failed" for item in issues), 1)
        self.assertEqual(sum(item["code"] == "historical_source_failures" for item in issues), 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from audit_dashboard_data import structured_candidate_evidence_valid, validate_candidate_alert_evidence
from build_monitoring_coverage import market_breadth_text


TZ = timezone(timedelta(hours=8))


class DashboardRuntimeFixTests(unittest.TestCase):
    def test_monitoring_coverage_accepts_text_sentiment(self) -> None:
        self.assertEqual(market_breadth_text({}, {"sentiment": "风险释放加速"}), "")

    def test_structured_risk_candidate_accepts_multiple_board_moves(self) -> None:
        item = {
            "quote_audit": {
                "board_3m_change_pct": "-0.97%/-1.10%",
                "sanity_checks": {
                    "price_move_valid": True,
                    "volume_valid": True,
                    "direction_ratio_valid": True,
                },
            }
        }
        self.assertTrue(structured_candidate_evidence_valid(item, "risk"))

    def test_expired_weak_candidate_is_review_not_trading_blocker(self) -> None:
        item = {
            "time": "2026-07-20T10:00:00+08:00",
            "confirmation_level": "candidate",
            "alert_class": "risk",
            "reason": "缺少短周期结构化证据",
        }
        issues = []
        validate_candidate_alert_evidence(
            {"timestamp": "2026-07-20T10:00:00+08:00"},
            item,
            0,
            issues,
            datetime(2026, 7, 20, 10, 30, tzinfo=TZ),
            "morning",
        )
        self.assertEqual(issues[0]["code"], "historical_candidate_alert_evidence_weak")
        self.assertEqual(issues[0]["impact_level"], "signal_review")


if __name__ == "__main__":
    unittest.main()

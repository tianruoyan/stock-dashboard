from __future__ import annotations

import unittest

from v2_platform.environment_evidence import (
    evidence_ref,
    infer_session_phase,
    same_metric_conflicts,
    trade_date_of,
)


class V22EnvironmentEvidenceTests(unittest.TestCase):
    def make_ref(self, *, source_id: str, as_of: str, value: int) -> dict:
        return evidence_ref(
            snapshot_id="snapshot_test",
            dimension_code="sentiment_structure",
            evidence_role="risk",
            metric_name="跌停家数",
            metric_scope="market",
            metric_value=value,
            unit="家",
            source_id=source_id,
            source_label=source_id,
            source_url="https://example.com",
            source_as_of=as_of,
            quality_state="usable",
            rule_version="test",
            scope_definition="同一股票全集",
        )

    def test_same_time_scope_and_metric_preserves_conflicting_values(self) -> None:
        rows = [
            self.make_ref(source_id="source_a", as_of="2026-07-17T15:00:00+08:00", value=161),
            self.make_ref(source_id="source_b", as_of="2026-07-17T15:00:00+08:00", value=172),
        ]
        conflicts = same_metric_conflicts(rows)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual({item["value"] for item in conflicts[0]["values"]}, {161, 172})
        self.assertIn("保留全部原值", conflicts[0]["resolution"])

    def test_different_times_are_not_collapsed_into_a_conflict(self) -> None:
        rows = [
            self.make_ref(source_id="source_a", as_of="2026-07-17T14:30:00+08:00", value=153),
            self.make_ref(source_id="source_b", as_of="2026-07-17T15:00:00+08:00", value=161),
        ]
        self.assertEqual(same_metric_conflicts(rows), [])

    def test_timezone_and_session_are_explicit(self) -> None:
        self.assertEqual(trade_date_of("2026-07-17T15:00:00+08:00"), "2026-07-17")
        self.assertEqual(infer_session_phase("2026-07-17T14:30:00+08:00"), "afternoon")
        self.assertEqual(infer_session_phase("2026-07-17T15:00:00+08:00"), "close")
        self.assertIsNone(trade_date_of("2026-07-17T15:00:00"))

    def test_timezone_missing_evidence_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone"):
            evidence_ref(
                snapshot_id="snapshot_test",
                dimension_code="market_breadth",
                evidence_role="support",
                metric_name="上涨家数",
                metric_scope="market",
                metric_value=3000,
                unit="家",
                source_id="source_a",
                source_label="来源A",
                source_url=None,
                source_as_of="2026-07-17T15:00:00",
                quality_state="usable",
            )


if __name__ == "__main__":
    unittest.main()

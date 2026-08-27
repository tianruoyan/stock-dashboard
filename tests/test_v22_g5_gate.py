from __future__ import annotations

import unittest

from v2_platform.g5_gate import G5_RESULTS, build_g5_links


class V22G5GateTests(unittest.TestCase):
    def test_risk_state_suppresses_and_never_bypasses_other_gates(self) -> None:
        decision = {"validation_queue": [{"id": "one", "theme": "测试方向"}]}
        environment = {"environment_snapshot_id": "env", "quality_state": "degraded", "dimensions": [{"dimension_code": "sentiment_structure", "support_level": "suppress"}]}
        rows = build_g5_links(decision, environment, {"primary_state": "risk_release"}, [])
        self.assertEqual(rows[0]["g5_result"], "suppress")
        self.assertTrue(rows[0]["representative_stock_gate_still_required"])
        self.assertTrue(rows[0]["position_gate_still_required"])
        self.assertFalse(rows[0]["user_asset_identity_bypasses_gate"])
        self.assertFalse(rows[0]["user_assets_modified"])

    def test_result_vocabulary_is_closed(self) -> None:
        decision = {"opportunity_radar": [{"id": "one", "title": "测试机会"}]}
        environment = {"environment_snapshot_id": "env", "quality_state": "usable", "dimensions": []}
        rows = build_g5_links(decision, environment, {"primary_state": "repair"}, [])
        self.assertIn(rows[0]["g5_result"], G5_RESULTS)
        self.assertEqual(G5_RESULTS, {"support", "partial_support", "neutral", "suppress", "block"})


if __name__ == "__main__":
    unittest.main()

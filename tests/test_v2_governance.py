from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v2_platform.governance import V2GovernanceBuilder


ROOT = Path(__file__).resolve().parents[1]


class V2GovernanceTests(unittest.TestCase):
    def test_all_legacy_automation_tasks_have_valid_routing(self) -> None:
        payload = V2GovernanceBuilder(ROOT).build()
        self.assertEqual(payload["automation_routing"]["state"], "valid")
        names = {item["name"] for item in payload["automation_routing"]["tasks"]}
        required = {"A股港股盘中监测与盘前综合推送", "老登小登盘中提醒", "智谱季度投资追踪", "周一科技消息盘前汇总", "股票看板晚间发布核验"}
        self.assertTrue(required.issubset(names))
        self.assertIn("V2双轨收盘后验证", names)

    def test_blogger_content_can_never_become_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            for name in ("v2-source-governance.json", "v2-automation-routing.json"):
                (root / "config" / name).write_text((ROOT / "config" / name).read_text(encoding="utf-8"), encoding="utf-8")
            path = root / "data" / "v2" / "inputs" / "events.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"events": [{
                "event_id": "blog-1", "source_id": "author-1", "source_type": "blogger_social",
                "published_at": "2026-07-12T09:00:00+08:00", "observed_at": "2026-07-12T09:01:00+08:00",
                "title": "观点", "url": "https://example.com/post", "content_hash": "abc", "fact_state": "verified_fact"
            }]}), encoding="utf-8")
            event = V2GovernanceBuilder(root).build()["event_registry"]["events"][0]
            self.assertEqual(event["fact_state"], "expectation_only")
            self.assertIn("blogger_cannot_support_fact", event["quality_flags"])

    def test_fact_inference_action_layers_are_explicit(self) -> None:
        payload = V2GovernanceBuilder(ROOT).build()
        self.assertEqual(set(payload["fact_inference_action_layers"]), {"fact", "inference", "action"})
        self.assertEqual(payload["user_authorizations"]["routine_external_app_access"], "preauthorized")
        self.assertTrue(payload["user_authorizations"]["still_requires_explicit_confirmation"])

    def test_workspace_has_usable_official_event_seed(self) -> None:
        payload = V2GovernanceBuilder(ROOT).build()["event_registry"]
        self.assertGreater(payload["official_event_count"], 0)
        self.assertEqual(payload["blogger_event_count"], 0)
        self.assertIn("blogger_account_count", payload)
        self.assertIn("blogger_enabled_account_count", payload)

    def test_private_portfolio_values_are_never_exposed(self) -> None:
        payload = V2GovernanceBuilder(ROOT).build()["private_portfolio_governance"]
        self.assertFalse(payload["raw_values_published"])
        self.assertFalse(payload["trade_authorization"])
        self.assertNotIn("holdings", payload)

    def test_longbridge_is_reference_only_and_never_replaces_watchlist(self) -> None:
        payload = V2GovernanceBuilder(ROOT).build()["longbridge_analysis_references"]
        self.assertEqual(payload["mode"], "shadow_reference_only")
        self.assertFalse(payload["may_change_decision_or_action"])
        self.assertFalse(payload["may_change_user_assets"])
        self.assertFalse(payload["may_replace_or_sync_ths_watchlist"])
        self.assertFalse(payload["trading_enabled"])


if __name__ == "__main__":
    unittest.main()

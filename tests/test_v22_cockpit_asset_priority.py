from __future__ import annotations

import unittest

from v2_platform.stock_pool_v22 import prioritize_cockpit_assets


class V22CockpitAssetPriorityTests(unittest.TestCase):
    def test_user_assets_are_first_and_same_security_is_only_shown_once(self) -> None:
        users = [
            {"code": "sh600000", "name": "浦发银行", "user_priority": "normal", "user_intent": "watch"},
            {"code": "sz000001", "name": "平安银行", "user_priority": "high", "user_intent": "research"},
        ]
        formal = [
            {"code": "sh600000", "name": "浦发银行"},
            {"code": "sh688981", "name": "中芯国际"},
        ]
        temporary = [
            {"code": "sh688981", "name": "中芯国际"},
            {"code": "sz300001", "name": "特锐德"},
        ]
        result = prioritize_cockpit_assets(users, formal, temporary)
        self.assertEqual([item["code"] for item in result], ["sz000001", "sh600000", "sh688981", "sz300001"])
        self.assertEqual([item["display_layer"] for item in result], ["用户自选", "用户自选", "正式观察", "系统发现"])

    def test_intent_routing_changes_with_risk_or_opportunity_context(self) -> None:
        users = [
            {"code": "sh600000", "user_priority": "normal", "user_intent": "holding"},
            {"code": "sz000001", "user_priority": "normal", "user_intent": "watch"},
            {"code": "sh688981", "user_priority": "normal", "user_intent": "research"},
        ]
        risk = prioritize_cockpit_assets(users, [], [], context="risk")
        opportunity = prioritize_cockpit_assets(users, [], [], context="opportunity")
        self.assertEqual(risk[0]["code"], "sh600000")
        self.assertEqual(opportunity[0]["code"], "sz000001")
        self.assertEqual(risk[-1]["code"], "sh688981")
        self.assertEqual(opportunity[-1]["code"], "sh688981")

    def test_style_samples_are_not_an_input_to_cockpit_asset_priority(self) -> None:
        result = prioritize_cockpit_assets([], [], [{"code": "sh688981", "style_relation": "小登样本"}])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["display_layer"], "系统发现")
        self.assertNotEqual(result[0]["display_layer"], "用户自选")


if __name__ == "__main__":
    unittest.main()

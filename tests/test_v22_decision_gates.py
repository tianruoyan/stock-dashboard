from __future__ import annotations

import unittest

from v2_platform.decision_gates import decision_maturity, evaluate_gates


def stock(code: str, name: str, role: str) -> dict:
    return {
        "stock_code": code,
        "name": name,
        "stock_change_pct": 2.0,
        "stock_quote_as_of": "2026-07-18T10:00:00+08:00",
        "stock_quote_source": "测试公开行情",
        "role": role,
        "basis": "代表股与主题同向。",
    }


class V22DecisionGateTests(unittest.TestCase):
    def test_every_case_has_exactly_g0_through_g7(self) -> None:
        gates = evaluate_gates({}, business_path="theme_opportunity", environment_gate=None, overall_quality="blocked", ended=False)
        self.assertEqual([item["gate_id"] for item in gates], [f"G{index}" for index in range(8)])

    def test_complete_theme_case_can_be_decision_ready_but_is_not_a_buy_order(self) -> None:
        card = {
            "theme": "测试主题",
            "triggered_at": "2026-07-18T09:35:00+08:00",
            "conclusion": "板块扩散且代表股同向。",
            "evidence": [{"summary": "同日触发", "accepted": True}],
            "representative_stocks": [stock("sh600001", "甲", "核心"), stock("sz000002", "乙", "中军")],
            "position_facts": ["未出现连续加速"],
            "tradability": "流动性可用",
            "confirm_conditions": ["扩散继续"],
            "invalidation_conditions": ["代表股背离"],
            "valid_until": "2026-07-18T10:30:00+08:00",
        }
        gates = evaluate_gates(card, business_path="theme_opportunity", environment_gate={"g5_result": "support", "reason": "环境支持"}, overall_quality="usable", ended=False)
        self.assertTrue(all(item["state"] == "pass" for item in gates))
        self.assertEqual(decision_maturity(gates, ended=False, signal_state="verified", business_path="theme_opportunity"), "decision_ready")

    def test_verified_trigger_is_not_ready_when_position_or_validity_is_missing(self) -> None:
        card = {
            "theme": "测试主题",
            "triggered_at": "2026-07-18T09:35:00+08:00",
            "conclusion": "触发已核验。",
            "evidence": [{"summary": "同日触发", "accepted": True}],
            "representative_stocks": [stock("sh600001", "甲", "核心"), stock("sz000002", "乙", "中军")],
            "confirm_conditions": ["扩散继续"],
            "invalidation_conditions": ["代表股背离"],
        }
        gates = evaluate_gates(card, business_path="theme_opportunity", environment_gate={"g5_result": "support"}, overall_quality="usable", ended=False)
        self.assertNotEqual(decision_maturity(gates, ended=False, signal_state="verified", business_path="theme_opportunity"), "decision_ready")
        self.assertIn(next(item for item in gates if item["gate_id"] == "G6")["state"], {"pending", "fail"})
        self.assertNotEqual(next(item for item in gates if item["gate_id"] == "G7")["state"], "pass")

    def test_explicit_single_source_representatives_remain_pending(self) -> None:
        row = stock("sh600001", "甲", "核心")
        row.update({"stock_quote_verification": "等待第二来源确认", "cross_source_verified": False})
        card = {
            "theme": "测试主题",
            "triggered_at": "2026-07-18T09:35:00+08:00",
            "conclusion": "板块发生变化。",
            "evidence": [{"summary": "同日触发", "accepted": True}],
            "representative_stocks": [row],
            "confirm_conditions": ["继续扩散"],
            "invalidation_conditions": ["代表股背离"],
            "valid_until": "2026-07-18T10:30:00+08:00",
        }
        gates = evaluate_gates(card, business_path="single_stock_event", environment_gate={"g5_result": "support"}, overall_quality="usable", ended=False)
        self.assertEqual(next(item for item in gates if item["gate_id"] == "G3")["state"], "partial")

    def test_explicit_source_conflict_blocks_representative_gate(self) -> None:
        row = stock("sh600001", "甲", "核心")
        row.update({"stock_quote_verification": "两路行情存在差异", "cross_source_verified": False})
        gates = evaluate_gates(
            {"theme": "测试主题", "triggered_at": "2026-07-18T09:35:00+08:00", "representative_stocks": [row]},
            business_path="single_stock_event",
            environment_gate={"g5_result": "support"},
            overall_quality="usable",
            ended=False,
        )
        self.assertEqual(next(item for item in gates if item["gate_id"] == "G3")["state"], "fail")


if __name__ == "__main__":
    unittest.main()

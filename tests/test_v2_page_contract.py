from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class V2PageContractTests(unittest.TestCase):
    def test_required_decision_containers_are_hard_required(self) -> None:
        html = (ROOT / "v2.html").read_text(encoding="utf-8")
        ids = set(re.findall(r'id="([^"]+)"', html))
        required = {
            "data-quality-gate",
            "market-environment",
            "opportunity-risk-radar",
            "validation-queue",
            "portfolio-risk",
            "signal-review",
            "stock-pool",
            "stock-pool-search",
            "governance-status",
            "source-manager",
            "blogger-source-form",
            "blogger-source-list",
            "parallel-operation",
            "parallel-comparison",
            "portfolio-manager",
            "portfolio-settings-form",
            "portfolio-holding-form",
        }
        self.assertTrue(required.issubset(ids))

    def test_radar_precedes_secondary_modules(self) -> None:
        html = (ROOT / "v2.html").read_text(encoding="utf-8")
        self.assertLess(html.index('id="opportunity-risk-radar"'), html.index('id="style-map"'))
        self.assertLess(html.index('id="opportunity-risk-radar"'), html.index('id="research-themes"'))

    def test_generated_data_is_shadow_only(self) -> None:
        data = json.loads((ROOT / "data" / "v2" / "decision-system.json").read_text(encoding="utf-8"))
        self.assertEqual(data["system"]["mode"], "shadow_only")
        self.assertFalse(data["system"]["production_behavior_changed"])

    def test_opportunity_filter_uses_kind_and_waiting_uses_state(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn('data-radar-kind="${escapeHtml(kind)}"', code)
        self.assertIn('data-radar-state="${escapeHtml(card.state)}"', code)
        self.assertIn('activeRadarFilter === "waiting" && waiting', code)

    def test_stock_pool_search_is_wired(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn('id="stock-pool-search"', (ROOT / "v2.html").read_text(encoding="utf-8"))
        self.assertIn('input.addEventListener("input"', code)

    def test_research_templates_render_evidence_and_mapping_gap(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn("template_ready_mapping_gap", code)
        self.assertIn("tracking_indicators", code)
        self.assertIn("invalidation_conditions", code)

    def test_market_environment_renders_two_sided_counts_and_cross_market(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn("sentiment.limit_up_count", code)
        self.assertIn("sentiment.limit_down_count", code)
        self.assertIn("cross_market", code)
        self.assertIn("涨停与跌停梯队", code)
        self.assertIn("high_level_loss_effect", code)
        self.assertIn("时点或清洗规则不同，不直接比较", code)
        self.assertIn("sourceLink(sentiment.source)", code)

    def test_local_input_privacy_status_is_visible(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn("inputStatus?.privacy_note", code)
        self.assertIn("renderGovernance(data.governance || {}, data.input_status || {})", code)

    def test_model_evaluation_is_visible_and_non_automatic(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn("model?.baseline_version", code)
        self.assertIn("model?.automatic_live_promotion", code)
        self.assertIn("renderReview(data.signal_review || {}, data.model_evaluation || {})", code)

    def test_blogger_sources_are_managed_without_backend_commands(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn('/_v2-blogger-accounts', code)
        self.assertIn('data-source-action="delete"', code)
        self.assertIn('data-source-action="toggle"', code)
        self.assertIn("bindBloggerManager()", code)

    def test_parallel_comparison_is_visible_and_non_automatic(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn("renderParallelComparison", code)
        self.assertIn("继续并行", code)
        self.assertIn("renderParallelComparison(data.parallel_comparison || {})", code)

    def test_private_portfolio_manager_does_not_grant_trading(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn('/_v2-portfolio', code)
        self.assertIn("不代表当前市值或盈亏", code)
        self.assertIn("交易授权：否", code)


if __name__ == "__main__":
    unittest.main()

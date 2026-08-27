from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class V2PageContractTests(unittest.TestCase):
    PAGE_FILES = [
        "v2.html", "v2-trading.html", "v2-premarket.html", "v2-radar.html",
        "v2-midday.html", "v2-postmarket.html", "v2-evening.html", "v2-market.html",
        "v2-research.html", "v2-stock-pool.html", "v2-review.html", "v2-system.html",
        "v2-governance.html", "v2-logic.html",
    ]

    def test_required_decision_containers_exist_across_module_pages(self) -> None:
        pages = {name: (ROOT / name).read_text(encoding="utf-8") for name in self.PAGE_FILES}
        ids = set(re.findall(r'id="([^"]+)"', "\n".join(pages.values())))
        required = {
            "data-quality-gate",
            "market-environment",
            "opportunity-risk-radar",
            "opportunity-history",
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
            "watchlist-sync-shadow",
            "stock-pool-v22",
            "user-asset-layer",
            "formal-observation-layer",
            "temporary-candidate-layer",
            "cockpit-user-assets",
            "cockpit-phase-title",
            "cockpit-phase-view",
            "market-environment-v22",
            "market-environment-v22-summary",
            "market-environment-v22-decision",
            "market-sentiment-v22",
            "market-environment-v22-dimensions",
            "market-environment-v22-sources",
            "style-regime-v22",
            "cross-market-v22",
            "v22-learning-summary",
            "industry-tracking-summary",
            "industry-tracking-cards",
            "logic-search",
            "logic-category-filter",
            "logic-result-summary",
            "logic-catalog",
        }
        self.assertTrue(required.issubset(ids))
        self.assertNotIn('id="opportunity-risk-radar"', pages["v2.html"])
        self.assertNotIn("数据决策门", pages["v2.html"])
        self.assertNotIn("当前决策案例", pages["v2.html"])
        self.assertIn('href="v2-trading.html"', pages["v2.html"])
        self.assertIn('href="v2-research.html"', pages["v2.html"])
        self.assertIn('href="v2-stock-pool.html"', pages["v2.html"])
        self.assertIn('href="v2-review.html"', pages["v2.html"])
        self.assertIn('href="v2-system.html"', pages["v2.html"])
        self.assertNotIn('href="v2-radar.html"', pages["v2.html"])
        self.assertNotIn('href="v2-market.html"', pages["v2.html"])
        self.assertNotIn('href="v2-logic.html"', pages["v2.html"])

    def test_result_pages_use_trader_language_instead_of_engineering_terms(self) -> None:
        result_pages = [
            "v2.html", "v2-trading.html", "v2-premarket.html", "v2-radar.html",
            "v2-midday.html", "v2-postmarket.html", "v2-evening.html", "v2-market.html",
            "v2-research.html", "v2-stock-pool.html", "v2-review.html",
        ]
        forbidden = (
            "决策就绪", "环境门禁", "候选投影", "影子模式", "数据血缘",
            "规则口径", "mainline_structure_snapshot", "external_market_snapshot",
        )
        for page_name in result_pages:
            page = (ROOT / page_name).read_text(encoding="utf-8")
            for term in forbidden:
                self.assertNotIn(term, page, f"{page_name} should not expose {term}")

    def test_result_pages_hide_data_quality_badge_and_use_honest_quote_copy(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn('window.location.pathname.endsWith("/v2-governance.html")', code)
        self.assertIn("status.hidden = true", code)
        self.assertIn("这个时段没有保存可核验的代表股行情，因此不展示涨跌幅。", code)
        self.assertNotIn("当日代表股行情尚未形成，不生成可操作结论。", code)
        self.assertIn("cockpitPhaseEvidence(mainline.evidence, 5)", code)

    def test_radar_has_its_own_decision_page(self) -> None:
        html = (ROOT / "v2-radar.html").read_text(encoding="utf-8")
        self.assertIn('id="opportunity-risk-radar"', html)
        self.assertIn('id="validation-queue"', html)
        self.assertIn('id="cockpit-phase-view"', html)
        self.assertIn('class="trading-nav"', html)
        self.assertIn('id="intraday-market-overview"', html)
        self.assertIn('data-session-key="intraday"', html)
        self.assertIn("盘中异动", html)
        for hidden_from_cockpit in (
            'id="data-quality-gate"', 'id="v2-status"', 'id="v2-updated"',
            'id="v2-refresh-status"', 'id="v22-case-projection-note"',
            'id="v22-clue-explanation"', "查看阶段切换逻辑",
            "查看判断方法", ">数据状态<", ">判断方法<",
        ):
            self.assertNotIn(hidden_from_cockpit, html)
        self.assertNotIn('id="research-themes"', html)
        self.assertNotIn('id="stock-pool"', html)

    def test_global_and_daily_navigation_match_the_approved_architecture(self) -> None:
        global_pages = ["v2.html", "v2-trading.html", "v2-research.html", "v2-stock-pool.html", "v2-review.html", "v2-system.html"]
        global_labels = ["交易系统", "产业研究", "股票池", "复盘学习", "系统说明"]
        for name in global_pages:
            html = (ROOT / name).read_text(encoding="utf-8")
            nav = re.search(r'<nav class="v2-nav global-nav"[^>]*>(.*?)</nav>', html, re.S)
            self.assertIsNotNone(nav, name)
            labels = re.findall(r'<a[^>]*>(.*?)</a>', nav.group(1), re.S)
            labels = [re.sub(r"<[^>]+>", "", label).strip() for label in labels]
            self.assertEqual(labels[:5], global_labels, name)
            self.assertNotIn("市场环境", labels, name)
        daily_pages = ["v2-trading.html", "v2-premarket.html", "v2-radar.html", "v2-midday.html", "v2-postmarket.html", "v2-evening.html", "v2-market.html"]
        daily_labels = ["今日", "盘前预案", "盘中异动", "午盘判断", "盘后复盘", "晚间舆情"]
        for name in daily_pages:
            html = (ROOT / name).read_text(encoding="utf-8")
            nav = re.search(r'<nav class="trading-nav"[^>]*>(.*?)</nav>', html, re.S)
            self.assertIsNotNone(nav, name)
            labels = re.findall(r'<a[^>]*>(.*?)</a>', nav.group(1), re.S)
            labels = [re.sub(r"<[^>]+>", "", label).strip() for label in labels]
            self.assertEqual(labels, daily_labels, name)
            self.assertNotIn("市场环境", labels, name)

    def test_v1_v2_entry_pages_are_fixed_by_port(self) -> None:
        pages = {name: (ROOT / name).read_text(encoding="utf-8") for name in self.PAGE_FILES}
        for name, html in pages.items():
            self.assertIn('href="http://127.0.0.1:8877/index.html">返回 V1</a>', html, name)
            self.assertNotIn('href="index.html">返回 V1</a>', html, name)
        v1_home = (ROOT / "index.html").read_text(encoding="utf-8")
        server = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('href="http://127.0.0.1:8878/v2.html"', v1_home)
        self.assertIn('server_port", None) == 8878', server)
        self.assertIn('requested_path in {"/", "/index.html"}', server)
        self.assertIn('self.send_redirect("/v2.html")', server)
        self.assertIn('self.send_header("Cache-Control", "no-store, max-age=0")', server)

    def test_cockpit_phase_switch_is_server_governed_and_user_facing(self) -> None:
        page = (ROOT / "v2-radar.html").read_text(encoding="utf-8")
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        server = (ROOT / "server.py").read_text(encoding="utf-8")
        payload = json.loads((ROOT / "data/v2/v22/cockpit-phase-view.json").read_text(encoding="utf-8"))
        self.assertIn('/_v2-cockpit-phase', code)
        self.assertIn("renderCockpitPhaseView", code)
        self.assertIn("旧预案不会作为今天的操作依据", code)
        self.assertIn('self.path.startswith("/_v2-cockpit-phase")', server)
        function_start = code.index("function applyV22MarketPageCurrentView")
        self.assertLess(
            code.index("if (marketTarget) {", function_start),
            code.index('if (!document.getElementById("market-environment-v22")) return;', function_start),
        )
        self.assertEqual(payload["mode"], "shadow_only")
        self.assertFalse(payload["guardrails"]["automatic_trading"])
        self.assertFalse(payload["guardrails"]["user_assets_modified"])
        for forbidden in ("availability", "stage", "source_as_of", "stale_data_used_as_current"):
            self.assertNotIn(forbidden, page)

    def test_generated_data_is_shadow_only(self) -> None:
        data = json.loads((ROOT / "data" / "v2" / "decision-system.json").read_text(encoding="utf-8"))
        self.assertEqual(data["system"]["mode"], "shadow_only")
        self.assertFalse(data["system"]["production_behavior_changed"])

    def test_opportunity_filter_uses_kind_and_waiting_uses_state(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn('data-radar-kind="${escapeHtml(kind)}"', code)
        self.assertIn('data-radar-state="${escapeHtml(card.state)}"', code)
        self.assertIn('activeRadarFilter === "waiting" && waiting', code)

    def test_current_fact_time_and_missing_numbers_are_user_facing(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn("function hasFiniteNumber(value)", code)
        self.assertIn('setText("home-evidence-time", compactTime(v22MarketEnvironment.as_of', code)
        self.assertIn('if (!hasFiniteNumber(data.change_pct)) return "";', code)
        self.assertIn('const pct = `${Number(data.change_pct).toFixed(2)}%`;', code)
        self.assertNotIn('Number.isFinite(Number(data.change_pct))', code)
        self.assertNotIn("数值待核验", code)
        self.assertIn("尚未设定有效观察时间，只能继续观察", code)

    def test_stock_pool_search_is_wired(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn('id="stock-pool-search"', (ROOT / "v2-stock-pool.html").read_text(encoding="utf-8"))
        self.assertIn('input.addEventListener("input"', code)

    def test_v22_stock_pool_layers_are_user_facing_and_read_only(self) -> None:
        page = (ROOT / "v2-stock-pool.html").read_text(encoding="utf-8")
        radar = (ROOT / "v2-radar.html").read_text(encoding="utf-8")
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        catalog = json.loads((ROOT / "data/v2/logic-catalog.json").read_text(encoding="utf-8"))
        self.assertIn("我的关注、正式观察与系统发现", page)
        self.assertIn("查看股票池规则", page)
        self.assertIn("优先展示", radar)
        self.assertNotIn("身份不绕过交易门禁", radar)
        self.assertIn("系统发现，尚未加入我的关注", code)
        self.assertIn("用户自选的来源优先级与删除规则", {item["title"] for item in catalog["entries"]})
        for forbidden in ("watchlist_source", "analysis_state", "source_identity_hash", "user_watchlist_asset"):
            self.assertNotIn(forbidden, page)
            self.assertNotIn(forbidden, radar)

    def test_light_cream_visual_system_is_declared(self) -> None:
        css = (ROOT / "v2.css").read_text(encoding="utf-8")
        self.assertIn("color-scheme: light", css)
        self.assertIn("--bg: #f3eee4", css)
        self.assertIn(".portal-grid", css)
        self.assertIn(".market-sentiment-card", css)
        self.assertIn(".environment-dimension-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));", css)
        self.assertNotIn(".environment-dimension-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));", css)

    def test_research_page_shows_results_and_logic_catalog_keeps_methods(self) -> None:
        page = (ROOT / "v2-research.html").read_text(encoding="utf-8")
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        catalog = json.loads((ROOT / "data/v2/logic-catalog.json").read_text(encoding="utf-8"))
        self.assertIn("template_ready_mapping_gap", code)
        self.assertIn("行业持续跟踪", page)
        self.assertIn("renderIndustryTracking", code)
        self.assertIn("V22_INDUSTRY_TRACKING_URL", code)
        self.assertIn("查看研究方法", page)
        self.assertNotIn("长期主题与核验框架", page)
        titles = {item["title"] for item in catalog["entries"]}
        self.assertIn("核聚变研究逻辑", titles)
        self.assertIn("量子科技研究逻辑", titles)

    def test_market_environment_renders_two_sided_counts_and_cross_market(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn("sentiment.limit_up_count", code)
        self.assertIn("sentiment.limit_down_count", code)
        self.assertIn("cross_market", code)
        self.assertIn("涨停与跌停梯队", code)
        self.assertIn("high_level_loss_effect", code)
        self.assertNotIn("时点或清洗规则不同，不直接比较", code)
        self.assertIn("sourceLink(sentiment.source)", code)

    def test_v22_market_environment_is_fact_only_and_user_facing(self) -> None:
        page = (ROOT / "v2-market.html").read_text(encoding="utf-8")
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        payload = json.loads((ROOT / "data/v2/v22/market-environment.json").read_text(encoding="utf-8"))
        self.assertIn("四个交易视角", page)
        self.assertIn('id="intraday-market-overview"', page)
        self.assertIn('class="module-card environment-shadow-card market-detail-drawer"', page)
        self.assertIn("展开详细依据", page)
        self.assertIn("先看结论和应对", page)
        self.assertNotIn("八维市场环境", page)
        self.assertNotIn("不替换当前机会状态", page)
        self.assertIn("renderEnvironmentV22", code)
        self.assertIn("代表股表现", code)
        self.assertIn("什么情况可能看错", code)
        self.assertIn("applyV22MarketPageCurrentView", code)
        self.assertIn("当前收盘环境", code)
        self.assertIn("当前市场环境", code)
        self.assertIn("市场情绪判断", code)
        self.assertIn("renderMarketSentimentV22", code)
        self.assertIn('id="market-sentiment-v22"', page)
        self.assertNotIn('id="data-quality-gate"', page)
        self.assertNotIn('id="market-environment"', page)
        self.assertIn("老登、中登、小登与微盘", page)
        self.assertNotIn("风格池只用于环境判断，不等于股票池", page)
        self.assertEqual(len(payload["dimensions"]), 8)
        self.assertTrue(payload["facts_only"])
        self.assertFalse(payload["guardrails"]["current_v2_action_modified"])
        for forbidden in ("dimension_code", "quality_state", "freshness_state", "environment_snapshot_id"):
            self.assertNotIn(forbidden, page)

    def test_v22_environment_decision_and_g5_are_user_facing_shadow_results(self) -> None:
        page = (ROOT / "v2-market.html").read_text(encoding="utf-8")
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        payload = json.loads((ROOT / "data/v2/v22/environment-decision.json").read_text(encoding="utf-8"))
        self.assertIn("查看风格与外盘影响", page)
        self.assertIn("renderEnvironmentDecisionV22", code)
        self.assertIn("renderEnvironmentGate", code)
        self.assertIn("<strong>大盘是否支持</strong>", code)
        self.assertNotIn("<strong>环境门禁</strong>", code)
        self.assertIn("function crossMarketTradeView(item)", code)
        self.assertIn('signal: "风险"', code)
        self.assertIn("先回避，不抄底", code)
        self.assertEqual(payload["mode"], "shadow_only")
        self.assertIn(payload["primary_state"], {"risk_release", "repair", "rotation_trial", "mainline_confirmed", "diffusion_strengthening", "crowding_divergence", "retreat"})
        self.assertFalse(payload["guardrails"]["user_assets_modified"])
        self.assertFalse(payload["guardrails"]["g5_bypasses_other_gates"])
        for forbidden in ("primary_state", "transmission_state", "g5_result", "user_assets_modified"):
            self.assertNotIn(forbidden, page)

    def test_v22_decision_cases_replace_noise_without_exposing_gate_fields(self) -> None:
        home = (ROOT / "v2.html").read_text(encoding="utf-8")
        radar = (ROOT / "v2-radar.html").read_text(encoding="utf-8")
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertNotIn("当前决策案例", home)
        self.assertNotIn("正在读取当前结果", home)
        self.assertNotIn("正在读取当前判断", radar)
        self.assertIn("renderDecisionCandidateV22", code)
        self.assertIn("证据不足的方向只保留观察", code)
        self.assertNotIn("为什么仍在等待", code)
        self.assertNotIn("未成卡线索", code)
        self.assertNotIn("盘中状态只在交易驾驶舱维护", code)
        for forbidden in ("case_batch_id", "gate_id", "g5_result", "quality_state", "valid_until"):
            self.assertNotIn(forbidden, home)
            self.assertNotIn(forbidden, radar)

    def test_v22_learning_page_withholds_hit_rate_and_cutover(self) -> None:
        review = (ROOT / "v2-review.html").read_text(encoding="utf-8")
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn("案例结果", review)
        self.assertIn("查看回溯方法", review)
        self.assertIn("renderV22Learning", code)
        self.assertIn("当前结论：继续观察", code)
        self.assertIn("已记录当时行情", code)
        self.assertNotIn("只有同交易日、近触发时点行情完整时才新增", code)
        for forbidden in ("state_hash", "trigger_snapshot_id", "evaluation_included", "quote_trade_date_mismatch"):
            self.assertNotIn(forbidden, review)

    def test_local_input_privacy_status_is_visible(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn("inputStatus?.privacy_note", code)
        self.assertIn("renderGovernance(data.governance || {}, data.input_status || {})", code)

    def test_model_evaluation_page_only_shows_results(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        catalog = json.loads((ROOT / "data/v2/logic-catalog.json").read_text(encoding="utf-8"))
        self.assertNotIn("当前规则基线", code)
        self.assertNotIn("model?.automatic_live_promotion", code)
        self.assertIn("模型离线评价与晋升边界", {item["title"] for item in catalog["entries"]})
        self.assertIn("renderReview(data.signal_review || {}, data.model_evaluation || {})", code)

    def test_logic_is_centralized_in_searchable_catalog(self) -> None:
        logic_page = (ROOT / "v2-logic.html").read_text(encoding="utf-8")
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        catalog = json.loads((ROOT / "data/v2/logic-catalog.json").read_text(encoding="utf-8"))
        self.assertIn('id="logic-search"', logic_page)
        self.assertIn('id="logic-category-filter"', logic_page)
        self.assertIn("renderLogicCatalog", code)
        self.assertIn("logicSearchText", code)
        self.assertGreaterEqual(len(catalog["entries"]), 18)
        self.assertEqual(len(catalog["categories"]), 7)
        required_titles = {
            "机会进入交易驾驶舱前的八项检查",
            "盘前预案与盘中验证切换",
            "八维市场环境模型",
            "老登、中登、小登与微盘定义",
            "股票体系的五层边界",
            "回溯快照与结果窗口",
            "数据时点、缺失和冲突处理",
        }
        self.assertTrue(required_titles.issubset({item["title"] for item in catalog["entries"]}))

    def test_blogger_sources_are_managed_without_backend_commands(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn('/_v2-blogger-accounts', code)
        self.assertIn('data-source-action="delete"', code)
        self.assertIn('data-source-action="toggle"', code)
        self.assertIn("bindBloggerManager()", code)

    def test_parallel_comparison_is_visible_and_non_automatic(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn("renderParallelComparison", code)
        self.assertIn("继续观察", code)
        self.assertIn(".filter(item => !/质量问题|自动化|价格复核|仅V1|仅V2/.test", code)
        self.assertNotIn("质量 ${escapeHtml", code)
        self.assertNotIn("自动化 ${escapeHtml", code)
        self.assertIn("renderParallelComparison(data.parallel_comparison || {})", code)

    def test_private_portfolio_manager_does_not_grant_trading(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn('/_v2-portfolio', code)
        self.assertIn("不代表当前市值或盈亏", code)
        self.assertIn("交易授权：否", code)

    def test_p0_frontend_uses_auditable_stock_quote_and_refreshes_radar(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn("stock_change_pct", code)
        self.assertIn("stock_quote_as_of", code)
        self.assertIn("stock_quote_source", code)
        self.assertIn("stockCodeLabel", code)
        self.assertIn("stock_code", code)
        self.assertIn("行情待补，不用于当前判断", code)
        self.assertNotIn("item.change_pct", code)
        self.assertIn("setInterval", code)
        self.assertIn("visibilitychange", code)
        self.assertIn("重新聚焦更新", code)
        self.assertIn("30秒自动更新", code)
        self.assertIn("risk-invalidation-grid", code)
        radar = (ROOT / "v2-radar.html").read_text(encoding="utf-8")
        self.assertNotIn("stock_quote_as_of", radar)
        self.assertNotIn("stock_quote_source", radar)

    def test_p0_frontend_hides_technical_source_and_quality_terms(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn('replace(/\\bmonitor\\.log\\b/gi, "盘中异动监测记录")', code)
        self.assertIn('replace(/\\bdegraded\\b/gi, "部分信息待补")', code)

    def test_unknown_backend_state_is_not_echoed_to_users(self) -> None:
        code = (ROOT / "v2.js").read_text(encoding="utf-8")
        self.assertIn('return STATE_LABELS[value] || "状态待核验"', code)


if __name__ == "__main__":
    unittest.main()

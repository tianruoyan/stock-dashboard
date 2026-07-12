from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from v2_platform.research import V2ResearchSystemBuilder
from v2_platform.market_structure import V2MarketStructureBuilder
from v2_platform.governance import V2GovernanceBuilder


SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def text(value: Any, default: str = "") -> str:
    return str(value).strip() if value not in (None, "") else default


def parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


def newest_time(values: Iterable[Any]) -> str | None:
    parsed = [item for value in values if (item := parse_time(value))]
    return max(parsed).isoformat() if parsed else None


def oldest_time(values: Iterable[Any]) -> str | None:
    parsed = [item for value in values if (item := parse_time(value))]
    return min(parsed).isoformat() if parsed else None


@dataclass
class LoadedSource:
    name: str
    path: Path
    data: dict[str, Any]
    status: str
    error: str | None

    @property
    def timestamp(self) -> str | None:
        value = self.data.get("timestamp")
        return str(value) if value else None

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path.name),
            "status": self.status,
            "timestamp": self.timestamp,
            "error": self.error,
        }


class V2DecisionSystemBuilder:
    SOURCE_FILES = {
        "premarket": "premarket.json",
        "intraday": "intraday.json",
        "midday": "midday.json",
        "postmarket": "postmarket.json",
        "evening": "evening-sentiment.json",
        "alert": "alert.json",
        "opportunity_watch": "opportunity-watch.json",
        "decision_feed": "decision-feed.json",
        "theme_shifts": "theme-shifts.json",
        "quality": "quality-report.json",
        "trust": "data-trust.json",
        "automation": "automation-health.json",
        "section_health": "section-health.json",
        "source_health": "source-health.json",
        "topics": "topics.json",
        "signal_review": "signal-review.json",
        "v2_signal_review": "v2/signal-review.json",
        "v2_sentiment_structure": "v2/inputs/sentiment-structure.json",
        "v2_input_import": "v2/input-import-manifest.json",
        "v2_model_evaluation": "v2/model-evaluation.json",
        "v2_public_input_health": "v2/public-input-health.json",
    }

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.data_dir = self.root / "data"
        self.sources = {
            name: self._load(name, self.data_dir / filename)
            for name, filename in self.SOURCE_FILES.items()
        }
        self.watchlist = self._load_config("watchlist.json")
        self.alert_config = self._load_config("alert-config.json")
        self.topic_config = self._load_config("topics-list.json")
        self.style_taxonomy = self._load_config("v2-style-taxonomy.json")
        self.model_registry = self._load_config("v2-model-registry.json")

    def build(self) -> dict[str, Any]:
        quality = self._quality_gate()
        environment = self._market_environment(quality)
        radar, validation = self._radar(quality)
        market_structure = V2MarketStructureBuilder(self.root).build()
        style = self._style_map(market_structure)
        research = self._research_themes()
        research_library, stock_pool = V2ResearchSystemBuilder(self.root).build()
        governance = V2GovernanceBuilder(self.root).build()
        portfolio = self._portfolio_risk()
        signal_review = self._signal_review()
        input_status = self._input_status()
        model_evaluation = self._model_evaluation()
        timestamps = [source.timestamp for source in self.sources.values() if source.timestamp]
        critical_timestamps = [
            self.sources[name].timestamp
            for name in ("intraday", "alert", "decision_feed", "quality", "trust")
            if self.sources[name].timestamp
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "system": {
                "name": "AI辅助投资决策系统",
                "version": "V2.0-shadow",
                "decision_model_version": text(as_dict(self.model_registry.get("baseline")).get("version"), "unversioned"),
                "mode": "shadow_only",
                "generated_at": now_iso(),
                "latest_source_at": newest_time(timestamps),
                "decision_as_of": oldest_time(critical_timestamps),
                "production_behavior_changed": False,
                "disclaimer": "仅作研究辅助，不构成个性化投资建议或自动交易指令。",
            },
            "data_quality_gate": quality,
            "market_environment": environment,
            "opportunity_radar": radar,
            "validation_queue": validation,
            "style_map": style,
            "market_structure": market_structure,
            "portfolio_risk": portfolio,
            "research_themes": research,
            "research_library": research_library,
            "stock_pool": stock_pool,
            "governance": governance,
            "signal_review": signal_review,
            "input_status": input_status,
            "model_evaluation": model_evaluation,
            "source_registry": [source.summary() for source in self.sources.values()],
        }

    def _load(self, name: str, path: Path) -> LoadedSource:
        if not path.exists():
            return LoadedSource(name, path, {}, "missing", "file_missing")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return LoadedSource(name, path, {}, "invalid", f"{type(exc).__name__}: {exc}")
        if not isinstance(value, dict):
            return LoadedSource(name, path, {}, "invalid", "top_level_not_object")
        return LoadedSource(name, path, value, "loaded", None)

    def _load_config(self, filename: str) -> dict[str, Any]:
        path = self.root / "config" / filename
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    def _quality_gate(self) -> dict[str, Any]:
        quality = self.sources["quality"].data
        trust = self.sources["trust"].data
        automation = self.sources["automation"].data
        raw_statuses = [
            text(quality.get("status"), "missing"),
            text(trust.get("overall_status"), "missing"),
            text(automation.get("overall_status"), "missing"),
        ]
        if any(item in {"critical", "blocked", "invalid", "missing"} for item in raw_statuses):
            state = "blocked"
        elif any(item in {"degraded", "late", "stale"} for item in raw_statuses):
            state = "degraded"
        else:
            state = "usable"
        counts = as_dict(quality.get("counts"))
        issues = []
        for item in as_list(quality.get("action_plan"))[:6]:
            if not isinstance(item, dict):
                continue
            issues.append(
                {
                    "level": text(item.get("impact_level"), text(item.get("priority"), "review")),
                    "problem": text(item.get("problem"), text(item.get("label"), "数据需复核")),
                    "next_step": text(item.get("next_step"), text(item.get("decision_action"), "等待核验")),
                    "source": text(item.get("file"), "quality-report.json"),
                }
            )
        blocking = int(counts.get("blocking") or counts.get("critical") or 0)
        return {
            "state": state,
            "headline": text(quality.get("summary"), "数据质量状态不可用"),
            "decision_rule": (
                "关键数据阻断：不得生成已确认机会。"
                if state == "blocked"
                else (
                    "数据降级：只允许候选和风险提示，已确认机会必须等待关键证据恢复。"
                    if state == "degraded"
                    else "关键数据可用，但仍需遵守每条机会的确认与失效条件。"
                )
            ),
            "blocking_count": blocking,
            "price_review_count": int(counts.get("price_review") or 0),
            "signal_review_count": int(counts.get("signal_review") or 0),
            "background_review_count": int(counts.get("background_review") or 0),
            "issues": issues,
            "evidence": [
                {"label": "质量审计", "source": "quality-report.json", "as_of": self.sources["quality"].timestamp},
                {"label": "文件可信", "source": "data-trust.json", "as_of": self.sources["trust"].timestamp},
                {"label": "任务健康", "source": "automation-health.json", "as_of": self.sources["automation"].timestamp},
            ],
        }

    def _market_environment(self, quality: dict[str, Any]) -> dict[str, Any]:
        feed = self.sources["decision_feed"].data
        brief = as_dict(feed.get("decision_brief"))
        intraday = self.sources["intraday"].data
        premarket = self.sources["premarket"].data
        postmarket = self.sources["postmarket"].data
        sentiment = as_dict(intraday.get("sentiment"))
        structure_source = self.sources["v2_sentiment_structure"]
        structure_input = structure_source.data if structure_source.status == "loaded" and parse_time(structure_source.data.get("as_of")) else {}
        index_rows = []
        for item in as_list(intraday.get("indices")):
            if isinstance(item, dict):
                index_rows.append(
                    {
                        "name": text(item.get("name"), text(item.get("code"), "指数")),
                        "pct": item.get("pct"),
                        "three_min_pct": item.get("three_min_pct"),
                        "status": text(item.get("status"), "unknown"),
                        "as_of": self.sources["intraday"].timestamp,
                    }
                )
        global_evidence = []
        us = as_dict(premarket.get("us_overnight"))
        if us:
            global_evidence.append(
                {
                    "market": "US",
                    "conclusion": text(us.get("conclusion"), text(us.get("impact_to_a_share"), "未形成结论")),
                    "mapping": as_list(us.get("mapping_chain")),
                    "as_of": self.sources["premarket"].timestamp,
                }
            )
        hk = as_dict(intraday.get("hk_market")) or as_dict(postmarket.get("hk_close_review"))
        if hk:
            global_evidence.append(
                {
                    "market": "HK",
                    "conclusion": text(hk.get("judgement"), text(hk.get("summary"), "未形成结论")),
                    "mapping": as_list(hk.get("impact")),
                    "as_of": self.sources["intraday"].timestamp or self.sources["postmarket"].timestamp,
                }
            )
        japan_korea = as_dict(us.get("japan_korea"))
        if japan_korea:
            global_evidence.append(
                {
                    "market": "KR",
                    "conclusion": text(japan_korea.get("summary"), "韩国市场没有形成可用结论"),
                    "mapping": [],
                    "watch": [text(value) for value in as_list(japan_korea.get("watch")) if text(value)],
                    "quality_state": text(japan_korea.get("source_status"), "missing"),
                    "actionability": "background_only" if japan_korea.get("pending_confirmation") else "verify_mapping",
                    "as_of": self.sources["premarket"].timestamp,
                }
            )
        limit_up_ladder = as_dict(structure_input.get("limit_up_ladder")) or as_dict(sentiment.get("limit_up_ladder"))
        limit_down_ladder = as_dict(structure_input.get("limit_down_ladder")) or as_dict(sentiment.get("limit_down_ladder"))
        return {
            "state": text(brief.get("stance"), "无法判断"),
            "action": text(brief.get("action"), "等待数据确认"),
            "headline": text(intraday.get("summary"), text(feed.get("summary"), "当前没有可用市场结论")),
            "quality_state": quality["state"],
            "supporting_reasons": [text(item) for item in as_list(brief.get("reasons")) if text(item)][:5],
            "risk_constraints": [text(item) for item in as_list(brief.get("risk_focus")) if text(item)][:5],
            "indices": index_rows,
            "sentiment_structure": {
                "limit_up_count": sentiment.get("limit_up_count", intraday.get("limit_up_count")),
                "limit_down_count": sentiment.get("limit_down_count", intraday.get("limit_down_count")),
                "broken_limit_count": sentiment.get("broken_limit_count"),
                "judgement": text(sentiment.get("judgement"), "情绪结构待核验"),
                "limit_up_ladder": limit_up_ladder or {
                    "state": "data_missing",
                    "items": [],
                    "note": "已有涨停总数和炸板数，但缺少可审计的连板高度、梯队和晋级率。",
                },
                "limit_down_ladder": limit_down_ladder or {
                    "state": "data_missing",
                    "items": [],
                    "note": "已有跌停总数，但缺少可审计的连续跌停、开板失败和风险扩散梯队。",
                },
                "promotion_rate": structure_input.get("promotion_rate", sentiment.get("promotion_rate")),
                "high_level_loss_effect": structure_input.get("high_level_loss_effect") or sentiment.get("high_level_loss_effect") or {
                    "state": "data_missing",
                    "note": "缺少昨日高位股/连板股次日收益与最大不利波动，暂不判断高位亏钱效应。",
                },
                "as_of": structure_input.get("as_of") or self.sources["intraday"].timestamp,
                "source": structure_input.get("source_url") or "intraday.json",
                "ladder_input_state": "loaded" if structure_input else "pending",
            },
            "cross_market": global_evidence,
        }

    def _radar(self, quality: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        cards: list[dict[str, Any]] = []
        for alert in as_list(self.sources["alert"].data.get("alerts")):
            if isinstance(alert, dict):
                cards.append(self._alert_card(alert, quality))

        feed = self.sources["decision_feed"].data
        for section in ("risks", "opportunities", "verifications"):
            for item in as_list(feed.get(section)):
                if isinstance(item, dict):
                    cards.append(self._feed_card(item, section, quality))

        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for card in cards:
            key = (card["kind"], card["title"].replace("待触发：", "").replace("盘中追踪：", ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(card)
        priority = {"confirmed": 0, "candidate": 1, "risk": 2, "waiting": 3, "invalidated": 4}
        deduped.sort(key=lambda item: (priority.get(item["state"], 9), item["title"]))

        queue = []
        watch = self.sources["opportunity_watch"].data
        for item in as_list(watch.get("items")):
            if not isinstance(item, dict):
                continue
            queue.append(
                {
                    "id": stable_id("validation", item.get("id"), item.get("source_phase")),
                    "theme": text(item.get("theme"), text(item.get("id"), "未命名方向")),
                    "status": text(item.get("status"), "waiting"),
                    "why_watch": text(item.get("source_reason"), "等待盘中规则触发"),
                    "representative_stocks": [text(value) for value in as_list(item.get("watch_stocks")) if text(value)],
                    "confirm_conditions": [text(value) for value in as_list(item.get("confirm_rules")) if text(value)],
                    "invalidation_conditions": [text(value) for value in as_list(item.get("invalidate_rules")) if text(value)],
                    "evidence": as_list(item.get("evidence")),
                    "source": "opportunity-watch.json",
                    "as_of": self.sources["opportunity_watch"].timestamp,
                }
            )
        return deduped[:16], queue[:16]

    def _alert_card(self, alert: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
        kind = text(alert.get("alert_class"), "opportunity")
        confirmation = text(alert.get("confirmation_level"), "candidate")
        quote = as_dict(alert.get("quote_audit"))
        sanity = as_dict(quote.get("sanity_checks"))
        cross_verified = sanity.get("cross_source_verified") is True
        if confirmation == "invalidated":
            state = "invalidated"
        elif kind == "risk":
            state = "risk"
        elif confirmation == "confirmed" and cross_verified and quality["state"] == "usable":
            state = "confirmed"
        else:
            state = "candidate"
        if state == "confirmed":
            action = "积极关注；只按确认条件执行，失效立即降级。"
        elif kind == "risk":
            action = "降低关注，等待风险收敛；未核验前不抄底。"
        else:
            action = "等待确认，不追；缺少双源或扩散证据时保持候选。"
        leaders = []
        for value in as_list(alert.get("leaders")):
            if isinstance(value, dict):
                leaders.append(
                    {
                        "name": text(value.get("name"), "未知标的"),
                        "change_pct": value.get("change_pct"),
                        "role": text(value.get("role"), "代表股"),
                    }
                )
        evidence = [
            {
                "type": "trigger",
                "summary": text(alert.get("reason"), "未提供触发依据"),
                "source": "alert.json",
                "as_of": text(alert.get("time"), self.sources["alert"].timestamp or ""),
            }
        ]
        if quote:
            evidence.append(
                {
                    "type": "quote_audit",
                    "summary": f"来源 {text(quote.get('provider'), '未知')}；样本 {quote.get('sample_count', '未知')}；交叉验证 {'通过' if cross_verified else '未通过'}",
                    "source": text(quote.get("provider"), "alert.quote_audit"),
                    "as_of": text(quote.get("quote_time"), ""),
                }
            )
        counter = []
        if not cross_verified:
            counter.append("交叉行情验证未通过，不能升级为已确认机会。")
        if quality["state"] != "usable":
            counter.append(f"全局数据状态为{quality['state']}，行动性结论降级。")
        return {
            "id": text(alert.get("id"), stable_id("alert", alert.get("sector"), alert.get("time"))),
            "kind": kind,
            "state": state,
            "title": text(alert.get("sector"), text(alert.get("type"), "盘中信号")),
            "trigger": text(alert.get("type"), "盘中异动"),
            "conclusion": text(alert.get("reason"), "等待原因核验"),
            "action": action,
            "representative_stocks": leaders,
            "evidence": evidence,
            "counter_evidence": counter,
            "confirm_conditions": ["关键行情交叉验证通过", "代表股与板块扩散同向", "在有效时间窗内保持触发"],
            "invalidation_conditions": ["超过有效期", "代表股与板块背离", "触发方向快速反转"],
            "valid_until": alert.get("valid_until"),
            "quality_state": "usable" if cross_verified else "degraded",
            "source": "alert.json",
        }

    def _feed_card(self, item: dict[str, Any], section: str, quality: dict[str, Any]) -> dict[str, Any]:
        kind = "risk" if section == "risks" else "opportunity"
        evidence_values = [text(value) for value in as_list(item.get("evidence")) if text(value)]
        missing = [text(value) for value in as_list(item.get("missing_evidence")) if text(value)]
        independent = item.get("independent_observation") is True
        trackable = text(item.get("use_action")) == "可跟踪"
        if kind == "risk":
            state = "risk"
        elif independent and evidence_values and not missing and trackable and quality["state"] == "usable":
            state = "confirmed"
        else:
            state = "waiting"
        action = (
            text(item.get("next_action"), "降低关注，等待风险收敛")
            if kind == "risk"
            else text(item.get("next_action"), "等待确认，不追")
        )
        source_files = as_list(item.get("source_files"))
        evidence_as_of = self._source_files_timestamp(source_files) or self.sources["decision_feed"].timestamp
        return {
            "id": stable_id("decision", item.get("title"), section, item.get("discovery_type")),
            "kind": kind,
            "state": state,
            "title": text(item.get("title"), "未命名判断"),
            "trigger": text(item.get("trigger_reason"), "未提供触发原因"),
            "conclusion": text(item.get("conclusion"), "无法判断"),
            "action": action,
            "representative_stocks": [],
            "evidence": [
                {
                    "type": "decision_evidence",
                    "summary": value,
                    "source": ", ".join(str(source) for source in source_files),
                    "as_of": evidence_as_of,
                }
                for value in evidence_values[:6]
            ],
            "counter_evidence": missing + [text(value) for value in as_list(item.get("quality_flags")) if text(value)],
            "confirm_conditions": [text(value) for value in as_list(item.get("watch_next")) if text(value)],
            "invalidation_conditions": [text(item.get("invalidation"), "未提供失效条件")],
            "valid_until": None,
            "quality_state": "degraded" if quality["state"] != "usable" or missing else "usable",
            "source": ", ".join(str(source) for source in source_files) or "decision-feed.json",
        }

    def _source_files_timestamp(self, source_files: list[Any]) -> str | None:
        names = {Path(str(value)).name for value in source_files}
        timestamps = [source.timestamp for source in self.sources.values() if source.path.name in names and source.timestamp]
        return newest_time(timestamps)

    def _style_map(self, market_structure: dict[str, Any]) -> dict[str, Any]:
        shifts = []
        raw_shifts = as_list(self.sources["theme_shifts"].data.get("shifts"))
        for item in raw_shifts:
            if not isinstance(item, dict):
                continue
            shifts.append(
                {
                    "theme": text(item.get("theme"), "未命名风格"),
                    "state": text(item.get("state"), "unknown"),
                    "conclusion": text(item.get("conclusion"), "无法判断"),
                    "evidence": [text(value) for value in as_list(item.get("evidence")) if text(value)][:6],
                    "watch_next": [text(value) for value in as_list(item.get("watch_next")) if text(value)][:4],
                    "risk": text(item.get("risk"), ""),
                    "stocks": [text(value) for value in as_list(item.get("stocks")) if text(value)][:8],
                    "quality_flags": [text(value) for value in as_list(item.get("quality_flags")) if text(value)],
                }
            )
        taxonomy = as_dict(self.style_taxonomy.get("dimensions"))
        definition_version = text(self.style_taxonomy.get("definition_version"), "unversioned")
        source_refs = [
            {
                "type": text(item.get("type"), "unknown"),
                "title": text(item.get("title"), "未命名来源"),
                "url": text(item.get("url"), "") or None,
                "retrieved_at": text(item.get("retrieved_at"), "") or None,
            }
            for item in as_list(self.style_taxonomy.get("sources"))
            if isinstance(item, dict)
        ]

        def dimension(style_id: str, default_label: str) -> dict[str, Any]:
            config = as_dict(taxonomy.get(style_id))
            keywords = [text(value).lower() for value in as_list(config.get("theme_keywords")) if text(value)]
            matched = [
                item for item in shifts
                if any(keyword in f"{item['theme']} {item['conclusion']}".lower() for keyword in keywords)
            ]
            if style_id == "microcap":
                proxy = as_dict(config.get("proxy"))
                observed_proxy = as_dict(market_structure.get("proxy"))
                return {
                    "id": style_id,
                    "label": text(config.get("label"), default_label),
                    "state": text(market_structure.get("state"), text(proxy.get("status"), "data_missing")),
                    "direction": text(market_structure.get("direction"), "unknown"),
                    "definition": text(config.get("definition"), "独立市值与流动性维度"),
                    "representative_sectors": as_list(config.get("representative_sectors")),
                    "conclusion": text(market_structure.get("conclusion"), "已配置中证2000作为观察代理；当前缺少带时间戳的可审计行情，暂不判断方向。"),
                    "proxy": {
                        "name": text(observed_proxy.get("name"), text(proxy.get("name"), "中证2000指数")),
                        "code": text(observed_proxy.get("code"), text(proxy.get("code"), "932000")),
                        "scope_note": text(observed_proxy.get("scope_note"), text(proxy.get("scope_note"), "指数代理不等于纯微盘。")),
                    },
                    "matched_themes": [],
                    "definition_version": definition_version,
                }
            return {
                "id": style_id,
                "label": text(config.get("label"), default_label),
                "state": "observed_by_themes" if matched else "not_observed",
                "direction": "mixed" if matched else "unknown",
                "definition": text(config.get("definition"), "定义待核验"),
                "representative_sectors": as_list(config.get("representative_sectors")),
                "conclusion": (
                    "；".join(item["conclusion"] for item in matched[:2])
                    if matched else "当前主题变化数据未形成该风格的可审计结论。"
                ),
                "matched_themes": [item["theme"] for item in matched[:6]],
                "definition_version": definition_version,
            }

        return {
            "dimensions": [
                dimension("old_deng", "老登"),
                dimension("middle_deng", "中登"),
                dimension("small_deng", "小登"),
                dimension("microcap", "微盘"),
            ],
            "theme_shifts": shifts,
            "as_of": self.sources["theme_shifts"].timestamp,
            "definition_version": definition_version,
            "governance_note": text(self.style_taxonomy.get("governance_note"), "市场俗称，按版本管理。"),
            "source_refs": source_refs,
        }

    def _portfolio_risk(self) -> dict[str, Any]:
        rules = as_dict(self.alert_config.get("july_portfolio_risk"))
        return {
            "state": "rules_only",
            "headline": "已加载风控规则，但未接入真实持仓和成本，不能生成个性化仓位动作。",
            "position_limits": as_dict(rules.get("position_limits")),
            "stop_loss": as_dict(rules.get("stop_loss")),
            "sector_drawdown": as_dict(rules.get("sector_drawdown")),
            "missing_inputs": ["真实持仓数量", "持仓成本", "可用现金", "用户风险预算"],
        }

    def _research_themes(self) -> list[dict[str, Any]]:
        rows = []
        for item in as_list(self.sources["topics"].data.get("topics")):
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "id": stable_id("theme", item.get("name")),
                    "name": text(item.get("name"), "未命名专题"),
                    "status": text(item.get("status"), "待更新"),
                    "conclusion": text(item.get("conclusion"), text(item.get("note"), "暂无结论")),
                    "action": text(item.get("action"), "等待更新"),
                    "related_topics": [text(value) for value in as_list(item.get("related_topics")) if text(value)],
                    "updated_at": item.get("updated_at") or self.sources["topics"].timestamp,
                }
            )
        return rows

    def _signal_review(self) -> dict[str, Any]:
        source = self.sources["v2_signal_review"] if self.sources["v2_signal_review"].status == "loaded" else self.sources["signal_review"]
        if source.status != "loaded":
            return {
                "state": "unavailable",
                "headline": "尚无统一信号复盘文件；当前只保留运行与判断快照，暂不展示命中率。",
                "windows": ["T+1", "T+3", "T+5", "T+10"],
                "items": [],
            }
        return {
            "state": text(source.data.get("status"), "available"),
            "headline": text(source.data.get("summary"), "信号复盘已加载"),
            "windows": as_list(source.data.get("windows")) or ["T+1", "T+3", "T+5", "T+10"],
            "items": as_list(source.data.get("items")),
            "snapshot_count": int(source.data.get("snapshot_count") or 0),
            "pending_signal_count": int(source.data.get("pending_signal_count") or 0),
            "evaluated_signal_count": int(source.data.get("evaluated_signal_count") or 0),
            "hit_rate": source.data.get("hit_rate"),
            "hit_rate_state": text(source.data.get("hit_rate_state"), "unavailable"),
            "guardrail": text(source.data.get("guardrail"), "样本不足不展示命中率。"),
            "workflow": as_list(source.data.get("workflow")),
        }

    def _input_status(self) -> dict[str, Any]:
        source = self.sources["v2_input_import"]
        public_health = self.sources["v2_public_input_health"]
        collectors = []
        if public_health.status == "loaded":
            for item in as_list(public_health.data.get("collectors")):
                if isinstance(item, dict):
                    collectors.append({"id": text(item.get("id"), "unknown"), "state": text(item.get("state"), "unknown"), "detail": text(item.get("detail"), "")})
        if source.status != "loaded":
            return {
                "state": "not_run",
                "contracts": [],
                "public_collectors": collectors,
                "updated_at": None,
                "privacy_note": "持仓保存在本地私有区；原始输入和授权行情不进入公开发布提交。",
            }
        rows = []
        for item in as_list(source.data.get("contracts")):
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "id": text(item.get("id"), "unknown"),
                    "status": text(item.get("status"), "unknown"),
                    "detail": text(item.get("detail"), ""),
                    "target": text(item.get("target"), ""),
                }
            )
        return {
            "state": text(source.data.get("status"), "unknown"),
            "contracts": rows,
            "public_collectors": collectors,
            "updated_at": source.data.get("imported_at"),
            "privacy_note": "持仓保存在本地私有区；原始输入和授权行情不进入公开发布提交。",
        }

    def _model_evaluation(self) -> dict[str, Any]:
        source = self.sources["v2_model_evaluation"]
        baseline = text(as_dict(self.model_registry.get("baseline")).get("version"), "unversioned")
        if source.status != "loaded":
            return {
                "state": "not_run",
                "baseline_version": baseline,
                "record_count": 0,
                "recommendation": {"action": "keep_baseline", "reason": "尚未运行离线模型评估。", "requires_user_confirmation": True},
                "automatic_live_promotion": False,
            }
        promotion = as_dict(source.data.get("promotion_policy"))
        return {
            "state": text(source.data.get("state"), "unknown"),
            "baseline_version": text(source.data.get("baseline_version"), baseline),
            "primary_window": source.data.get("primary_window"),
            "record_count": int(source.data.get("record_count") or 0),
            "version_summaries": as_list(source.data.get("version_summaries")),
            "comparisons": as_list(source.data.get("comparisons")),
            "recommendation": as_dict(source.data.get("recommendation")),
            "data_gaps": as_list(source.data.get("data_gaps")),
            "automatic_live_promotion": bool(promotion.get("automatic_live_promotion", False)),
        }

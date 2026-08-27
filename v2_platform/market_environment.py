from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2_platform.environment_evidence import (
    canonical_hash,
    dimension_state,
    evidence_ref,
    infer_session_phase,
    newest_time,
    normalize_quote_time,
    parse_datetime,
    same_metric_conflicts,
    stable_id,
    trade_date_of,
)
from v2_platform.style_regime import V22StyleRegimeBuilder


PUBLIC_OUTPUT = "data/v2/v22/market-environment.json"
SNAPSHOT_INDEX = "data/v2/v22/environment-snapshot-index.json"
PRESENTATION_VERSION = "plain-language-2026-07-23.3"
DIMENSION_LABELS = {
    "index_structure": "主要指数",
    "liquidity": "成交是否活跃",
    "market_breadth": "上涨与下跌家数",
    "mainline_structure": "主线是否明确",
    "sentiment_structure": "涨停与跌停表现",
    "style_structure": "老登、中登、小登表现",
    "position_fragility": "高位股风险",
    "external_constraint": "外盘影响",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def first_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw.split(" ; ", 1)[0] if raw else None


def file_hash(path: Path) -> str | None:
    try:
        return canonical_hash(path.read_text(encoding="utf-8"))
    except OSError:
        return None


class V22MarketEnvironmentBuilder:
    def __init__(self, root: Path, *, built_at: datetime | None = None) -> None:
        self.root = root.resolve()
        resolved = built_at or datetime.now(timezone.utc).astimezone()
        if resolved.tzinfo is None:
            raise ValueError("built_at must include timezone")
        self.built_at = resolved
        self.policy = load_json(self.root / "config/v2-market-environment-policy.json")
        self.price_rules = load_json(self.root / "config/v2-price-limit-rules.json")
        self.paths = {
            "decision": self.root / "data/v2/decision-system.json",
            "intraday": self.root / "data/intraday.json",
            "sentiment": self.root / "data/v2/inputs/sentiment-structure.json",
            "market_structure": self.root / "data/v2/market-structure.json",
            "breadth": self.root / "data/v2/inputs/market-breadth.json",
            "liquidity": self.root / "data/v2/inputs/market-liquidity.json",
            "mainline": self.root / "data/v2/inputs/mainline-structure.json",
            "external": self.root / "data/v2/inputs/external-market.json",
            "style_quotes": self.root / "data/v2/inputs/representative-stock-quotes.json",
            "style_baskets": self.root / "config/v2-style-baskets.json",
            "theme_shifts": self.root / "data/theme-shifts.json",
            "quality": self.root / "data/quality-report.json",
        }
        self.sources = {name: load_json(path) for name, path in self.paths.items()}

    def _decision_trade_date(self) -> str | None:
        sentiment = self.sources["sentiment"]
        structure = self.sources["market_structure"]
        selected = structure.get("selected_observation") if isinstance(structure.get("selected_observation"), dict) else {}
        explicit = [
            sentiment.get("trade_date"),
            self.sources["breadth"].get("trade_date"),
            self.sources["liquidity"].get("trade_date"),
            self.sources["mainline"].get("trade_date"),
            self.sources["external"].get("trade_date"),
            trade_date_of(selected.get("as_of")),
        ]
        dates = [str(value) for value in explicit if value]
        if dates:
            # 交易日管线允许部分维度在来源失败时保留上一有效值。当前环境应锚定
            # 最新已取得的交易日，再让各维度分别标记“同日可用/等待更新”；
            # 不能由多份旧缓存以数量优势把整张环境快照拉回前一交易日。
            return max(dates)
        fallback = newest_time([
            normalize_quote_time(item.get("quote_time"))
            for item in as_list(self.sources["intraday"].get("indices"))
            if isinstance(item, dict)
        ])
        return trade_date_of(fallback)

    def _candidate_times(self, trade_date: str) -> list[str]:
        sentiment = self.sources["sentiment"]
        structure = self.sources["market_structure"]
        selected = structure.get("selected_observation") if isinstance(structure.get("selected_observation"), dict) else {}
        values = [
            sentiment.get("as_of"),
            selected.get("as_of"),
            self.sources["breadth"].get("as_of"),
            self.sources["liquidity"].get("as_of"),
            self.sources["mainline"].get("as_of"),
        ]
        values.extend([
            normalize_quote_time(item.get("quote_time"))
            for item in as_list(self.sources["intraday"].get("indices"))
            if isinstance(item, dict)
        ])
        current = [str(value) for value in values if parse_datetime(value) and trade_date_of(value) == trade_date]
        if not current:
            values.extend([
                self.sources["intraday"].get("timestamp"),
                self.sources["theme_shifts"].get("timestamp"),
            ])
            current = [str(value) for value in values if parse_datetime(value) and trade_date_of(value) == trade_date]
        return current

    def _source_hashes(self) -> dict[str, str | None]:
        return {name: file_hash(path) for name, path in self.paths.items()}

    def build(self) -> dict[str, Any]:
        trade_date = self._decision_trade_date() or self.built_at.date().isoformat()
        candidate_times = self._candidate_times(trade_date)
        snapshot_as_of = newest_time(candidate_times)
        if not snapshot_as_of:
            snapshot_as_of = self.built_at.isoformat(timespec="seconds")
        session_phase = infer_session_phase(snapshot_as_of)
        policy_version = str(self.policy.get("version") or "unversioned")
        source_hashes = self._source_hashes()
        snapshot_id = stable_id(
            "environment",
            trade_date,
            session_phase,
            snapshot_as_of,
            policy_version,
            canonical_hash(source_hashes),
            PRESENTATION_VERSION,
        )
        evidence: list[dict[str, Any]] = []
        dimensions = [
            self._index_dimension(snapshot_id, trade_date, snapshot_as_of, policy_version, evidence),
            self._liquidity_dimension(snapshot_id, trade_date, snapshot_as_of, policy_version, evidence),
            self._breadth_dimension(snapshot_id, trade_date, snapshot_as_of, policy_version, evidence),
            self._mainline_dimension(snapshot_id, trade_date, snapshot_as_of, policy_version, evidence),
            self._sentiment_dimension(snapshot_id, trade_date, snapshot_as_of, policy_version, evidence),
            self._style_dimension(snapshot_id, trade_date, snapshot_as_of, policy_version, evidence),
            self._position_dimension(snapshot_id, trade_date, snapshot_as_of, policy_version, evidence),
            self._external_dimension(snapshot_id, trade_date, snapshot_as_of, policy_version, evidence),
        ]
        conflicts = same_metric_conflicts(evidence)
        promotion = self.sources["sentiment"].get("promotion_rate")
        if isinstance(promotion, dict) and promotion.get("state") == "degraded_response_date_unverified":
            conflicts.append({
                "conflict_id": stable_id("env_conflict", snapshot_id, "promotion_date"),
                "dimension_code": "sentiment_structure",
                "metric_name": "晋级日期",
                "source_as_of": self.sources["sentiment"].get("as_of"),
                "values": promotion.get("quality_flags") or [],
                "resolution": "晋级率不参与任何正向判断。",
            })
        support_counts = Counter(str(item.get("support_level") or "unknown") for item in dimensions)
        quality_counts = Counter(str(item.get("quality_state") or "unknown") for item in dimensions)
        reliable_risk = [
            item for item in dimensions
            if item.get("support_level") in {"suppress", "risk_release"}
            and item.get("quality_state") in {"usable", "degraded"}
        ]
        positive = [item for item in dimensions if item.get("support_level") == "support" and item.get("quality_state") == "usable"]
        unknown = [item for item in dimensions if item.get("support_level") == "unknown"]
        sentiment_view = self._sentiment_user_view(dimensions, snapshot_as_of)
        if reliable_risk:
            headline = "高位股和外盘仍偏弱，先防守"
            if unknown:
                unknown_labels = [str(item.get("label") or item.get("dimension_code")) for item in unknown]
                liquidity = next((item for item in unknown if item.get("dimension_code") == "liquidity"), {})
                liquidity_facts = [str(value) for value in as_list(liquidity.get("fact_summary")) if value]
                if len(unknown) == 1 and liquidity:
                    turnover = liquidity_facts[0] if liquidity_facts else "全市场成交额已经取得"
                    conclusion = f"高位股回落，外盘相关方向也偏弱；{turnover.rstrip('。')}。由于没有可比的上一交易日成交额，暂时无法判断今天是放量还是缩量。当前不适合追高。"
                else:
                    conclusion = f"高位股回落，外盘相关方向也偏弱；{'、'.join(unknown_labels)}还没有更新完整。当前不适合追高。"
                action = "先防守，等高位股止跌、代表股转强、上涨家数增加"
            else:
                headline = "多项表现一起转弱，先防守"
                conclusion = "上涨家数、主线、高位股和外盘多项偏弱；即使成交放大，也更可能是抛压释放，不是机会确认。"
                action = "不追高，等上涨家数、核心代表股和外盘影响一起改善"
        elif len(positive) >= int((self.policy.get("positive_conclusion_rules") or {}).get("minimum_independent_dimensions") or 3) and not unknown:
            headline = "市场多项表现一起转强"
            conclusion = "主要指数、上涨家数和主线表现互相支持，市场正在转强，但仍需代表股连续确认。"
            action = "关注已经确认的机会，不追没有代表股承接的后排"
        else:
            headline = "强弱信号互相矛盾，先观察"
            conclusion = "主要指数、上涨家数、主线和高位股没有形成一致方向，暂时不适合提高进攻力度。"
            action = "等待至少两项关键表现转为同向，再决定是否行动"
        overall_quality = "blocked" if any(item.get("quality_state") == "blocked" for item in dimensions) else ("degraded" if unknown or conflicts or quality_counts.get("degraded") else "usable")
        source_cutoff = newest_time([item.get("source_as_of") for item in evidence]) or snapshot_as_of
        source_status = self._source_status(trade_date)
        payload: dict[str, Any] = {
            "schema_version": 1,
            "mode": "shadow_only",
            "facts_only": True,
            "environment_snapshot_id": snapshot_id,
            "trade_date": trade_date,
            "session_phase": session_phase,
            "as_of": snapshot_as_of,
            "built_at": self.built_at.isoformat(timespec="seconds"),
            "source_cutoff_at": source_cutoff,
            "policy_version": policy_version,
            "presentation_version": PRESENTATION_VERSION,
            "price_limit_rule_version": self.price_rules.get("version"),
            "primary_state": "等待市场状态判断",
            "state_changed": False,
            "action_constraint": action,
            "quality_state": overall_quality,
            "quality_summary": f"八维中可用{quality_counts.get('usable', 0)}项、降级{quality_counts.get('degraded', 0)}项、未知{quality_counts.get('unknown', 0)}项；冲突{len(conflicts)}项。",
            "headline": headline,
            "conclusion": conclusion,
            "dimension_summary": {
                "total": len(dimensions),
                "support": support_counts.get("support", 0),
                "partial_support": support_counts.get("partial_support", 0),
                "neutral": support_counts.get("neutral", 0),
                "suppress": support_counts.get("suppress", 0),
                "risk_release": support_counts.get("risk_release", 0),
                "unknown": support_counts.get("unknown", 0),
            },
            "dimensions": dimensions,
            "sentiment_view": sentiment_view,
            "evidence_refs": evidence,
            "conflicts": conflicts,
            "source_status": source_status,
            "source_content_hashes": source_hashes,
            "user_view": {
                "标题": headline,
                "当前判断": conclusion,
                "当前允许": action,
                "行情时点": snapshot_as_of,
                "交易日": trade_date,
                "阶段": {"pre_market": "盘前", "auction": "竞价后", "morning": "上午", "midday": "午盘", "afternoon": "下午", "close": "收盘", "evening_plan": "晚间预案"}.get(session_phase, "时点待核验"),
                "支持项": support_counts.get("support", 0) + support_counts.get("partial_support", 0),
                "抑制项": support_counts.get("suppress", 0) + support_counts.get("risk_release", 0),
                "待补项": support_counts.get("unknown", 0),
                "冲突项": len(conflicts),
                "说明": "这是V2.2事实层影子对照，不替换当前V2行动结论。"
            },
            "guardrails": {
                "current_v2_action_modified": False,
                "environment_state_machine_enabled": False,
                "automatic_trading": False,
                "user_assets_modified": False,
                "model_promoted": False,
                "v1_modified": False,
                "mixed_trade_dates_used_as_current": False,
                "missing_facts_ai_filled": False,
            },
        }
        immutable_material = {key: value for key, value in payload.items() if key not in {"built_at", "immutable_hash"}}
        payload["immutable_hash"] = canonical_hash(immutable_material)
        return payload

    @staticmethod
    def _sentiment_user_view(dimensions: list[dict[str, Any]], as_of: str) -> dict[str, Any]:
        rows = {str(item.get("dimension_code") or ""): item for item in dimensions}
        sentiment = rows.get("sentiment_structure", {})
        breadth = rows.get("market_breadth", {})
        position = rows.get("position_fragility", {})
        index = rows.get("index_structure", {})

        def level(item: dict[str, Any]) -> str:
            return str(item.get("support_level") or "unknown")

        def first_fact(item: dict[str, Any]) -> str:
            facts = [str(value) for value in as_list(item.get("fact_summary")) if value]
            return facts[0] if facts else str(item.get("conclusion") or "证据待补。")

        def user_state(item: dict[str, Any]) -> str:
            return {
                "support": "偏强",
                "partial_support": "部分改善",
                "neutral": "好坏参半",
                "suppress": "偏弱",
                "risk_release": "仍在释放风险",
                "unknown": "数据不完整",
            }.get(level(item), "还需确认")

        sentiment_risk = level(sentiment) in {"suppress", "risk_release"}
        breadth_risk = level(breadth) in {"suppress", "risk_release"}
        position_risk = level(position) in {"suppress", "risk_release"}
        index_support = level(index) in {"support", "partial_support"}
        sentiment_support = level(sentiment) in {"support", "partial_support"}
        breadth_support = level(breadth) in {"support", "partial_support"}

        risk_signal_count = sum((sentiment_risk, breadth_risk, position_risk))

        if level(sentiment) == "unknown" and level(breadth) == "unknown":
            status = "unknown"
            headline = "暂时看不清强弱"
            judgment = "涨停、跌停、上涨家数和高位股表现还没收集完整，暂时不判断市场强弱。"
            action = "先等关键数据更新，不根据单个指数或少数股票行动"
        elif risk_signal_count >= 2:
            status = "risk"
            headline = "亏钱效应还没有结束"
            judgment = (
                "指数虽然上涨，但多数股票或高位股仍偏弱。不要把指数上涨理解为赚钱效应已经恢复。"
                if index_support else
                "下跌股票仍然偏多，高位股也有明显回落风险。即使少数强势股上涨，市场里的亏钱效应仍没有结束。"
            )
            action = "先不追高，等跌停减少、上涨家数增加、高位股不再连续回落"
        elif sentiment_support and breadth_support and not position_risk:
            status = "positive"
            headline = "赚钱效应正在回升"
            judgment = "上涨股票增多、涨停股持续走强，高位股没有明显补跌，市场赚钱效应正在回升。"
            action = "可以关注已经确认的机会，但仍要检查板块是否扩散、代表股是否有承接"
        elif sentiment_support or breadth_support:
            status = "repair"
            if sentiment_support and breadth_support:
                headline = "普涨了，但追高风险还在"
                judgment = "上涨股票和涨停表现都在改善，但高位股仍有明显回落。市场在修复，追高风险还没有解除。"
                action = "先看高位股跌幅和炸板是否减少；没有改善前，不追高"
            elif breadth_support:
                headline = "上涨股票增多，但强势股还不稳"
                judgment = "上涨股票明显增多，但强势股能否继续上涨、高位股回落时是否有人接盘还没有确认。多数股票在修复，追高仍容易亏钱。"
                action = "先看涨停股能否继续走强、炸板是否减少、高位股是否止跌；没有改善前，只观察、不追高"
            else:
                headline = "强势股在走强，但多数股票还没跟上"
                judgment = "涨停和强势股数量在增加，但上涨还没有扩散到多数股票。赚钱效应集中在少数前排，追后排容易被套。"
                action = "先看上涨家数是否继续增加、后排是否跟上；只有少数前排走强时，不追后排"
        else:
            status = "neutral"
            headline = "涨跌不一致，先观察"
            judgment = "涨停股、上涨家数和高位股表现互相矛盾，暂时看不出一致方向。"
            action = "先观察，不因为指数上涨或少数强股走强就追高"

        counter = first_fact(index) if index_support and (sentiment_risk or breadth_risk or position_risk) else None
        return {
            "status": status,
            "headline": headline,
            "judgment": judgment,
            "action": action,
            "as_of": as_of,
            "counter_evidence": counter,
            "drivers": [
                {"label": "涨停与跌停表现", "state": user_state(sentiment), "evidence": first_fact(sentiment)},
                {"label": "上涨与下跌家数", "state": user_state(breadth), "evidence": first_fact(breadth)},
                {"label": "高位股表现", "state": user_state(position), "evidence": first_fact(position)},
                {"label": "主要指数表现", "state": user_state(index), "evidence": first_fact(index)},
            ],
        }

    def _source_status(self, trade_date: str) -> list[dict[str, Any]]:
        result = []
        intraday_quote_time = newest_time([
            normalize_quote_time(item.get("quote_time"))
            for item in as_list(self.sources["intraday"].get("indices"))
            if isinstance(item, dict)
        ])
        source_times = {
            "盘中指数": intraday_quote_time or self.sources["intraday"].get("timestamp"),
            "涨跌停梯队": self.sources["sentiment"].get("as_of"),
            "小微盘宽基代理": (self.sources["market_structure"].get("selected_observation") or {}).get("as_of") if isinstance(self.sources["market_structure"].get("selected_observation"), dict) else None,
            "上涨与下跌家数": self.sources["breadth"].get("as_of"),
            "成交是否活跃": self.sources["liquidity"].get("as_of"),
            "主题线索": self.sources["theme_shifts"].get("timestamp"),
        }
        for label, value in source_times.items():
            parsed = parse_datetime(value)
            if not parsed:
                state = "missing"
                note = "尚未取得带时区的事实时点"
            elif parsed.date().isoformat() != trade_date:
                state = "stale"
                note = f"来源时点为{parsed.date().isoformat()}，未混入当前快照"
            else:
                state = "current"
                note = "与当前交易日一致"
            result.append({"label": label, "state": state, "as_of": value, "note": note})
        return result

    def _index_dimension(self, snapshot_id: str, trade_date: str, default_as_of: str, version: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        intraday = self.sources["intraday"]
        rows = [item for item in as_list(intraday.get("indices")) if isinstance(item, dict)]
        current = []
        for item in rows:
            quote_as_of = normalize_quote_time(item.get("quote_time")) or intraday.get("timestamp")
            if trade_date_of(quote_as_of) == trade_date and number(item.get("pct")) is not None:
                current.append((item, quote_as_of))
        refs = []
        if len(current) >= 3:
            changes = [number(item.get("pct")) or 0.0 for item, _ in current]
            positive_count = sum(value > 0 for value in changes)
            negative_count = sum(value < 0 for value in changes)
            level = "support" if positive_count >= 4 else ("suppress" if negative_count >= 4 else "neutral")
            conclusion = "主要指数多数上涨，指数整体偏强。" if level == "support" else ("主要指数多数下跌，指数整体偏弱。" if level == "suppress" else "主要指数涨跌不一，暂时没有一致方向。")
            for item, as_of in current:
                ref = evidence_ref(snapshot_id=snapshot_id, dimension_code="index_structure", evidence_role="support" if (number(item.get("pct")) or 0) >= 0 else "risk", metric_name=str(item.get("name") or "核心指数"), metric_scope="index", metric_value=number(item.get("pct")), unit="%", source_id=str(item.get("source") or "intraday_index_quote"), source_label=str(item.get("source") or "盘中指数行情"), source_url=None, source_as_of=str(as_of), quality_state="usable")
                evidence.append(ref); refs.append(ref["evidence_ref_id"])
            return dimension_state(snapshot_id=snapshot_id, dimension_code="index_structure", label=DIMENSION_LABELS["index_structure"], support_level=level, conclusion=conclusion, fact_summary=[f"观察的{len(current)}个主要指数中，{positive_count}个上涨、{negative_count}个下跌。"], counter_evidence=[], missing_evidence=[], quality_state="usable", freshness_state="current", as_of=newest_time([value for _, value in current]) or default_as_of, method_version=version, evidence_ref_ids=refs)
        stale_dates = sorted({trade_date_of(normalize_quote_time(item.get("quote_time")) or intraday.get("timestamp")) for item in rows} - {None, trade_date})
        return dimension_state(snapshot_id=snapshot_id, dimension_code="index_structure", label=DIMENSION_LABELS["index_structure"], support_level="unknown", conclusion="当天主要指数行情还没有更新完整，暂时不判断市场整体强弱。", fact_summary=[], counter_evidence=[f"现有指数行情停留在{'、'.join(stale_dates)}，不用于今天的判断。"] if stale_dates else [], missing_evidence=["上证、深证、创业板、科创50、沪深300当天的涨跌表现"], quality_state="unknown", freshness_state="stale" if stale_dates else "missing", as_of=default_as_of, method_version=version, evidence_ref_ids=[])

    def _liquidity_dimension(self, snapshot_id: str, trade_date: str, default_as_of: str, version: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        data = self.sources["liquidity"]
        as_of = data.get("as_of")
        if trade_date_of(as_of) != trade_date or number(data.get("total_turnover")) is None:
            return dimension_state(snapshot_id=snapshot_id, dimension_code="liquidity", label=DIMENSION_LABELS["liquidity"], support_level="unknown", conclusion="还没有当天成交额，暂时看不出资金是在进场还是离场。", fact_summary=[], counter_evidence=[], missing_evidence=["当天全市场成交额", "和上一交易日相同时点的比较", "资金是否集中在少数股票"], quality_state="unknown", freshness_state="missing", as_of=default_as_of, method_version=version, evidence_ref_ids=[])
        turnover = number(data.get("total_turnover"))
        change = number(data.get("turnover_change_pct"))
        concentration = number(data.get("top_concentration_pct"))
        breadth = self.sources["breadth"]
        advance = integer(breadth.get("advance_count"))
        decline = integer(breadth.get("decline_count"))
        if change is None or concentration is None:
            level, quality = "unknown", "degraded"
            conclusion = "全市场成交额有数据，但没有和上一交易日相同时点比较，也不知道资金是否集中在少数股票，暂时看不出有没有更多资金进场。"
        else:
            broad_decline = advance is not None and decline is not None and decline > advance * 1.5
            broad_advance = advance is not None and decline is not None and advance > decline * 1.5
            if change > 5 and broad_decline:
                level = "suppress"
            elif change > 5 and concentration < 30 and broad_advance:
                level = "support"
            else:
                level = "suppress" if change < -5 or concentration >= 45 else "neutral"
            quality = "usable"
            if change > 5 and broad_decline:
                conclusion = "成交额放大，但下跌股票明显更多，说明抛压在增加，不是资金进场做多。"
            elif level == "support":
                conclusion = "成交额放大、上涨股票增多，而且资金没有只集中在少数股票，说明资金参与正在扩大。"
            elif level == "suppress":
                conclusion = "成交额缩小、资金过度集中，或放量下跌，当前不支持追高。"
            else:
                conclusion = "成交额没有明显变强或变弱，暂时不能提供交易方向。"
        ref = evidence_ref(snapshot_id=snapshot_id, dimension_code="liquidity", evidence_role="support" if level == "support" else "risk" if level == "suppress" else "counter", metric_name="全市场成交额", metric_scope="market", metric_value=turnover, unit=str(data.get("unit") or "亿元"), source_id=str(data.get("source_id") or "market_liquidity_input"), source_label=str(data.get("source_name") or "市场流动性输入"), source_url=data.get("source_url"), source_as_of=str(as_of), quality_state=quality, rule_version=str(data.get("method_version") or data.get("comparison_method") or "unspecified"), scope_definition=str(data.get("scope") or "全市场"))
        evidence.append(ref)
        return dimension_state(snapshot_id=snapshot_id, dimension_code="liquidity", label=DIMENSION_LABELS["liquidity"], support_level=level, conclusion=conclusion, fact_summary=[f"全市场成交额{turnover:g}{data.get('unit') or '亿元'}。"], counter_evidence=[], missing_evidence=[] if quality == "usable" else ["和上一交易日相同时点的变化，以及资金是否集中在少数股票"], quality_state=quality, freshness_state="current", as_of=str(as_of), method_version=version, evidence_ref_ids=[ref["evidence_ref_id"]])

    def _breadth_dimension(self, snapshot_id: str, trade_date: str, default_as_of: str, version: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        data = self.sources["breadth"]
        as_of = data.get("as_of")
        advance, decline, flat = integer(data.get("advance_count")), integer(data.get("decline_count")), integer(data.get("flat_count"))
        if trade_date_of(as_of) != trade_date or None in {advance, decline, flat}:
            return dimension_state(snapshot_id=snapshot_id, dimension_code="market_breadth", label=DIMENSION_LABELS["market_breadth"], support_level="unknown", conclusion="上涨、下跌和平盘股票数量还没有更新完整，暂时不知道行情是多数股票一起变化，还是只有少数指数股在动。", fact_summary=[], counter_evidence=[], missing_evidence=["全部A股中的上涨数量", "全部A股中的下跌数量", "平盘数量", "统计包含哪些股票"], quality_state="unknown", freshness_state="missing", as_of=default_as_of, method_version=version, evidence_ref_ids=[])
        total = advance + decline + flat
        level = "support" if advance > decline * 1.5 else ("suppress" if decline > advance * 1.5 else "neutral")
        conclusion = "上涨股票明显多于下跌股票，多数股票正在修复。" if level == "support" else ("下跌股票明显多于上涨股票，多数股票仍在承压。" if level == "suppress" else "上涨和下跌股票数量接近，市场没有明显强弱方向。")
        input_quality = str(data.get("quality_state") or "usable")
        quality = "usable" if input_quality == "usable" else "degraded"
        ref = evidence_ref(snapshot_id=snapshot_id, dimension_code="market_breadth", evidence_role="support" if level == "support" else "risk" if level == "suppress" else "counter", metric_name="上涨下跌平盘家数", metric_scope="market", metric_value={"上涨": advance, "下跌": decline, "平盘": flat, "合计": total}, unit="家", source_id=str(data.get("source_id") or "market_breadth_input"), source_label=str(data.get("source_name") or "市场宽度输入"), source_url=data.get("source_url"), source_as_of=str(as_of), quality_state=quality, rule_version=str(data.get("universe_definition_id") or "missing"), scope_definition=str(data.get("scope") or "全量A股"))
        evidence.append(ref)
        missing = [] if quality == "usable" else ["上涨股票明显占多数，但具体数量仍需继续核对。"]
        return dimension_state(snapshot_id=snapshot_id, dimension_code="market_breadth", label=DIMENSION_LABELS["market_breadth"], support_level=level, conclusion=conclusion, fact_summary=[f"上涨{advance}家、下跌{decline}家、平盘{flat}家。"], counter_evidence=[], missing_evidence=missing, quality_state=quality, freshness_state="current", as_of=str(as_of), method_version=version, evidence_ref_ids=[ref["evidence_ref_id"]])

    def _mainline_dimension(self, snapshot_id: str, trade_date: str, default_as_of: str, version: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        data = self.sources["mainline"]
        as_of = data.get("as_of")
        themes = [item for item in as_list(data.get("themes")) if isinstance(item, dict)]
        if trade_date_of(as_of) == trade_date and themes:
            refs = []
            representatives = []
            for theme in themes:
                securities = [item for item in as_list(theme.get("representative_securities")) if isinstance(item, dict)]
                representatives.extend(securities)
                ref = evidence_ref(
                    snapshot_id=snapshot_id,
                    dimension_code="mainline_structure",
                    evidence_role="risk" if theme.get("state") == "risk" else "counter",
                    metric_name=f"{theme.get('theme') or '主题'}收盘结构",
                    metric_scope="theme",
                    metric_value=theme.get("conclusion") or theme.get("fact"),
                    unit=None,
                    source_id=str(data.get("source_id") or "mainline_structure_input"),
                    source_label=str(data.get("source_name") or "主线结构输入"),
                    source_url=data.get("source_url"),
                    source_as_of=str(as_of),
                    quality_state=str(data.get("quality_state") or "degraded"),
                    rule_version=str(data.get("method_version") or "close_mainline_v1"),
                    scope_definition=str(data.get("scope") or "收盘主题结构"),
                    representative_securities=securities,
                )
                evidence.append(ref)
                refs.append(ref["evidence_ref_id"])
            facts = [
                str(item.get("fact") or item.get("conclusion"))
                .replace("同口径", str(item.get("theme") or "该行业"))
                .replace("房地产开", "房地产开发")
                for item in themes
                if item.get("fact") or item.get("conclusion")
            ]
            counters = [
                str(value).replace(
                    "涨跌停数量集中不等于行业全部个股和成交同步。",
                    "某个行业涨停股多，不代表行业内多数股票都在上涨，也不代表成交额真的放大。",
                )
                for value in as_list(data.get("counter_evidence"))
                if value
            ]
            support_level = str(data.get("support_level") or "unknown")
            conclusion = (
                "多个行业的涨停股明显增多，但还要看行业内多数股票和成交额是否一起走强，主线尚未完全确认。"
                if support_level in {"support", "partial_support"} else
                "主线里的代表股和后排一起走弱，当前不适合追这条线。"
                if support_level in {"suppress", "risk_release"} else
                "各行业强弱不一，暂时没有明确主线。"
            )
            return dimension_state(
                snapshot_id=snapshot_id,
                dimension_code="mainline_structure",
                label=DIMENSION_LABELS["mainline_structure"],
                support_level=support_level,
                conclusion=conclusion,
                fact_summary=facts,
                counter_evidence=counters,
                missing_evidence=[
                    {
                        "完整行业上涨下跌宽度": "行业内多数股票是否一起上涨",
                        "行业成交额与历史基线": "行业成交额是否明显高于平时",
                        "核心、中军和后排的连续时点确认": "核心股、主力大市值股和后排股票能否持续一起走强",
                    }.get(str(value), str(value))
                    for value in as_list(data.get("missing_evidence"))
                    if value
                ],
                quality_state=str(data.get("quality_state") or "degraded"),
                freshness_state="current",
                as_of=str(as_of),
                method_version=version,
                evidence_ref_ids=refs,
            )
        shifts = self.sources["theme_shifts"]
        rows = [item for item in as_list(shifts.get("shifts")) if isinstance(item, dict)]
        as_of = shifts.get("timestamp")
        if trade_date_of(as_of) == trade_date and rows:
            states = Counter(str(item.get("state") or "unknown") for item in rows)
            fact = f"主题文件记录{len(rows)}条线索，其中风险{states.get('risk', 0)}条、拥挤{states.get('crowded', 0)}条。"
            return dimension_state(snapshot_id=snapshot_id, dimension_code="mainline_structure", label=DIMENSION_LABELS["mainline_structure"], support_level="unknown", conclusion="行业线索有更新，但代表股当天涨跌、板块地位和成交情况还不完整，暂时不能确认主线。", fact_summary=[fact], counter_evidence=["行业故事或旧评分不能代替核心股、主力大市值股和后排股票一起走强。"], missing_evidence=["代表股当天的真实行情", "核心股、主力大市值股和后排股票的板块地位", "行业内上涨股票数量和成交分布"], quality_state="degraded", freshness_state="current", as_of=str(as_of), method_version=version, evidence_ref_ids=[])
        return dimension_state(snapshot_id=snapshot_id, dimension_code="mainline_structure", label=DIMENSION_LABELS["mainline_structure"], support_level="unknown", conclusion="当天行业和代表股数据还没有更新，暂时看不出市场主线。", fact_summary=[], counter_evidence=[], missing_evidence=["核心股、主力大市值股和后排股票的涨跌、成交和扩散情况"], quality_state="unknown", freshness_state="missing", as_of=default_as_of, method_version=version, evidence_ref_ids=[])

    def _sentiment_dimension(self, snapshot_id: str, trade_date: str, default_as_of: str, version: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        data = self.sources["sentiment"]
        as_of = data.get("as_of")
        up = data.get("limit_up_ladder") if isinstance(data.get("limit_up_ladder"), dict) else {}
        down = data.get("limit_down_ladder") if isinstance(data.get("limit_down_ladder"), dict) else {}
        up_count = integer(up.get("filtered_count"))
        down_count = integer(down.get("filtered_count"))
        if trade_date_of(as_of) != trade_date or up_count is None or down_count is None:
            return dimension_state(snapshot_id=snapshot_id, dimension_code="sentiment_structure", label=DIMENSION_LABELS["sentiment_structure"], support_level="unknown", conclusion="当天涨停、跌停和强势股表现还没有更新完整，暂时看不清市场赚钱效应。", fact_summary=[], counter_evidence=[], missing_evidence=["当天各连板高度的涨停股", "当天连续跌停股", "炸板数量和高位股回落情况"], quality_state="unknown", freshness_state="missing", as_of=default_as_of, method_version=version, evidence_ref_ids=[])
        promotion = data.get("promotion_rate") if isinstance(data.get("promotion_rate"), dict) else {}
        high_level = data.get("high_level_loss_effect") if isinstance(data.get("high_level_loss_effect"), dict) else {}
        promotion_usable = promotion.get("state") == "usable"
        if down_count > max(20, up_count * 2):
            level = "suppress"
            conclusion = "跌停股明显多于涨停股，亏钱效应较强，当前不适合增加进攻。"
        elif up_count > max(20, down_count * 2) and promotion_usable:
            level = "support"
            conclusion = "涨停股明显多于跌停股，而且强势股能够继续走强，赚钱效应正在回升。"
        else:
            level = "neutral"
            conclusion = "涨停和跌停数量已有结果，但还不能确认强势股能否持续，先观察。"
        representatives = self._ladder_representatives(up, down, str(as_of), str(data.get("source_name") or "东方财富涨跌停股池"))
        refs = []
        for metric_name, value, role in (("过滤后涨停数", up_count, "support"), ("过滤后跌停数", down_count, "risk")):
            ref = evidence_ref(snapshot_id=snapshot_id, dimension_code="sentiment_structure", evidence_role=role, metric_name=metric_name, metric_scope="market", metric_value=value, unit="家", source_id="eastmoney_price_limit_pool", source_label=str(data.get("source_name") or "东方财富涨跌停股池"), source_url=first_url(data.get("source_url")), source_as_of=str(as_of), quality_state="usable", rule_version=str(self.price_rules.get("version") or "unversioned"), scope_definition=str(data.get("scope") or "沪深A股过滤池"), representative_securities=representatives)
            evidence.append(ref); refs.append(ref["evidence_ref_id"])
        missing = []
        if not promotion_usable:
            missing.append("强势股第二天能否继续走强的数据日期不一致，暂时不采用")
        if data.get("broken_limit_total") is None:
            missing.append("炸板总数还没有按相同范围统计")
        quality = "degraded" if missing or data.get("quality_flags") else "usable"
        counter = [f"过滤后仍有{up_count}家涨停，不能把风险理解为所有股票同向下跌。"] if level == "suppress" and up_count else []
        return dimension_state(snapshot_id=snapshot_id, dimension_code="sentiment_structure", label=DIMENSION_LABELS["sentiment_structure"], support_level=level, conclusion=conclusion, fact_summary=[f"涨停{up_count}只、跌停{down_count}只。", f"最高连板{self._highest_ladder(up)}板，最长连续跌停{self._highest_ladder(down)}天。"], counter_evidence=counter, missing_evidence=missing, quality_state=quality, freshness_state="current", as_of=str(as_of), method_version=version, evidence_ref_ids=refs)

    @staticmethod
    def _highest_ladder(value: dict[str, Any]) -> int:
        heights = [integer(item.get("height")) or 0 for item in as_list(value.get("items")) if isinstance(item, dict)]
        return max(heights, default=0)

    @staticmethod
    def _ladder_representatives(up: dict[str, Any], down: dict[str, Any], as_of: str, source: str | None) -> list[dict[str, Any]]:
        result = []
        for side, ladder in (("涨停梯队", up), ("跌停梯队", down)):
            rows = sorted((item for item in as_list(ladder.get("items")) if isinstance(item, dict)), key=lambda item: integer(item.get("height")) or 0, reverse=True)
            for stock in as_list(rows[0].get("stocks"))[:3] if rows else []:
                if not isinstance(stock, dict) or not stock.get("code") or not stock.get("name"):
                    continue
                result.append({"code": stock.get("code"), "name": stock.get("name"), "change_pct": stock.get("change_pct"), "as_of": as_of, "source": source or "东方财富涨跌停股池", "role": side})
        return result

    def _style_dimension(self, snapshot_id: str, trade_date: str, default_as_of: str, version: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        styles = V22StyleRegimeBuilder(self.root).build({"trade_date": trade_date, "dimensions": []})
        basket_rows = [item for item in styles if item.get("style_id") in {"old_deng", "middle_deng", "small_deng"}]
        complete_baskets = [item for item in basket_rows if item.get("quality_state") == "usable"]
        if len(complete_baskets) == 3:
            weak = [item for item in styles if item.get("price_state") == "weakening"]
            strong = [item for item in styles if item.get("price_state") == "strengthening"]
            level = "suppress" if len(weak) >= 3 else ("support" if len(strong) >= 3 else "neutral")
            refs = []
            for item in styles:
                ref = evidence_ref(
                    snapshot_id=snapshot_id,
                    dimension_code="style_structure",
                    evidence_role="risk" if item.get("price_state") == "weakening" else "support" if item.get("price_state") == "strengthening" else "counter",
                    metric_name=f"{item.get('label') or item.get('style_id')}篮子收盘结构",
                    metric_scope="style",
                    metric_value={"中位涨跌幅": item.get("median_change_pct"), "上涨比例": item.get("positive_ratio"), "下跌比例": item.get("negative_ratio")},
                    unit="%",
                    source_id="tencent_style_basket_quotes" if item.get("style_id") != "microcap" else "csi2000_proxy",
                    source_label="腾讯财经代表股行情" if item.get("style_id") != "microcap" else "中证2000小微盘宽基代理",
                    source_url=None,
                    source_as_of=str(item.get("as_of") or default_as_of),
                    quality_state=str(item.get("quality_state") or "degraded"),
                    rule_version=str(item.get("basket_version") or version),
                    scope_definition=str(item.get("construction") or item.get("label") or "风格篮子"),
                    representative_securities=as_list(item.get("representative_securities")),
                )
                evidence.append(ref)
                refs.append(ref["evidence_ref_id"])
            facts = [f"{item.get('label')}代表股涨跌幅中位数{float(item.get('median_change_pct')):+.2f}%。" for item in basket_rows if number(item.get("median_change_pct")) is not None]
            microcap = next((item for item in styles if item.get("style_id") == "microcap"), {})
            if number(microcap.get("median_change_pct")) is not None:
                facts.append(f"中证2000小微盘宽基代理涨跌幅{float(microcap.get('median_change_pct')):+.2f}%；不等于纯微盘或小登。")
            conclusion = (
                "老登、中登、小登代表股都在走弱，暂时没有可用于避险的强势方向。"
                if level == "suppress" else
                "老登、中登、小登代表股多数走强，但还要看市场情绪和主线是否配合。" if level == "support" else
                "老登、中登、小登代表股涨跌不一，暂时没有统一风格。"
            )
            return dimension_state(snapshot_id=snapshot_id, dimension_code="style_structure", label=DIMENSION_LABELS["style_structure"], support_level=level, conclusion=conclusion, fact_summary=facts, counter_evidence=["这些风格分类只用于观察市场，不会改变你的自选股。", "中证2000只能近似观察小微盘，不代表纯微盘，也不代表小登方向。"], missing_evidence=["纯微盘市场的正式数据"] if microcap.get("quality_state") != "usable" else [], quality_state="degraded" if microcap.get("quality_state") != "usable" else "usable", freshness_state="current", as_of=newest_time([item.get("as_of") for item in styles]) or default_as_of, method_version=version, evidence_ref_ids=refs)
        structure = self.sources["market_structure"]
        selected = structure.get("selected_observation") if isinstance(structure.get("selected_observation"), dict) else {}
        as_of = selected.get("as_of")
        if trade_date_of(as_of) == trade_date and selected.get("change_pct") is not None:
            value = number(selected.get("change_pct"))
            ref = evidence_ref(snapshot_id=snapshot_id, dimension_code="style_structure", evidence_role="risk" if (value or 0) < 0 else "support", metric_name="中证2000宽基代理涨跌", metric_scope="style", metric_value=value, unit="%", source_id=str(selected.get("source_id") or "csi2000_proxy"), source_label=str(selected.get("name") or "中证2000宽基代理"), source_url=selected.get("source_url"), source_as_of=str(as_of), quality_state=str(selected.get("quality_state") or "degraded"), rule_version=str(structure.get("config_version") or "unversioned"), scope_definition="小微盘宽基代理，不等于纯微盘或小登")
            evidence.append(ref)
            fact = f"中证2000宽基代理涨跌幅{value:+.2f}%。" if value is not None else "中证2000宽基代理已更新。"
            return dimension_state(snapshot_id=snapshot_id, dimension_code="style_structure", label=DIMENSION_LABELS["style_structure"], support_level="unknown", conclusion="目前只有中证2000行情；老登、中登、小登代表股的数据不完整，暂时看不出资金偏向哪种风格。", fact_summary=[fact, "中证2000只能近似观察小微盘，不代表纯微盘，也不代表小登方向。"], counter_evidence=["单看一个小微盘指数，不能判断整个市场的风格。"], missing_evidence=["老登代表股的涨跌和成交", "中登新能源及设备链代表股的涨跌和成交", "小登代表股的涨跌和成交", "纯微盘市场的正式数据"], quality_state="degraded", freshness_state="current", as_of=str(as_of), method_version=version, evidence_ref_ids=[ref["evidence_ref_id"]])
        return dimension_state(snapshot_id=snapshot_id, dimension_code="style_structure", label=DIMENSION_LABELS["style_structure"], support_level="unknown", conclusion="老登、中登、小登代表股和微盘行情还没有更新完整，暂时看不出资金偏向哪种风格。", fact_summary=[], counter_evidence=[], missing_evidence=["老登、中登、小登代表股的涨跌与成交，以及纯微盘市场数据"], quality_state="unknown", freshness_state="missing", as_of=default_as_of, method_version=version, evidence_ref_ids=[])

    def _position_dimension(self, snapshot_id: str, trade_date: str, default_as_of: str, version: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        sentiment = self.sources["sentiment"]
        as_of = sentiment.get("as_of")
        effect = sentiment.get("high_level_loss_effect") if isinstance(sentiment.get("high_level_loss_effect"), dict) else {}
        if trade_date_of(as_of) != trade_date or effect.get("state") not in {"usable", "partial"} or integer(effect.get("sample_count")) in {None, 0}:
            return dimension_state(snapshot_id=snapshot_id, dimension_code="position_fragility", label=DIMENSION_LABELS["position_fragility"], support_level="unknown", conclusion="高位样本、前期路径和成交证据不足，位置风险待核验。", fact_summary=[], counter_evidence=[], missing_evidence=["高位样本收益与最大不利波动", "前期涨幅、换手和拥挤度"], quality_state="unknown", freshness_state="missing", as_of=default_as_of, method_version=version, evidence_ref_ids=[])
        median = number(effect.get("median_return_pct"))
        adverse = number(effect.get("max_adverse_excursion_pct"))
        sample = integer(effect.get("sample_count")) or 0
        level = "suppress" if (median is not None and median < 0) or (adverse is not None and adverse <= -8) else "neutral"
        representatives = []
        for stock in sorted((item for item in as_list(effect.get("stocks")) if isinstance(item, dict)), key=lambda item: number(item.get("low_return_pct")) or 0)[:5]:
            quote_as_of = normalize_quote_time(stock.get("quote_as_of")) or str(as_of)
            representatives.append({"code": stock.get("code"), "name": stock.get("name"), "change_pct": stock.get("close_return_pct"), "as_of": quote_as_of, "source": "腾讯财经公开行情", "role": "昨日高位样本"})
        ref = evidence_ref(snapshot_id=snapshot_id, dimension_code="position_fragility", evidence_role="risk" if level == "suppress" else "counter", metric_name="高位样本收益与最大不利波动", metric_scope="security", metric_value={"样本": sample, "收益中位数": median, "最大不利波动": adverse}, unit="%", source_id="high_level_loss_effect", source_label="昨日高位股次日行情", source_url=effect.get("source"), source_as_of=str(as_of), quality_state=str(effect.get("state")), rule_version="high_level_loss_v1", scope_definition=f"昨日二板及以上样本{sample}只", representative_securities=representatives)
        evidence.append(ref)
        conclusion = "多数高位股收盘仍上涨，但其中最弱的一只盘中一度跌幅较大，追高的个股风险仍然很高。" if level == "suppress" else "高位股整体没有明显走弱，但仍要看成交是否放大、资金是否过度集中。"
        median_text = f"{median:.2f}" if median is not None else "待核验"
        adverse_text = f"{adverse:.2f}" if adverse is not None else "待核验"
        return dimension_state(snapshot_id=snapshot_id, dimension_code="position_fragility", label=DIMENSION_LABELS["position_fragility"], support_level=level, conclusion=conclusion, fact_summary=[f"观察的{sample}只高位股，收盘涨跌幅中间值为{median_text}%；其中最弱的一只盘中一度跌{abs(adverse):.2f}%。" if adverse is not None else f"观察的{sample}只高位股，收盘涨跌幅中间值为{median_text}%。"], counter_evidence=["只观察了部分高位股，不能代表全部股票。"], missing_evidence=["更多高位股是否出现放量下跌，以及资金是否过度集中在少数高位股"], quality_state="degraded" if effect.get("state") == "partial" else "usable", freshness_state="current", as_of=str(as_of), method_version=version, evidence_ref_ids=[ref["evidence_ref_id"]])

    def _external_dimension(self, snapshot_id: str, trade_date: str, default_as_of: str, version: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        external = self.sources["external"]
        external_rows = [item for item in as_list(external.get("markets")) if isinstance(item, dict)]
        external_current = [
            item for item in external_rows
            if str(item.get("a_share_trade_date") or trade_date_of(item.get("as_of")) or "") == trade_date
            and (parse_datetime(item.get("as_of")) is not None)
            and (parse_datetime(item.get("as_of")) <= parse_datetime(default_as_of))
        ]
        if external_current:
            refs = []
            for item in external_current:
                ref = evidence_ref(
                    snapshot_id=snapshot_id,
                    dimension_code="external_constraint",
                    evidence_role="risk" if item.get("direction") == "down" else "counter",
                    metric_name=f"{item.get('market') or '外盘'}收盘线索",
                    metric_scope="cross_market",
                    metric_value=item.get("conclusion"),
                    unit=None,
                    source_id=str(item.get("source_id") or f"external_{item.get('market') or 'unknown'}"),
                    source_label=str(item.get("source_name") or f"{item.get('market') or '外盘'}市场输入"),
                    source_url=item.get("source_url") or external.get("source_url"),
                    source_as_of=str(item.get("as_of")),
                    quality_state=str(item.get("quality_state") or "usable"),
                )
                evidence.append(ref)
                refs.append(ref["evidence_ref_id"])
            return dimension_state(
                snapshot_id=snapshot_id,
                dimension_code="external_constraint",
                label=DIMENSION_LABELS["external_constraint"],
                support_level="suppress" if any(item.get("direction") == "down" for item in external_current) else "unknown",
                conclusion="外盘已经有行情，但只有A股代表股也同步走强或走弱，才说明影响真正传到了A股。",
                fact_summary=[str(item.get("conclusion")) for item in external_current if item.get("conclusion")],
                counter_evidence=["外盘上涨不代表A股一定上涨，要看A股代表股是否跟随。"],
                missing_evidence=[
                    str(value)
                    .replace("同口径公开行情", "使用相同时间和统计方法的公开行情")
                    .replace("A股代表股共振或背离", "A股代表股是否跟随外盘走强或走弱")
                    for value in as_list(external.get("missing_evidence"))
                    if value
                ],
                quality_state=str(external.get("quality_state") or "degraded"),
                freshness_state="current",
                as_of=newest_time([item.get("as_of") for item in external_current]) or default_as_of,
                method_version=version,
                evidence_ref_ids=refs,
            )
        decision = self.sources["decision"]
        env = decision.get("market_environment") if isinstance(decision.get("market_environment"), dict) else {}
        rows = [item for item in as_list(env.get("cross_market")) if isinstance(item, dict)]
        current = [item for item in rows if trade_date_of(item.get("as_of")) == trade_date]
        if not current:
            stale_dates = sorted({trade_date_of(item.get("as_of")) for item in rows} - {None, trade_date})
            return dimension_state(snapshot_id=snapshot_id, dimension_code="external_constraint", label=DIMENSION_LABELS["external_constraint"], support_level="unknown", conclusion="当天美股、港股或韩国市场行情还没有更新完整，暂时不判断外盘对A股的影响。", fact_summary=[], counter_evidence=[f"现有外盘行情停留在{'、'.join(stale_dates)}，不用于今天的判断。"] if stale_dates else [], missing_evidence=["外盘发生变化的时间和来源", "A股代表股是否跟随或反向变化", "外盘影响通常能持续多久"], quality_state="unknown", freshness_state="stale" if stale_dates else "missing", as_of=default_as_of, method_version=version, evidence_ref_ids=[])
        refs = []
        for item in current:
            ref = evidence_ref(snapshot_id=snapshot_id, dimension_code="external_constraint", evidence_role="counter", metric_name=f"{item.get('market') or '外盘'}传导线索", metric_scope="cross_market", metric_value=item.get("conclusion"), unit=None, source_id=f"cross_market_{item.get('market') or 'unknown'}", source_label=f"{item.get('market') or '外盘'}市场输入", source_url=item.get("source_url"), source_as_of=str(item.get("as_of")), quality_state=str(item.get("quality_state") or "degraded"))
            evidence.append(ref); refs.append(ref["evidence_ref_id"])
        return dimension_state(snapshot_id=snapshot_id, dimension_code="external_constraint", label=DIMENSION_LABELS["external_constraint"], support_level="unknown", conclusion="外盘已经有行情，但A股代表股是否跟随还没有确认，暂时不能把外盘变化当成交易机会。", fact_summary=[f"已取得{len(current)}条当天外盘行情。"], counter_evidence=["外盘上涨或下跌，不代表A股一定同方向变化。"], missing_evidence=["A股代表股是否跟随外盘走强或走弱"], quality_state="degraded", freshness_state="current", as_of=newest_time([item.get("as_of") for item in current]) or default_as_of, method_version=version, evidence_ref_ids=refs)

    def write(self) -> dict[str, Any]:
        payload = self.build()
        snapshot = self.root / "data/v2/v22/environment-snapshots" / str(payload["trade_date"]) / f"{payload['environment_snapshot_id']}.json"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        if snapshot.exists():
            existing = load_json(snapshot)
            if existing.get("immutable_hash") != payload.get("immutable_hash"):
                raise ValueError("immutable environment snapshot conflict")
        else:
            snapshot.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        current = self.root / PUBLIC_OUTPUT
        current.parent.mkdir(parents=True, exist_ok=True)
        current.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._write_index(payload, snapshot)
        return payload

    def _write_index(self, payload: dict[str, Any], snapshot: Path) -> None:
        path = self.root / SNAPSHOT_INDEX
        existing = load_json(path)
        rows = [item for item in as_list(existing.get("snapshots")) if isinstance(item, dict)]
        if not any(item.get("environment_snapshot_id") == payload.get("environment_snapshot_id") for item in rows):
            rows.append({
                "environment_snapshot_id": payload.get("environment_snapshot_id"),
                "trade_date": payload.get("trade_date"),
                "session_phase": payload.get("session_phase"),
                "as_of": payload.get("as_of"),
                "immutable_hash": payload.get("immutable_hash"),
                "relative_path": str(snapshot.relative_to(self.root)),
            })
        rows.sort(key=lambda item: (str(item.get("as_of") or ""), str(item.get("environment_snapshot_id") or "")))
        index = {"schema_version": 1, "generated_at": now_iso(), "snapshot_count": len(rows), "snapshots": rows}
        path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

from __future__ import annotations

from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from v2_platform.learning import TradingCalendar, as_dict, as_list, load_json


CHINA = ZoneInfo("Asia/Shanghai")


def parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(CHINA)


def text(value: Any, default: str = "") -> str:
    value = str(value or "").strip()
    return value or default


def text_list(value: Any) -> list[str]:
    return [text(item) for item in as_list(value) if text(item)]


def unique(values: list[str], limit: int = 6) -> list[str]:
    rows: list[str] = []
    for value in values:
        value = text(value)
        if value and value not in rows:
            rows.append(value)
        if len(rows) >= limit:
            break
    return rows


MARKET_LABELS = {"US": "美股", "HK": "港股", "KR": "韩国市场"}


def cross_market_trade_text(item: dict[str, Any]) -> str:
    market = MARKET_LABELS.get(text(item.get("origin_market")).upper(), "外盘")
    themes = text("、".join(text_list(item.get("a_share_themes"))), "相关方向")
    origin_direction = text(item.get("origin_direction")).lower()
    a_share_direction = text(item.get("a_share_direction")).lower()
    state = text(item.get("transmission_state")).lower()
    stock_rows = []
    for stock in as_list(item.get("representative_securities"))[:2]:
        if not isinstance(stock, dict) or not text(stock.get("name")):
            continue
        try:
            change = float(stock.get("change_pct"))
            stock_rows.append(f"{text(stock.get('name'))}{change:+.2f}%")
        except (TypeError, ValueError):
            stock_rows.append(text(stock.get("name")))
    stocks = "、".join(stock_rows)
    stock_note = f"，代表股{stocks}" if stocks else ""
    if state == "confirmed" and origin_direction == "down" and a_share_direction == "down":
        return f"{themes}：{market}走弱，A股相关股票也在下跌{stock_note}。这是风险信号，先回避，不抄底。"
    if state == "confirmed" and origin_direction == "up" and a_share_direction == "up":
        return f"{themes}：{market}上涨，A股相关股票也在走强{stock_note}。这是机会信号，但不追高，等回踩承接或板块继续扩散。"
    if state == "divergent" or (origin_direction and a_share_direction and origin_direction != a_share_direction):
        return f"{themes}：{market}与A股走势相反{stock_note}。外盘没有形成可用指引，暂不操作。"
    if state == "pending":
        direction = "上涨" if origin_direction == "up" else ("下跌" if origin_direction == "down" else "方向不明")
        return f"{themes}：{market}{direction}，但A股相关股票还没有跟随{stock_note}。先观察，不提前下注。"
    return f"{themes}：{market}变化暂时只能作背景{stock_note}，不能单独作为买卖理由。"


class CockpitPhaseViewBuilder:
    """Build the user-facing pre-market/intraday phase result without changing decisions."""

    def __init__(self, root: Path, *, now: datetime | None = None) -> None:
        self.root = root.resolve()
        observed = now or datetime.now(timezone.utc).astimezone(CHINA)
        if observed.tzinfo is None:
            raise ValueError("cockpit_phase_time_timezone_required")
        self.now = observed.astimezone(CHINA)
        self.calendar = TradingCalendar(load_json(self.root / "config/v2-market-calendar.json"), "CN")
        self.premarket = load_json(self.root / "data/premarket.json")
        self.midday = load_json(self.root / "data/midday.json")
        self.postmarket = load_json(self.root / "data/postmarket.json")
        self.evening = load_json(self.root / "data/evening-sentiment.json")
        self.watch = load_json(self.root / "data/opportunity-watch.json")
        self.environment = load_json(self.root / "data/v2/v22/market-environment.json")
        self.environment_decision = load_json(self.root / "data/v2/v22/environment-decision.json")
        self.candidate = load_json(self.root / "data/v2/v22/decision-system-candidate.json")
        quote_payload = load_json(self.root / "data/v2/inputs/representative-stock-quotes.json")
        self.representative_quotes = {
            text(item.get("name")): item
            for item in as_list(quote_payload.get("quotes"))
            if isinstance(item, dict) and text(item.get("name"))
        }
        self.codes = as_dict(load_json(self.root / "config/v2-representative-stock-codes.json").get("codes"))

    def build(self) -> dict[str, Any]:
        open_state = self.calendar.is_open(self.now.date())
        stage = self._stage(open_state)
        if stage == "pre_market":
            body = self._premarket_view()
        elif stage in {"intraday_validation", "close_validation"}:
            body = self._intraday_view(stage)
        else:
            body = self._waiting_view(open_state)
        sessions = {
            "today": {"session_id": "today", **body},
            "premarket": {"session_id": "premarket", **self._premarket_view()},
            "intraday": {"session_id": "intraday", **self._intraday_view("intraday_validation")},
            "midday": {"session_id": "midday", **self._midday_view()},
            "postmarket": {"session_id": "postmarket", **self._postmarket_view()},
            "evening": {"session_id": "evening", **self._evening_view()},
        }
        return {
            "schema_version": 1,
            "mode": "shadow_only",
            "generated_at": self.now.isoformat(timespec="seconds"),
            "trade_date": self.now.date().isoformat(),
            "calendar_version": self.calendar.version,
            "stage": stage,
            **body,
            "sessions": sessions,
            "guardrails": {
                "automatic_trading": False,
                "user_assets_modified": False,
                "model_promoted": False,
                "v1_modified": False,
                "stale_data_used_as_current": False,
                "missing_facts_ai_filled": False,
            },
        }

    def _is_current_source(self, payload: dict[str, Any]) -> tuple[bool, datetime | None]:
        source_time = parse_time(payload.get("timestamp"))
        explicit_dates = [
            text(payload.get("trade_date")),
            text(payload.get("target_trade_date")),
            text(payload.get("current_signal_date")),
            text(as_dict(payload.get("sentiment_summary")).get("date")),
        ]
        current = self.now.date().isoformat() in explicit_dates or bool(source_time and source_time.date() == self.now.date())
        return current, source_time

    def _representatives_from_text(
        self,
        values: list[str],
        *,
        source: str,
        as_of: datetime | None,
        quote_status_label: str = "等待下一交易时段",
        role_label: str = "影响对象",
    ) -> list[dict[str, Any]]:
        haystack = " ".join(values)
        rows: list[dict[str, Any]] = []
        known_codes = dict(self.codes)
        known_codes.update({
            name: text(item.get("code"))
            for name, item in self.representative_quotes.items()
            if text(item.get("code"))
        })
        for name, code in known_codes.items():
            if name not in haystack:
                continue
            rows.append({
                "name": name,
                "code": text(code, "代码待核验"),
                "role": role_label,
                "change_pct": None,
                "quote_as_of": as_of.isoformat(timespec="seconds") if as_of else None,
                "source": source,
                "quote_note": "当前仅确认事件关联，价格等待下一交易时段验证。",
                "quote_status_label": quote_status_label,
            })
            if len(rows) >= 6:
                break
        return rows

    def _stage(self, open_state: bool | None) -> str:
        if open_state is not True:
            return "waiting_next_session"
        current = self.now.timetz().replace(tzinfo=None)
        if current < time(9, 30):
            return "pre_market"
        if current < time(15, 0):
            return "intraday_validation"
        return "close_validation"

    def _premarket_view(self) -> dict[str, Any]:
        source_time = parse_time(self.premarket.get("timestamp"))
        explicit_target = text(self.premarket.get("target_trade_date"))
        current = explicit_target == self.now.date().isoformat() or bool(source_time and source_time.date() == self.now.date())
        if not current:
            return self._empty_body(
                stage_label="今日盘前预案",
                status_label="等待今日更新",
                headline="今日盘前预案尚未生成，最近一次旧预案不会作为今天的操作依据。",
                note="盘前数据到达后，本区将展示隔夜外盘、情绪预判、主线、代表股和条件；09:30后自动切换为盘中验证。",
                last_available_at=source_time.isoformat(timespec="seconds") if source_time else None,
            )

        context = as_dict(self.premarket.get("market_context"))
        us = as_dict(self.premarket.get("us_overnight"))
        asia = as_dict(self.premarket.get("early_asia"))
        hk = as_dict(self.premarket.get("hk_auction"))
        external_evidence = unique([
            text(us.get("conclusion")),
            text(asia.get("judgement")),
            *[
                f"港股{item.get('name')}：{item.get('status')}，{item.get('evidence')}"
                for item in as_list(hk.get("sectors"))[:2]
                if isinstance(item, dict) and text(item.get("name"))
            ],
        ], 4)
        mainline_items = unique([
            *text_list(self.premarket.get("strong_lines")),
            *text_list(self.premarket.get("watch_lines")),
        ], 5)
        mainline_names = unique(text_list(context.get("benefit_themes")), 5)
        mapping = as_dict(self.premarket.get("a_share_mapping"))
        representatives = []
        for role, names in (("核心观察", mapping.get("core_leaders")), ("弹性观察", mapping.get("elastic_targets"))):
            for name in text_list(names):
                if any(item["name"] == name for item in representatives):
                    continue
                representatives.append({
                    "name": name,
                    "code": text(self.codes.get(name), "代码待核验"),
                    "role": role,
                    "change_pct": None,
                    "quote_as_of": None,
                    "source": "等待集合竞价行情",
                    "quote_note": "盘前仅列观察对象，不能用题材涨跌代替个股行情。",
                    "quote_status_label": "盘前行情未单独保存",
                })
                if len(representatives) >= 6:
                    break
            if len(representatives) >= 6:
                break
        if not representatives:
            representatives = self._representatives_from_text(
                [text(value) for value in mapping.values()],
                source="盘前观察名单（9:25个股行情未留存）",
                as_of=None,
                quote_status_label="盘前行情未单独保存",
                role_label="盘前观察股",
            )
        watch_current = text(self.watch.get("target_trade_date")) == self.now.date().isoformat()
        invalidations = []
        if watch_current:
            for item in as_list(self.watch.get("items")):
                if isinstance(item, dict) and "盘前" in text(item.get("source_phase")):
                    invalidations.extend(text_list(item.get("invalidate_rules")))
        invalidations = unique(invalidations, 5) or ["代表股与板块扩散未兑现时，不升级为盘中机会。"]
        risks = unique([*text_list(self.premarket.get("risk_lines")), *text_list(context.get("risk_points"))], 6)
        sentiment = text(context.get("sentiment_judgement"), text(self.premarket.get("summary"), "开盘情绪等待判断"))
        return {
            "stage_label": "今日盘前预案",
            "availability": "ready",
            "status_label": "当日预案已就绪",
            "headline": text(self.premarket.get("summary"), sentiment),
            "source_as_of": source_time.isoformat(timespec="seconds") if source_time else None,
            "last_available_at": source_time.isoformat(timespec="seconds") if source_time else None,
            "transition_note": "09:30后自动切换为盘中验证；盘前判断不会直接升级为交易机会。",
            "sections": {
                "external_market": {"title": "隔夜外盘", "conclusion": external_evidence[0] if external_evidence else "外盘证据等待更新", "evidence": external_evidence[1:]},
                "sentiment": {"title": "开盘情绪判断", "conclusion": sentiment, "evidence": []},
                "mainline": {"title": "主线预判", "names": mainline_names, "evidence": mainline_items},
                "representative_stocks": representatives,
                "action_conditions": unique(text_list(self.premarket.get("opening_plan")), 6),
                "risks": risks or ["当日风险证据等待补齐。"],
                "invalidation_conditions": invalidations,
            },
        }

    def _intraday_view(self, stage: str) -> dict[str, Any]:
        today = self.now.date().isoformat()
        candidate_time = parse_time(self.candidate.get("as_of"))
        environment_time = parse_time(self.environment.get("as_of"))
        candidate_current = text(self.candidate.get("trade_date")) == today and bool(candidate_time and candidate_time.date() == self.now.date())
        environment_current = text(self.environment.get("trade_date")) == today and bool(environment_time and environment_time.date() == self.now.date())
        label = "盘中判断" if stage == "intraday_validation" else "收盘结论"
        if not candidate_current and not environment_current:
            return self._empty_body(
                stage_label=label,
                status_label="等待当日采集",
                headline="已进入盘中验证阶段，今日行情与代表股证据尚未形成。",
                note="系统将在下一个更新时间补充市场和代表股；更新前不沿用上一交易日结论。",
                last_available_at=max(filter(None, [candidate_time, environment_time]), default=None).isoformat(timespec="seconds") if any([candidate_time, environment_time]) else None,
            )

        cases = []
        if candidate_current:
            cases = [
                item for item in [*as_list(self.candidate.get("current_cases")), *as_list(self.candidate.get("validation_cases"))]
                if isinstance(item, dict)
            ]
        representatives = []
        for case in cases:
            for stock in as_list(case.get("representative_stocks")):
                if not isinstance(stock, dict) or not text(stock.get("name")):
                    continue
                identity = text(stock.get("stock_code"), text(stock.get("name")))
                if any(item["code"] == identity for item in representatives):
                    continue
                representatives.append({
                    "name": text(stock.get("name")),
                    "code": identity,
                    "role": text(stock.get("role"), "代表股"),
                    "change_pct": stock.get("stock_change_pct"),
                    "quote_as_of": stock.get("stock_quote_as_of"),
                    "source": text(stock.get("stock_quote_source"), "行情来源待核验"),
                    "quote_note": text(stock.get("basis"), "用于当前案例验证"),
                })
                if len(representatives) >= 6:
                    break
            if len(representatives) >= 6:
                break
        sentiment = as_dict(self.environment.get("sentiment_view")) if environment_current else {}
        mappings = as_list(self.environment_decision.get("cross_market_mappings")) if text(self.environment_decision.get("trade_date")) == today else []
        external_evidence = unique([
            cross_market_trade_text(item)
            for item in mappings if isinstance(item, dict)
        ], 4)
        mainline_cases = [item for item in cases if text(item.get("title")) != "市场环境风险"]
        mainline_names = unique([text(item.get("title")) for item in mainline_cases], 5)
        mainline_evidence = unique([text(item.get("conclusion")) for item in mainline_cases], 5)
        conditions = unique([condition for item in cases for condition in text_list(item.get("confirm_conditions"))], 6)
        risks = unique([risk for item in cases for risk in text_list(item.get("risk_factors"))], 6)
        invalidations = unique([condition for item in cases for condition in text_list(item.get("invalidation_conditions"))], 6)
        action_constraint = text(self.environment_decision.get("action_constraint")) if environment_current else ""
        current_case_count = len(as_list(self.candidate.get("current_cases"))) if candidate_current else 0
        candidate_headline = (
            f"当前有{current_case_count}个方向值得重点处理"
            if current_case_count
            else "当前没有值得出手的机会"
        ) if candidate_current else ""
        headline = "；".join(unique([candidate_headline, action_constraint], 2)) or "当日环境事实已更新，机会案例仍待确认。"
        availability = "ready" if candidate_current else "partial"
        status_label = "今天的判断已更新" if candidate_current else "大盘数据已更新，机会还在整理"
        source_times = [value for value in (candidate_time if candidate_current else None, environment_time if environment_current else None) if value]
        return {
            "stage_label": label,
            "availability": availability,
            "status_label": status_label,
            "headline": headline,
            "source_as_of": max(source_times).isoformat(timespec="seconds") if source_times else None,
            "last_available_at": max(source_times).isoformat(timespec="seconds") if source_times else None,
            "transition_note": "盘前判断已经进入盘中检查；只有代表股和板块一起走强，才考虑行动。",
            "sections": {
                "external_market": {"title": "外盘对A股的影响", "conclusion": external_evidence[0] if external_evidence else "外盘方向还没有得到A股代表股确认，暂不据此操作。", "evidence": external_evidence[1:]},
                "sentiment": {"title": "当前情绪判断", "conclusion": text(sentiment.get("judgment"), "当日情绪证据仍待补齐"), "evidence": unique([text(item.get("evidence")) for item in as_list(sentiment.get("drivers")) if isinstance(item, dict)], 4)},
                "mainline": {"title": "今天资金集中在哪里", "names": mainline_names, "evidence": mainline_evidence},
                "representative_stocks": representatives,
                "action_conditions": conditions or ["代表股和板块一起转强后，才加强关注。"],
                "risks": risks or [action_constraint or "风险证据等待当日检查点更新。"],
                "invalidation_conditions": invalidations or ["代表股背离或市场环境转弱时，当前方向不成立。"],
            },
        }

    def _midday_view(self) -> dict[str, Any]:
        current, source_time = self._is_current_source(self.midday)
        if not current:
            return self._empty_body(
                stage_label="今日午盘判断",
                status_label="等待今日更新",
                headline="今日午盘判断尚未生成，旧日期结论不作为下午操作依据。",
                note="午间数据到达后，本页将展示上午强弱、代表股、下午条件和风险。",
                last_available_at=source_time.isoformat(timespec="seconds") if source_time else None,
            )
        snapshot = as_dict(self.midday.get("morning_snapshot"))
        breadth = as_dict(snapshot.get("breadth"))
        review = as_dict(self.midday.get("morning_review"))
        trends = [item for item in as_list(review.get("main_trends")) if isinstance(item, dict)]
        afternoon = [item for item in as_list(self.midday.get("afternoon_watch")) if isinstance(item, dict)]
        tracking = as_dict(self.midday.get("semiconductor_five_tracking"))
        representatives = []
        for item in as_list(tracking.get("strength_ranking")):
            if not isinstance(item, dict) or not text(item.get("name")):
                continue
            name = text(item.get("name"))
            representatives.append({
                "name": name,
                "code": text(self.codes.get(name), "代码待核验"),
                "role": text(item.get("mainline_role"), "午盘观察"),
                "change_pct": item.get("change_pct"),
                "quote_as_of": source_time.isoformat(timespec="seconds") if source_time else None,
                "source": "午间行情",
                "quote_note": text(item.get("intraday_state"), "用于下午验证"),
            })
            if len(representatives) >= 6:
                break
        if not representatives:
            representatives = self._midday_representatives(source_time, snapshot)
        strongest = trends[:4]
        limit_up = breadth.get("effective_limit_up_count", breadth.get("non_st_limit_up_count"))
        limit_down = breadth.get("limit_down_count", breadth.get("non_st_limit_down_count"))
        broken = breadth.get("broken_limit_count")
        sentiment = text(
            breadth.get("comparison"),
            f"涨停{limit_up if limit_up is not None else '尚未取得'}只、跌停{limit_down if limit_down is not None else '尚未取得'}只。",
        )
        action_conditions = unique(
            [text(item.get("confirm")) for item in afternoon]
            if afternoon else text_list(self.midday.get("afternoon_watch")),
            6,
        )
        invalidation_conditions = unique([
            *[text(item.get("invalidate")) for item in afternoon],
            text(as_dict(self.midday.get("switch_chain_special")).get("invalidate_condition")),
            text(as_dict(self.midday.get("electronic_cloth_fiberglass_watch")).get("invalidate_condition")),
            text(as_dict(self.midday.get("style_rotation_radar")).get("condition_to_reverse")),
        ], 6)
        return {
            "stage_label": "今日午盘判断",
            "availability": "ready",
            "status_label": "当日午盘已更新",
            "headline": text(review.get("one_sentence"), "上午结论待整理。"),
            "source_as_of": source_time.isoformat(timespec="seconds") if source_time else None,
            "last_available_at": source_time.isoformat(timespec="seconds") if source_time else None,
            "transition_note": "只使用今日上午已经发生的行情；下午条件需由代表股和板块共同验证。",
            "sections": {
                "external_market": {
                    "title": "上午盘面",
                    "conclusion": sentiment,
                    "evidence": unique(text_list(snapshot.get("hk")), 3),
                },
                "sentiment": {
                    "title": "上午情绪",
                    "conclusion": sentiment,
                    "evidence": unique([
                        f"非ST涨停{limit_up if limit_up is not None else '尚未取得'}只，跌停{limit_down if limit_down is not None else '尚未取得'}只，炸板{broken if broken is not None else '尚未取得'}只。",
                    ], 2),
                },
                "mainline": {
                    "title": "上午强弱方向",
                    "names": unique([text(item.get("name")) for item in strongest], 4),
                    "evidence": unique([
                        f"{text(item.get('name'))}：{text(item.get('status'))}"
                        for item in strongest
                        if text(item.get("name")) and text(item.get("status"))
                    ], 4),
                },
                "representative_stocks": representatives,
                "action_conditions": action_conditions,
                "risks": unique(text_list(self.midday.get("risk")), 6),
                "invalidation_conditions": invalidation_conditions,
            },
        }

    def _midday_representatives(self, source_time: datetime | None, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        groups = [
            ("交换机风险代表", as_list(as_dict(self.midday.get("switch_chain_special")).get("ranking"))[:3]),
            ("电子布观察代表", as_list(as_dict(self.midday.get("electronic_cloth_fiberglass_watch")).get("upstream_core"))[:2]),
            ("PCB风险代表", as_list(as_dict(self.midday.get("electronic_cloth_fiberglass_watch")).get("pcb_feedback"))[:2]),
        ]
        quote_time = source_time
        for index in as_list(snapshot.get("indices")):
            if not isinstance(index, dict):
                continue
            raw = text(index.get("quote_time"))
            try:
                quote_time = datetime.strptime(raw[:14], "%Y%m%d%H%M%S").replace(tzinfo=CHINA)
                break
            except (TypeError, ValueError):
                continue
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for role, items in groups:
            for item in items:
                if not isinstance(item, dict) or not text(item.get("name")) or item.get("change_pct") is None:
                    continue
                name = text(item.get("name"))
                reference = self.representative_quotes.get(name) or {}
                code = text(reference.get("code"), text(self.codes.get(name), "代码待核验"))
                if code in seen:
                    continue
                seen.add(code)
                rows.append({
                    "name": name,
                    "code": code,
                    "role": text(item.get("role"), role),
                    "change_pct": item.get("change_pct"),
                    "quote_as_of": quote_time.isoformat(timespec="seconds") if quote_time else None,
                    "source": "午间11:30行情",
                    "quote_note": text(item.get("intraday_state"), text(item.get("assessment"), "用于下午验证")),
                })
                if len(rows) >= 6:
                    return rows
        return rows

    def _postmarket_view(self) -> dict[str, Any]:
        current, source_time = self._is_current_source(self.postmarket)
        today = self.now.date().isoformat()
        environment_time = parse_time(self.environment.get("as_of"))
        candidate_time = parse_time(self.candidate.get("as_of"))
        close_shadow_current = (
            self.now.timetz().replace(tzinfo=None) >= time(15, 0)
            and text(self.environment.get("trade_date")) == today
            and bool(environment_time and environment_time.date() == self.now.date())
        )
        if not current and close_shadow_current:
            view = self._intraday_view("close_validation")
            return {**view, "stage_label": "今日盘后复盘", "status_label": "当日收盘验证已更新"}
        if not current:
            latest = max(filter(None, [source_time, environment_time, candidate_time]), default=None)
            return self._empty_body(
                stage_label="今日盘后复盘",
                status_label="等待今日更新",
                headline="今日收盘复盘尚未形成，不用旧收盘结论代替。",
                note="收盘后将展示今日主线、风险线、代表股和次日验证条件。",
                last_available_at=latest.isoformat(timespec="seconds") if latest else None,
            )
        review = as_dict(self.postmarket.get("review"))
        hotspots = [item for item in as_list(self.postmarket.get("hotspots")) if isinstance(item, dict)]
        representatives: list[dict[str, Any]] = []
        seen: set[str] = set()
        candidates: list[tuple[dict[str, Any], Any]] = []
        # First take one auditable representative from each line, then fill the
        # remaining slots. This prevents the first theme from occupying the
        # whole close-review sample.
        for theme in hotspots:
            stocks = as_list(theme.get("stocks"))
            first = next((stock for stock in stocks if self._postmarket_quote(stock, today)), None)
            if first is not None:
                candidates.append((theme, first))
        for theme in hotspots:
            candidates.extend((theme, stock) for stock in as_list(theme.get("stocks")))
        for theme, stock in candidates:
            quote = self._postmarket_quote(stock, today)
            if not quote:
                continue
            name = text(quote.get("name"))
            identity = text(quote.get("code"), name)
            if identity in seen:
                continue
            seen.add(identity)
            representatives.append({
                "name": name,
                "code": identity,
                "role": f"{text(theme.get('name'), '收盘方向')}代表股",
                "change_pct": quote.get("stock_change_pct"),
                "quote_as_of": quote.get("stock_quote_as_of"),
                "source": text(quote.get("stock_quote_source"), "行情来源待核验"),
                "quote_note": text(theme.get("status"), "用于收盘结论"),
            })
            if len(representatives) >= 6:
                break
        sentiment_indicator = as_dict(self.postmarket.get("sentiment_indicator"))
        breadth = as_dict(self.postmarket.get("market_breadth"))
        limit_structure = as_dict(breadth.get("limit_structure"))
        style = text(sentiment_indicator.get("style"))
        risk_level = {"高": "较高", "中": "中等", "低": "较低"}.get(text(sentiment_indicator.get("risk_level")), text(sentiment_indicator.get("risk_level")))
        limit_up = limit_structure.get("limit_up_count")
        limit_down = limit_structure.get("limit_down_count")
        down_ratio = breadth.get("down_ratio_pct")
        sentiment_facts = []
        if limit_up is not None and limit_down is not None:
            sentiment_facts.append(f"非ST涨停{limit_up}只、跌停{limit_down}只，跌停比涨停多{max(0, int(limit_down) - int(limit_up))}只。")
        if down_ratio is not None:
            sentiment_facts.append(f"全市场约{float(down_ratio):.2f}%的股票下跌。")
        if limit_structure.get("broken_board_count") is not None:
            sentiment_facts.append(f"炸板{limit_structure.get('broken_board_count')}只，追高成功率偏低。")
        if sentiment_facts:
            sentiment_conclusion = (
                f"{style or '市场分化'}，风险{risk_level or '仍需警惕'}："
                f"{''.join(sentiment_facts[:2])}先防守，不把尾盘指数回拉当作风险解除。"
            )
        else:
            sentiment_conclusion = text(review.get("market_structure"), text(review.get("one_sentence"), "收盘情绪数据还不完整，先防守。"))
        return {
            "stage_label": "今日盘后复盘",
            "availability": "ready",
            "status_label": "当日盘后已更新",
            "headline": text(review.get("one_sentence"), text(review.get("summary"), "收盘结论待整理。")),
            "source_as_of": source_time.isoformat(timespec="seconds") if source_time else None,
            "last_available_at": source_time.isoformat(timespec="seconds") if source_time else None,
            "transition_note": "今日结论用于复盘和次日预案，不作为盘中实时触发。",
            "sections": {
                "external_market": {
                    "title": "收盘结构",
                    "conclusion": text(review.get("summary"), "收盘结构待整理。"),
                    "evidence": unique([text(item.get("detail")) for item in as_list(review.get("evidence")) if isinstance(item, dict)], 3),
                },
                "sentiment": {
                    "title": "全天情绪",
                    "conclusion": sentiment_conclusion,
                    "evidence": unique(sentiment_facts, 3),
                },
                "mainline": {
                    "title": "主线与风险线",
                    "names": unique([text(item.get("name")) for item in hotspots[:5]], 5),
                    "evidence": unique([f"{text(item.get('name'))}：{text(item.get('status'))}" for item in hotspots[:5]], 5),
                },
                "representative_stocks": representatives,
                "action_conditions": unique(text_list(self.postmarket.get("next_day_watch")), 6),
                "risks": unique(text_list(self.postmarket.get("risk")), 6),
                "invalidation_conditions": unique([text(item.get("risk")) for item in hotspots[:6]], 6),
            },
        }

    def _postmarket_quote(self, stock: Any, trade_date: str) -> dict[str, Any]:
        stock_row = stock if isinstance(stock, dict) else {}
        name = text(stock_row.get("name"), text(stock))
        quote = self.representative_quotes.get(name) or {}
        quote_time = parse_time(quote.get("stock_quote_as_of"))
        if (
            not quote_time
            or quote_time.date().isoformat() != trade_date
            or quote.get("stock_change_pct") is None
            or not text(quote.get("stock_quote_source"))
            or not text(quote.get("code"))
        ):
            return {}
        return quote

    def _evening_view(self) -> dict[str, Any]:
        current, source_time = self._is_current_source(self.evening)
        if not current:
            return self._empty_body(
                stage_label="今日晚间舆情",
                status_label="等待今晚更新",
                headline="今日晚间舆情尚未生成，不展示旧日期事件。",
                note="晚间更新后，本页只展示对次日有影响的事件、关联股票和验证条件。",
                last_available_at=source_time.isoformat(timespec="seconds") if source_time else None,
            )
        summary = as_dict(self.evening.get("sentiment_summary"))
        alerts = [item for item in as_list(self.evening.get("p0_alerts")) if isinstance(item, dict)]
        news = [item for item in as_list(self.evening.get("news")) if isinstance(item, dict)]
        combined_text = [
            text(self.evening.get("summary")),
            text(summary.get("market_read")),
            *[text(item.get("title")) for item in alerts],
            *[text(item.get("impact")) for item in news[:8]],
        ]
        representatives = self._representatives_from_text(
            combined_text,
            source="晚间只确认关联对象，价格等待次日竞价",
            as_of=None,
            quote_status_label="等待次日竞价",
            role_label="次日观察股",
        )
        return {
            "stage_label": "今日晚间舆情",
            "availability": "ready",
            "status_label": "当日晚间已更新",
            "headline": text(self.evening.get("summary"), text(summary.get("market_read"), "晚间结论待整理。")),
            "source_as_of": source_time.isoformat(timespec="seconds") if source_time else None,
            "last_available_at": source_time.isoformat(timespec="seconds") if source_time else None,
            "transition_note": "事件只用于形成次日预案；公司利好或市场观点不自动升级为板块机会。",
            "sections": {
                "external_market": {
                    "title": "晚间新增信息",
                    "conclusion": text(summary.get("market_read"), "等待晚间信息"),
                    "evidence": unique([text(item.get("title")) for item in alerts[:4]], 4),
                },
                "sentiment": {
                    "title": "次日开盘倾向",
                    "conclusion": text(summary.get("open_bias"), "等待判断"),
                    "evidence": unique([*text_list(summary.get("bullish"))[:2], *text_list(summary.get("bearish"))[:2]], 4),
                },
                "mainline": {
                    "title": "影响方向",
                    "names": unique([text(item.get("title")) for item in alerts[:5]], 5),
                    "evidence": unique([text(item.get("why_p0")) for item in alerts[:5]], 5),
                },
                "representative_stocks": representatives,
                "action_conditions": unique(text_list(summary.get("next_session_focus")), 6),
                "risks": unique([text(summary.get("risk_bias")), *text_list(summary.get("bearish"))], 6),
                "invalidation_conditions": unique([text(item.get("verify_next_day")) for item in news[:6]], 6),
            },
        }

    def _waiting_view(self, open_state: bool | None) -> dict[str, Any]:
        headline = "交易日历尚未完成核验，当前不生成盘前或盘中结论。" if open_state is None else "今日休市，等待下一交易日盘前预案。"
        return self._empty_body(
            stage_label="等待下一交易日",
            status_label="当前无交易时段",
            headline=headline,
            note="休市期间只保留历史复盘，不把旧预案当作当前机会。",
            last_available_at=None,
        )

    @staticmethod
    def _empty_body(*, stage_label: str, status_label: str, headline: str, note: str, last_available_at: str | None) -> dict[str, Any]:
        return {
            "stage_label": stage_label,
            "availability": "waiting_update",
            "status_label": status_label,
            "headline": headline,
            "source_as_of": None,
            "last_available_at": last_available_at,
            "transition_note": note,
            "sections": {
                "external_market": {"title": "隔夜外盘", "conclusion": "等待当日数据", "evidence": []},
                "sentiment": {"title": "情绪判断", "conclusion": "等待当日数据", "evidence": []},
                "mainline": {"title": "主线判断", "names": [], "evidence": []},
                "representative_stocks": [],
                "action_conditions": [],
                "risks": [],
                "invalidation_conditions": [],
            },
        }

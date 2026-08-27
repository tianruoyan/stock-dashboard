from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2_platform.decision_gates import decision_maturity, evaluate_gates, quote_complete
from v2_platform.environment_evidence import canonical_hash, newest_time, stable_id


PUBLIC_OUTPUT = "data/v2/v22/decision-cases.json"
CANDIDATE_OUTPUT = "data/v2/v22/decision-system-candidate.json"
SNAPSHOT_INDEX = "data/v2/v22/decision-case-snapshot-index.json"
POLICY_VERSION = "2026-07-23.e6.2"


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


def humanize(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("detail") or value.get("summary") or value.get("conclusion") or value.get("text") or ""
    elif isinstance(value, list):
        value = "；".join(humanize(item) for item in value if humanize(item))
    text = str(value or "")
    # Older generated clues may contain a serialized evidence fragment. Preserve
    # the market fact while stripping the engineering contract from user output.
    details = re.findall(r'(?:^|[,;])\s*"?detail"?\s*:\s*"([^"]+)"', text)
    if details:
        text = "；".join(dict.fromkeys(item.rstrip("；。") for item in details if item.strip()))
    replacements = {
        "本地监控日志 monitor.log": "盘中异动监测记录",
        "monitor.log": "盘中异动监测记录",
        "confirmed": "已确认",
        "candidate": "待确认",
        "expired": "已结束",
        "degraded": "数据待核验",
        "evaluation_eligible": "可进入复盘",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text).strip()


def normalized_identity(value: Any) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", str(value or "").strip().lower()).strip("-") or "unknown"


def business_path(card: dict[str, Any]) -> str:
    raw = "；".join(str(card.get(key) or "") for key in ("title", "theme", "trigger", "why_watch_summary", "why_watch", "conclusion"))
    if card.get("kind") == "risk" or any(token in str(card.get("trigger") or "") for token in ("回落", "下跌", "风险")):
        return "risk_path"
    if any(token in raw for token in ("港股", "美股", "韩国", "NVIDIA", "Micron", "外盘", "跨市场")):
        return "cross_market_mapping"
    if len(as_list(card.get("representative_stocks"))) == 1 and any(token in raw for token in ("公告", "业绩", "减持", "并购", "诉讼")):
        return "single_stock_event"
    return "theme_opportunity"


def signal_state(card: dict[str, Any], ended: bool) -> str:
    if ended or card.get("state") in {"expired", "invalidated"}:
        return "invalidated"
    return "verified" if card.get("state") == "confirmed" else "candidate"


def source_time(card: dict[str, Any]) -> str | None:
    trigger = card.get("trigger_metrics") if isinstance(card.get("trigger_metrics"), dict) else {}
    return newest_time([card.get("as_of"), card.get("last_evidence_at"), card.get("triggered_at"), trigger.get("as_of")])


def same_trade_date(value: Any, trade_date: str) -> bool:
    return bool(trade_date and value and str(value)[:10] == trade_date)


def has_current_clue_evidence(case: dict[str, Any], trade_date: str) -> bool:
    if same_trade_date(case.get("last_evidence_at"), trade_date):
        return True
    trigger = case.get("trigger_metrics") if isinstance(case.get("trigger_metrics"), dict) else {}
    if same_trade_date(trigger.get("as_of"), trade_date):
        return True
    return any(
        isinstance(stock, dict) and same_trade_date(stock.get("stock_quote_as_of"), trade_date)
        for stock in as_list(case.get("representative_stocks"))
    )


def clue_gap_breakdown(cases: list[dict[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    missing_representative = 0
    missing_trigger = 0
    missing_current_evidence = 0
    missing_validity = 0
    for case in cases:
        gates = {
            str(item.get("gate_id")): str(item.get("state"))
            for item in as_list(case.get("gates"))
            if isinstance(item, dict)
        }
        if gates.get("G3") == "fail":
            missing_representative += 1
        if gates.get("G1") == "fail":
            missing_trigger += 1
        if not has_current_clue_evidence(case, trade_date):
            missing_current_evidence += 1
        if not case.get("valid_until"):
            missing_validity += 1
    rows = [
        ("缺少代表股行情闭环", missing_representative),
        ("没有同日实质触发", missing_trigger),
        ("证据不是当前交易日", missing_current_evidence),
        ("没有明确有效时间", missing_validity),
    ]
    return [{"label": label, "count": count} for label, count in rows if count]


class V22DecisionCaseBuilder:
    def __init__(self, root: Path, *, built_at: datetime | None = None) -> None:
        self.root = root.resolve()
        resolved = built_at or datetime.now(timezone.utc).astimezone()
        if resolved.tzinfo is None:
            raise ValueError("built_at must include timezone")
        self.built_at = resolved
        self.baseline = load_json(self.root / "data/v2/decision-system.json")
        self.environment = load_json(self.root / "data/v2/v22/market-environment.json")
        self.environment_decision = load_json(self.root / "data/v2/v22/environment-decision.json")
        self.mainline = load_json(self.root / "data/v2/inputs/mainline-structure.json")
        quote_input = load_json(self.root / "data/v2/inputs/representative-stock-quotes.json")
        self.quotes = {
            str(item.get("code") or "").lower(): item
            for item in as_list(quote_input.get("quotes"))
            if isinstance(item, dict) and item.get("code")
        }
        self.g5 = {
            str(item.get("opportunity_id")): item
            for item in as_list(self.environment_decision.get("g5_links"))
            if isinstance(item, dict) and item.get("opportunity_id")
        }

    def build(self) -> tuple[dict[str, Any], dict[str, Any]]:
        raw_rows: list[tuple[str, dict[str, Any]]] = []
        for source_group in ("opportunity_radar", "validation_queue", "opportunity_history"):
            raw_rows.extend((source_group, item) for item in as_list(self.baseline.get(source_group)) if isinstance(item, dict))
        raw_rows.extend(("current_fact_observation", item) for item in self._current_fact_cards())
        grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for source_group, card in raw_rows:
            identity = normalized_identity(card.get("theme_id") or card.get("theme") or card.get("title"))
            grouped.setdefault(identity, []).append((source_group, card))
        cases = [self._case(key, occurrences) for key, occurrences in grouped.items()]
        cases.sort(key=lambda item: (item.get("ended", False), str(item.get("last_evidence_at") or ""), str(item.get("case_id"))), reverse=True)
        trade_date = str(self.environment.get("trade_date") or "unknown")
        all_active = [item for item in cases if not item.get("ended")]
        history = [item for item in cases if item.get("ended")]
        current = [item for item in all_active if item.get("maturity") == "decision_ready" and item.get("display_eligible")]
        validation = [item for item in all_active if item.get("maturity") != "decision_ready" and item.get("display_eligible")]
        all_unformed = [item for item in all_active if not item.get("display_eligible")]
        unformed = [item for item in all_unformed if has_current_clue_evidence(item, trade_date)]
        parked = [item for item in all_unformed if not has_current_clue_evidence(item, trade_date)]
        active = [*current, *validation, *unformed]
        source_material = {
            "baseline": canonical_hash(self.baseline),
            "environment": self.environment.get("immutable_hash"),
            "environment_decision": self.environment_decision.get("immutable_hash"),
            "policy_version": POLICY_VERSION,
        }
        batch_id = stable_id("decision_case_batch", canonical_hash(source_material), canonical_hash(cases), POLICY_VERSION)
        payload: dict[str, Any] = {
            "schema_version": 1,
            "mode": "shadow_only",
            "case_batch_id": batch_id,
            "trade_date": trade_date,
            "as_of": newest_time([item.get("last_evidence_at") for item in cases]) or self.environment.get("as_of"),
            "built_at": self.built_at.isoformat(timespec="seconds"),
            "policy_version": POLICY_VERSION,
            "source_material": source_material,
            "case_count": len(cases),
            "active_case_count": len(active),
            "decision_ready_count": len(current),
            "validation_case_count": len(validation),
            "unformed_clue_count": len(unformed),
            "parked_clue_count": len(parked),
            "history_case_count": len(history),
            "cases": cases,
            "current_case_ids": [item["case_id"] for item in current],
            "validation_case_ids": [item["case_id"] for item in validation],
            "unformed_clue_ids": [item["case_id"] for item in unformed],
            "parked_clue_ids": [item["case_id"] for item in parked],
            "history_case_ids": [item["case_id"] for item in history],
            "guardrails": {
                "baseline_v2_output_modified": False,
                "v1_modified": False,
                "automatic_trading": False,
                "user_assets_modified": False,
                "temporary_candidate_auto_upgraded": False,
                "decision_ready_equals_buy": False,
                "model_promoted": False,
            },
        }
        immutable_material = {key: value for key, value in payload.items() if key not in {"built_at", "immutable_hash"}}
        payload["immutable_hash"] = canonical_hash(immutable_material)
        by_id = {item["case_id"]: item for item in cases}
        candidate = {
            "schema_version": 1,
            "mode": "shadow_only",
            "candidate_version": POLICY_VERSION,
            "case_batch_id": batch_id,
            "trade_date": trade_date,
            "as_of": payload["as_of"],
            "built_at": payload["built_at"],
            "availability": "可用" if payload["immutable_hash"] else "暂不可用",
            "headline": "当前没有决策就绪案例" if not current else f"当前有{len(current)}个决策就绪案例",
            "summary": {
                "decision_ready": len(current),
                "awaiting_confirmation": len(validation),
                "unformed_clues": len(unformed),
                "parked_clues": len(parked),
                "history": len(history),
                "deduplicated_occurrences": len(raw_rows) - len(cases),
            },
            "current_cases": [self._user_case(by_id[case_id]) for case_id in payload["current_case_ids"]],
            "validation_cases": [self._user_case(by_id[case_id]) for case_id in payload["validation_case_ids"]],
            "history_cases": [self._user_case(by_id[case_id]) for case_id in payload["history_case_ids"]],
            "unformed_clue_summary": {
                "count": len(unformed),
                "parked_count": len(parked),
                "reason_breakdown": clue_gap_breakdown(all_unformed, trade_date),
                "explanation": "当日线索只有具备同日触发、代表股真实行情和有效时间，才会进入交易卡。",
                "impact": "历史待补线索已与当日结果隔离，不影响盘中判断，也不会被误当成机会。",
                "repair_rules": [
                    "补齐代表股代码、同日真实行情、角色和选择依据",
                    "记录同日实质触发与触发时点",
                    "明确加强条件、失效条件和本次判断有效时间",
                ],
            },
            "research_links": self._research_links(active),
            "guardrails": payload["guardrails"],
        }
        candidate["immutable_hash"] = canonical_hash({key: value for key, value in candidate.items() if key not in {"built_at", "immutable_hash"}})
        return payload, candidate

    def _current_fact_cards(self) -> list[dict[str, Any]]:
        trade_date = str(self.environment.get("trade_date") or "")
        as_of = self.environment.get("as_of")
        if not trade_date or not as_of or str(as_of)[:10] != trade_date or self.built_at.date().isoformat() != trade_date:
            return []
        cards: list[dict[str, Any]] = []
        summary = self.environment.get("dimension_summary") if isinstance(self.environment.get("dimension_summary"), dict) else {}
        suppress_count = int(summary.get("suppress") or 0) + int(summary.get("risk_release") or 0)
        if suppress_count:
            representatives = self._environment_representatives(trade_date)
            cards.append({
                "id": stable_id("current_fact_card", trade_date, "market_environment_risk"),
                "theme_id": f"market-environment-risk-{trade_date}",
                "theme": "市场环境风险",
                "title": "市场环境风险",
                "kind": "risk",
                "state": "candidate",
                "trigger": f"八维环境中有{suppress_count}项形成抑制",
                "conclusion": humanize(self.environment.get("conclusion") or "多维风险事实形成，降低追高许可。"),
                "representative_stocks": representatives,
                "evidence": [
                    {
                        "type": "market_environment",
                        "summary": humanize(item.get("conclusion")),
                        "source": humanize(item.get("label") or "市场环境事实"),
                        "as_of": item.get("as_of") or as_of,
                    }
                    for item in as_list(self.environment.get("dimensions"))
                    if isinstance(item, dict) and item.get("support_level") in {"suppress", "risk_release"}
                ],
                "counter_evidence": [humanize(item.get("conclusion")) for item in as_list(self.environment.get("dimensions")) if isinstance(item, dict) and item.get("support_level") in {"support", "partial_support"}],
                "risk_factors": [humanize(self.environment.get("action_constraint") or "市场风险尚未收敛")],
                "confirm_conditions": ["市场宽度、情绪和核心代表股至少两项继续走弱"],
                "invalidation_conditions": ["风险维度收敛，市场宽度和核心代表股转为同向承接"],
                "valid_until": f"{trade_date}T15:15:00+08:00",
                "as_of": as_of,
                "last_evidence_at": as_of,
                "source": "V2.2市场环境事实",
            })
        if str(self.mainline.get("trade_date") or "") == trade_date:
            mainline_as_of = self.mainline.get("as_of") or as_of
            for theme in as_list(self.mainline.get("themes")):
                if not isinstance(theme, dict) or theme.get("state") not in {"partial_support", "risk"}:
                    continue
                representatives = self._mainline_representatives(theme, trade_date)
                if not representatives:
                    continue
                title = humanize(theme.get("theme") or "行业结构")
                is_risk = theme.get("state") == "risk"
                cards.append({
                    "id": stable_id("current_fact_card", trade_date, title, theme.get("state")),
                    "theme_id": f"current-fact-{normalized_identity(title)}-{trade_date}",
                    "theme": title,
                    "title": title,
                    "kind": "risk" if is_risk else "opportunity",
                    "state": "candidate",
                    "trigger": humanize(theme.get("fact") or "涨跌停行业分布发生变化"),
                    "conclusion": humanize(theme.get("conclusion") or "等待行业宽度和成交确认"),
                    "representative_stocks": representatives,
                    "evidence": [{
                        "type": "price_limit_distribution",
                        "summary": humanize(theme.get("fact")),
                        "source": humanize(self.mainline.get("source_name") or "涨跌停行业分布"),
                        "as_of": mainline_as_of,
                    }],
                    "counter_evidence": [humanize(item) for item in as_list(self.mainline.get("counter_evidence"))],
                    "risk_factors": [humanize(item) for item in as_list(self.mainline.get("missing_evidence"))][:3],
                    "confirm_conditions": ["行业上涨宽度、成交和非涨停中军同向确认", "代表股在后续检查点保持同向"],
                    "invalidation_conditions": ["代表股转为背离", "涨跌停集中度消失或行业宽度反向"],
                    "valid_until": f"{trade_date}T15:15:00+08:00",
                    "as_of": mainline_as_of,
                    "last_evidence_at": mainline_as_of,
                    "source": "V2.2主线事实",
                })
        return cards

    def _environment_representatives(self, trade_date: str) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for ref in as_list(self.environment.get("evidence_refs")):
            if not isinstance(ref, dict) or ref.get("evidence_role") != "risk":
                continue
            for security in as_list(ref.get("representative_securities")):
                if isinstance(security, dict):
                    candidates.append(security)
        return self._verified_fact_representatives(candidates, trade_date)[:3]

    def _mainline_representatives(self, theme: dict[str, Any], trade_date: str) -> list[dict[str, Any]]:
        return self._verified_fact_representatives(
            [item for item in as_list(theme.get("representative_securities")) if isinstance(item, dict)],
            trade_date,
        )[:4]

    def _verified_fact_representatives(self, securities: list[dict[str, Any]], trade_date: str) -> list[dict[str, Any]]:
        rows = []
        seen = set()
        for security in securities:
            code = str(security.get("code") or "").lower()
            if not code.startswith(("sh", "sz", "bj")) or code in seen:
                continue
            quote = self.quotes.get(code)
            if not quote or str(quote.get("stock_quote_as_of") or "")[:10] != trade_date:
                continue
            if not isinstance(quote.get("stock_change_pct"), (int, float)):
                continue
            seen.add(code)
            rows.append({
                "name": quote.get("name") or security.get("name"),
                "stock_code": code,
                "stock_change_pct": quote.get("stock_change_pct"),
                "stock_quote_as_of": quote.get("stock_quote_as_of"),
                "stock_quote_source": quote.get("stock_quote_source"),
                "stock_quote_verification": quote.get("stock_quote_verification"),
                "cross_source_verified": quote.get("cross_source_verified"),
                "metric_state": "dual_source_confirmed" if quote.get("cross_source_verified") is True else "awaiting_cross_source_confirmation",
                "role": security.get("role") or "事实代表股",
                "basis": "来自当前交易日可审计市场事实；个股涨跌幅由独立行情字段计算。",
            })
        return rows

    def _case(self, key: str, occurrences: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        ranked = sorted(
            occurrences,
            key=lambda pair: (pair[0] == "opportunity_history", pair[0] == "validation_queue", str(source_time(pair[1]) or "")),
        )
        source_group, card = ranked[0] if any(pair[0] != "opportunity_history" for pair in ranked) else ranked[-1]
        active_occurrences = [pair for pair in occurrences if pair[0] != "opportunity_history"]
        if active_occurrences:
            source_group, card = sorted(active_occurrences, key=lambda pair: str(source_time(pair[1]) or ""))[-1]
        ended = not active_occurrences
        identity = key
        path = business_path(card)
        case_id = stable_id("decision_case", identity, POLICY_VERSION)
        original_id = str(card.get("id") or "")
        environment_gate = self.g5.get(original_id) or {
            "g5_result": "neutral",
            "reason": "历史案例不参与当前环境升级。" if ended else "环境门禁等待核验。",
            "effective_action": "仅保留观察",
        }
        sig_state = signal_state(card, ended)
        gates = evaluate_gates(
            card,
            business_path=path,
            environment_gate=environment_gate,
            overall_quality=str(self.baseline.get("data_quality_gate", {}).get("state") or "blocked"),
            ended=ended,
        )
        maturity = decision_maturity(gates, ended=ended, signal_state=sig_state, business_path=path)
        representatives = [item for item in as_list(card.get("representative_stocks")) if isinstance(item, dict)]
        display_eligible = bool(representatives) and all(quote_complete(item) for item in representatives)
        timeline = []
        for occurrence_group, occurrence in sorted(occurrences, key=lambda pair: str(source_time(pair[1]) or "")):
            timeline.append({
                "at": source_time(occurrence),
                "source_group": occurrence_group,
                "source_id": occurrence.get("id"),
                "signal_state": signal_state(occurrence, occurrence_group == "opportunity_history"),
                "conclusion_hash": canonical_hash(humanize(occurrence.get("conclusion") or occurrence.get("why_watch_summary") or occurrence.get("why_watch"))),
            })
        return {
            "case_id": case_id,
            "case_identity": identity,
            "business_path": path,
            "title": humanize(card.get("title") or card.get("theme") or card.get("theme_id") or "未命名线索"),
            "theme_id": card.get("theme_id"),
            "source_card_id": original_id,
            "source_group": source_group,
            "signal_state": sig_state,
            "maturity": maturity,
            "ended": ended,
            "display_eligible": display_eligible,
            "current_judgment": humanize(card.get("conclusion") or card.get("why_watch_summary") or card.get("why_watch") or "等待主题专属依据。"),
            "trigger": humanize(card.get("trigger") or "等待实质触发"),
            "trigger_metrics": card.get("trigger_metrics") if isinstance(card.get("trigger_metrics"), dict) else None,
            "representative_stocks": representatives,
            "evidence": as_list(card.get("evidence")),
            "evidence_refs": as_list(card.get("evidence_refs")),
            "counter_evidence": [humanize(item) for item in as_list(card.get("counter_evidence"))],
            "risk_factors": [humanize(item) for item in as_list(card.get("risk_factors"))],
            "confirm_conditions": [humanize(item) for item in as_list(card.get("confirm_conditions"))],
            "invalidation_conditions": [humanize(item) for item in as_list(card.get("invalidation_conditions"))],
            "valid_until": card.get("valid_until"),
            "last_evidence_at": source_time(card),
            "environment_gate": environment_gate,
            "gates": gates,
            "occurrence_count": len(occurrences),
            "timeline": timeline,
            "automatic_alert": False,
            "user_assets_modified": False,
        }

    def _user_case(self, case: dict[str, Any]) -> dict[str, Any]:
        maturity_labels = {
            "clue": "线索", "observe": "观察", "await_confirmation": "等待确认",
            "decision_ready": "决策就绪", "weakened": "减弱", "ended": "已结束",
        }
        signal_labels = {"candidate": "候选", "verified": "触发已核验", "invalidated": "已结束"}
        path_labels = {"theme_opportunity": "主题机会", "single_stock_event": "单股事件", "cross_market_mapping": "外盘映射", "risk_path": "风险路径"}
        maturity = str(case.get("maturity"))
        g5_result = str(case.get("environment_gate", {}).get("g5_result") or "neutral")
        if maturity == "ended":
            action = "已结束，仅供复盘"
        elif g5_result in {"suppress", "block"} or maturity == "weakened":
            action = "不追，等待风险释放"
        elif maturity == "decision_ready":
            action = "积极关注，但仍由用户决定"
        elif maturity == "clue":
            action = "降低关注，仅保留线索"
        else:
            action = "等待确认"
        missing_gates = [item for item in as_list(case.get("gates")) if item.get("state") not in {"pass", "not_applicable"}]
        return {
            "id": case.get("case_id"),
            "title": case.get("title"),
            "theme": case.get("title"),
            "path_label": path_labels.get(case.get("business_path"), "观察线索"),
            "signal_label": signal_labels.get(case.get("signal_state"), "候选"),
            "maturity_label": maturity_labels.get(maturity, "等待确认"),
            "status": "waiting" if maturity not in {"decision_ready", "ended"} else ("confirmed" if maturity == "decision_ready" else "invalidated"),
            "state": "candidate" if maturity not in {"decision_ready", "ended"} else ("confirmed" if maturity == "decision_ready" else "invalidated"),
            "kind": "risk" if case.get("business_path") == "risk_path" else "opportunity",
            "trigger": case.get("trigger"),
            "trigger_metrics": case.get("trigger_metrics"),
            "current_judgment": case.get("current_judgment"),
            "conclusion": case.get("current_judgment"),
            "why_watch_summary": case.get("current_judgment"),
            "action": action,
            "representative_stocks": case.get("representative_stocks"),
            "evidence": case.get("evidence"),
            "evidence_refs": case.get("evidence_refs"),
            "counter_evidence": case.get("counter_evidence"),
            "risk_factors": case.get("risk_factors") or case.get("counter_evidence"),
            "confirm_conditions": case.get("confirm_conditions"),
            "invalidation_conditions": case.get("invalidation_conditions"),
            "valid_until": case.get("valid_until"),
            "valid_window_display": f"本次判断有效至 {case.get('valid_until')}" if case.get("valid_until") else "有效时间待补，不能进入决策就绪",
            "environment_gate": case.get("environment_gate"),
            "waiting_reasons": [{"label": item.get("label"), "conclusion": item.get("conclusion")} for item in missing_gates],
            "last_evidence_at": case.get("last_evidence_at"),
        }

    @staticmethod
    def _research_links(active: list[dict[str, Any]]) -> list[dict[str, Any]]:
        domains = {
            "AI硬件": ("半导体", "存储", "HBM", "CPO", "光模块", "算力", "PCB", "封装"),
            "AI软件": ("软件", "模型", "Agent", "信创"),
            "具身智能": ("机器人", "自动化", "具身"),
            "医药": ("医药", "创新药", "中药", "CXO", "CRO"),
            "核聚变": ("核聚变",),
            "量子科技": ("量子",),
        }
        rows = []
        for domain, keywords in domains.items():
            matching = [item for item in active if any(keyword.lower() in str(item.get("title") or "").lower() for keyword in keywords)]
            rows.append({"domain": domain, "active_case_count": len(matching), "case_ids": [item.get("case_id") for item in matching], "note": "研究页只显示关联数量，不维护盘中状态。"})
        return rows

    def write(self) -> tuple[dict[str, Any], dict[str, Any]]:
        payload, candidate = self.build()
        snapshot = self.root / "data/v2/v22/decision-case-snapshots" / str(payload["trade_date"]) / f"{payload['case_batch_id']}.json"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        if snapshot.exists():
            existing = load_json(snapshot)
            if existing.get("immutable_hash") != payload.get("immutable_hash"):
                raise ValueError("immutable decision case snapshot conflict")
        else:
            snapshot.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output = self.root / PUBLIC_OUTPUT
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (self.root / CANDIDATE_OUTPUT).write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._write_index(payload, snapshot)
        return payload, candidate

    def _write_index(self, payload: dict[str, Any], snapshot: Path) -> None:
        path = self.root / SNAPSHOT_INDEX
        existing = load_json(path)
        rows = [item for item in as_list(existing.get("snapshots")) if isinstance(item, dict)]
        if not any(item.get("case_batch_id") == payload.get("case_batch_id") for item in rows):
            rows.append({
                "case_batch_id": payload.get("case_batch_id"),
                "trade_date": payload.get("trade_date"),
                "as_of": payload.get("as_of"),
                "case_count": payload.get("case_count"),
                "immutable_hash": payload.get("immutable_hash"),
                "relative_path": str(snapshot.relative_to(self.root)),
            })
        rows.sort(key=lambda item: (str(item.get("as_of") or ""), str(item.get("case_batch_id") or "")))
        path.write_text(json.dumps({"schema_version": 1, "generated_at": now_iso(), "snapshot_count": len(rows), "snapshots": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

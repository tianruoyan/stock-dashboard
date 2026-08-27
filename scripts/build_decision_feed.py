#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.trading_context import resolve_cn_trading_context

DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "decision-feed.json"
TZ = timezone(timedelta(hours=8))


def main() -> int:
    files = {
        name: load_json(DATA_DIR / name)
        for name in (
            "alert.json",
            "intraday.json",
            "midday.json",
            "postmarket.json",
            "topics.json",
            "quality-report.json",
            "source-health.json",
            "theme-shifts.json",
            "opportunity-watch.json",
        )
    }
    now = datetime.now(TZ)
    context = resolve_cn_trading_context(ROOT, now, [latest_signal_date(files)])
    signal_date = context.market_date.isoformat()
    opportunities = rank_upgrade_candidates(dedupe_items(build_opportunities(files, signal_date)))[:8]
    risks = dedupe_items(build_risks(files, signal_date))[:8]
    verifications = dedupe_items(build_verifications(files, signal_date))[:8]
    conflicts = build_signal_conflicts(opportunities, risks, verifications)
    feed = {
        "timestamp": now.astimezone(TZ).replace(microsecond=0).isoformat(),
        "current_signal_date": signal_date,
        "target_trade_date": context.target_trade_date.isoformat(),
        "calendar_version": context.calendar_version,
        "quality_gate": quality_gate(files.get("quality-report.json") or {}),
        "summary": build_summary(files, signal_date),
        "observation_coverage": build_observation_coverage(opportunities, risks, verifications),
        "decision_brief": build_decision_brief(opportunities, risks, verifications, conflicts, files),
        "signal_queue": build_signal_queue(opportunities, risks, verifications, conflicts),
        "opportunities": opportunities,
        "risks": risks,
        "verifications": verifications,
        "conflicts": conflicts,
        "rules": [
            "每条机会/风险必须带 source_files；没有证据时置信度不得高于 low。",
            "机会只代表候选方向，必须经过下一步验证，不生成交易指令。",
            "quality-report 为 degraded/critical 时，所有机会必须带 quality_flags 并自动降权。",
            "每条信号必须输出 signal_grade/use_action/use_reasons，前端按可用性而不是标题强弱展示。",
            "每条信号必须输出 discovery_type/evidence_score/missing_evidence，用于区分主动发现、继承专题、风险兜底和证据缺口。",
            "每条信号必须输出 trigger_reason，用一句话解释为什么系统把它推到雷达。",
            "每条信号必须输出 next_action，把证据缺口翻译成下一交易窗口可执行检查。",
            "每条机会必须输出 upgrade_rank/upgrade_priority/upgrade_condition，降权后进入验证栏也要保留升级排序和升级门槛。",
            "同一主线同时出现在机会、风险或验证栏时，必须输出 conflicts，给出风险优先/仅验证/可升级的统一判定。",
            "theme-shifts 用于识别升温、新线、抱团、降温和风险变化，并进入机会/风险/验证栏。",
            "observation_coverage 必须说明主动扫描、盘后扫描、专题继承和验证队列占比，避免雷达只复述既有配置。",
            "decision_brief 必须给出一句话站位、依据、风险焦点和升级条件，作为盘中交易口径入口。",
            "signal_queue 必须把可用机会、可跟踪风险、仅验证和禁用信号拆开，避免用户把降权候选误当机会。",
        ],
    }
    OUT.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"decision-feed: {len(feed['opportunities'])} opportunities, {len(feed['risks'])} risks, {len(feed['verifications'])} verifications")
    return 0


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_summary(files: dict[str, Any], current_date: str) -> str:
    midday = current_payload(files, "midday.json", current_date)
    intraday = current_payload(files, "intraday.json", current_date)
    post = current_payload(files, "postmarket.json", current_date)
    quality = files.get("quality-report.json") or {}
    candidates = [
        (
            str(midday.get("timestamp") or ""),
            first_text(midday.get("morning_review", {}).get("one_sentence")),
        ),
        (
            str(intraday.get("timestamp") or ""),
            first_text(intraday.get("summary")),
        ),
        (
            str(post.get("timestamp") or ""),
            first_text(
                post.get("review", {}).get("one_sentence"),
                post.get("index", {}).get("summary"),
            ),
        ),
    ]
    current_summaries = [item for item in candidates if item[0] and item[1]]
    base = max(current_summaries, key=lambda item: item[0])[1] if current_summaries else "当前时段尚无可用盘面结论。"
    if quality.get("status") in {"degraded", "critical"}:
        return trim(f"{base} 数据质量：{quality.get('summary')}", 180)
    return trim(base, 180)


def build_decision_brief(
    opportunities: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    verifications: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    files: dict[str, Any],
) -> dict[str, Any]:
    quality_report = files.get("quality-report.json") or {}
    quality = quality_gate(quality_report)
    actionable = [item for item in opportunities if item.get("signal_grade") in {"A", "B"} and not re.search(r"仅复核|降权|等待", str(item.get("use_action") or ""))]
    high_risks = [item for item in risks if item.get("signal_grade") in {"A", "B"}]
    risk_first = [item for item in conflicts if item.get("severity") == "risk_first"]
    upgrade_candidates = [item for item in opportunities if item.get("upgrade_rank")]
    quality_actions = quality_action_items(quality_report)
    if risk_first or (not actionable and opportunities):
        stance = "风险优先，只做验证"
        action = "不把候选方向当交易机会；先看风险收敛、数据恢复和核心承接。"
    elif actionable:
        stance = "存在可跟踪机会"
        action = "只按验证条件跟踪，不追无证据扩散。"
    elif high_risks:
        stance = "无明确机会，控制回撤"
        action = "优先处理风险项，等待新线或主线重新确认。"
    else:
        stance = "等待确认"
        action = "继续观察主动扫描和验证队列。"

    reasons = clean_list([
        quality.get("summary") if quality.get("status") in {"degraded", "critical"} else "",
        f"A/B级风险 {len(high_risks)} 条" if high_risks else "",
        f"风险优先冲突 {len(risk_first)} 条" if risk_first else "",
        f"可用机会 {len(actionable)} 条，降权候选 {max(0, len(opportunities) - len(actionable))} 条",
        f"先处理：{quality_actions[0]['label']}（{quality_actions[0]['file']}）" if quality_actions else "",
    ])[:4]
    risk_focus = [item.get("title") for item in high_risks[:3] if item.get("title")]
    upgrade_watch = [
        f"#{item.get('upgrade_rank')} {item.get('title')}：{item.get('upgrade_condition')}"
        for item in upgrade_candidates[:3]
        if item.get("title") and item.get("upgrade_condition")
    ]
    verification_focus = [
        item.get("next_action") or first_text(*(item.get("watch_next") or []))
        for item in verifications[:3]
    ]
    return {
        "stance": stance,
        "action": action,
        "reasons": reasons,
        "risk_focus": risk_focus,
        "upgrade_watch": clean_list(upgrade_watch)[:3],
        "verification_focus": clean_list(verification_focus)[:3],
        "quality_actions": quality_actions,
    }


def quality_action_items(quality_report: dict[str, Any]) -> list[dict[str, str]]:
    actions = quality_report.get("action_plan") if isinstance(quality_report, dict) else []
    if not isinstance(actions, list):
        return []
    rows: list[dict[str, str]] = []
    for item in actions:
        if not isinstance(item, dict):
            continue
        rows.append({
            "label": trim(first_text(item.get("label"), item.get("impact_level"), "处置"), 18),
            "file": trim(first_text(item.get("file"), "quality-report.json"), 32),
            "next_step": trim(first_text(item.get("next_step"), item.get("decision_action"), item.get("problem")), 110),
            "unblock_condition": trim(first_text(item.get("unblock_condition"), ""), 90),
        })
    return rows[:2]


def build_signal_queue(
    opportunities: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    verifications: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    active_opportunities = [
        queue_item(item, "可跟踪机会")
        for item in opportunities
        if item.get("signal_grade") in {"A", "B"} and not re.search(r"仅复核|降权|等待", str(item.get("use_action") or ""))
    ][:3]
    trackable_risks = [
        queue_item(item, "优先风险")
        for item in risks
        if item.get("signal_grade") in {"A", "B"}
    ][:4]
    verification_queue = [
        queue_item(item, "等待确认")
        for item in [
            *[op for op in opportunities if op.get("signal_grade") in {"C", "D"} or re.search(r"仅复核|降权|等待", str(op.get("use_action") or ""))],
            *verifications,
        ]
    ][:5]
    disabled_signals = []
    if any(item.get("severity") == "risk_first" for item in conflicts):
        disabled_signals.append({
            "title": "冲突主线机会",
            "use_action": "禁用追高",
            "reason": "同一主线存在风险优先冲突，只保留验证条件，不作为交易触发。",
        })
    disabled_signals.extend([
        queue_item(item, "禁用直用")
        for item in opportunities
        if item.get("quality_flags") and item.get("signal_grade") == "D"
    ][:3])
    return {
        "summary": signal_queue_summary(active_opportunities, trackable_risks, verification_queue, disabled_signals),
        "active_opportunities": active_opportunities,
        "trackable_risks": trackable_risks,
        "verification_queue": verification_queue,
        "disabled_signals": disabled_signals[:4],
    }


def queue_item(item: dict[str, Any], default_action: str) -> dict[str, str]:
    return {
        "title": trim(item.get("title") or "未命名信号", 36),
        "grade": trim(item.get("signal_grade") or "-", 4),
        "use_action": trim(item.get("use_action") or default_action, 18),
        "reason": trim(first_text(item.get("next_action"), item.get("conclusion"), *(item.get("watch_next") or [])), 100),
    }


def signal_queue_summary(active: list[dict[str, Any]], risks: list[dict[str, Any]], verify: list[dict[str, Any]], disabled: list[dict[str, Any]]) -> str:
    if active:
        return f"{len(active)} 条机会可跟踪，{len(risks)} 条风险优先，{len(verify)} 条只做验证。"
    return f"无可用机会，{len(risks)} 条风险优先，{len(verify)} 条只做验证，{len(disabled)} 条禁用直用。"


def build_opportunities(files: dict[str, Any], current_date: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    quality = files.get("quality-report.json") or {}
    gate = quality_gate(quality)
    quality_degraded = gate["status"] in {"degraded", "critical"}

    for theme, source in risk_theme_candidates(files, current_date):
        if is_generic_bucket(theme):
            continue
        text = compact_json(theme)
        if has_stale_relative_time(text, current_date):
            continue
        status = trend_status(theme)
        if not is_opportunity_text(status, text):
            continue
        evidence = evidence_from(theme)
        confidence = confidence_from(evidence, text, quality_degraded)
        items.append(decision_item(
            title=theme_name(theme),
            item_type="theme",
            conclusion=first_text(theme.get("conclusion"), theme.get("continuity"), theme.get("note"), status, "强线候选，需验证扩散和承接。"),
            confidence=confidence,
            evidence=evidence,
            watch_next=watch_next_from(theme),
            invalidation=invalidation_for(theme, mode="opportunity"),
            tags=related_tags(text),
            source_files=[source],
            tone="good",
            discovery_type=discovery_type_for(source, theme, "opportunity"),
            quality_flags=gate["decision_flags"] if quality_degraded else [],
        ))

    for shift in theme_shift_candidates(files, {"warming", "emerging"}, current_date):
        shift_text = " ".join([shift.get("theme", ""), shift.get("conclusion", ""), shift.get("risk", "")])
        items.append(decision_item(
            title=f"主线变化：{shift.get('theme')}",
            item_type="theme_shift",
            conclusion=shift.get("conclusion") or "主线有边际升温迹象。",
            confidence="low" if quality_degraded else "medium",
            evidence=shift.get("evidence") or [],
            watch_next=shift.get("watch_next") or [],
            invalidation=shift.get("risk") or "次日不能继续扩散或核心股冲高回落，则降级为观察。",
            tags=related_tags(shift_text),
            source_files=shift.get("source_files") or ["theme-shifts.json"],
            tone="good",
            discovery_type="theme_shift_scan",
            quality_flags=clean_list([*(gate["decision_flags"] if quality_degraded else []), *(shift.get("quality_flags") or [])]),
        ))

    existing_titles = {item.get("title") for item in items}
    for theme in unplanned_theme_candidates(files, existing_titles, current_date):
        text = compact_json(theme)
        items.append(decision_item(
            title=f"新线观察：{theme_name(theme)}",
            item_type="unplanned_theme",
            conclusion=first_text(theme.get("continuity"), theme.get("note"), theme.get("status"), "盘面出现非预设活跃方向，需要验证是否从轮动变主线。"),
            confidence="low" if quality_degraded else "medium",
            evidence=evidence_from(theme),
            watch_next=watch_next_from(theme),
            invalidation=f"{theme_name(theme)}次日不能继续高开承接、涨停池收缩或代表股冲高回落，则只按一日轮动处理。",
            tags=related_tags(text) or ["新线观察"],
            source_files=["postmarket.json"],
            tone="good",
            discovery_type="active_market_scan",
            trigger_reason=f"非预设盘面扫描触发：{theme_name(theme)}不在既有专题精确清单中，但出现涨停池/强势组/轮动增强证据。",
            quality_flags=gate["decision_flags"] if quality_degraded else [],
        ))

    post = current_payload(files, "postmarket.json", current_date)
    for stock in strong_stock_candidates(post):
        items.append(decision_item(
            title=stock["title"],
            item_type="stock",
            conclusion=stock["conclusion"],
            confidence="medium" if not quality_degraded else "low",
            evidence=stock["evidence"],
            watch_next=stock["watch_next"],
            invalidation="次日不能高开承接或所在板块未扩散，则只作个股情绪，不升级主线。",
            tags=related_tags(stock["conclusion"]),
            source_files=["postmarket.json"],
            tone="good",
            discovery_type="active_stock_scan",
            quality_flags=gate["decision_flags"] if quality_degraded else [],
        ))

    for watch in opportunity_watch_candidates(files):
        text = compact_json(watch)
        items.append(decision_item(
            title=f"待触发：{watch.get('theme')}",
            item_type="opportunity_watch",
            conclusion=first_text(watch.get("source_reason"), "盘前/晚间线索等待盘中量价触发。"),
            confidence="low",
            evidence=watch.get("evidence") or [],
            watch_next=watch.get("confirm_rules") or [],
            invalidation=first_text(*(watch.get("invalidate_rules") or []), "未出现短周期量价、成交或扩散确认。"),
            tags=related_tags(text) or [watch.get("theme")],
            source_files=["opportunity-watch.json"],
            tone="good",
            discovery_type="premarket_watch_queue",
            trigger_reason="盘前/晚间注意点已转为盘中追踪清单，等待实时行情触发。",
            quality_flags=gate["decision_flags"] if quality_degraded else [],
        ))
    return items


def opportunity_watch_candidates(files: dict[str, Any]) -> list[dict[str, Any]]:
    data = files.get("opportunity-watch.json") or {}
    rows = data.get("items") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []
    return [row for row in rows[:8] if isinstance(row, dict) and row.get("theme")]


def rank_upgrade_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(items, key=upgrade_sort_score, reverse=True)
    for index, item in enumerate(ranked, 1):
        item["upgrade_rank"] = index
        item["upgrade_priority"] = upgrade_priority_for(item)
        item["upgrade_condition"] = upgrade_condition_for(item)
    return ranked


def upgrade_sort_score(item: dict[str, Any]) -> float:
    score = number(item.get("evidence_score")) * 0.55 + number(item.get("signal_score")) * 0.35
    if item.get("discovery_type") in {"active_market_scan", "theme_shift_scan", "active_stock_scan"}:
        score += 8
    if item.get("watch_next"):
        score += 5
    if item.get("quality_flags"):
        score -= min(12, 4 + len(clean_list(item.get("quality_flags"))) * 2)
    if item.get("use_action") == "仅复核":
        score -= 10
    if item.get("tone") == "risk":
        score -= 20
    return score


def upgrade_priority_for(item: dict[str, Any]) -> str:
    grade = str(item.get("signal_grade") or "").upper()
    action = str(item.get("use_action") or "")
    score = upgrade_sort_score(item)
    if "仅复核" in action or grade == "D":
        return "仅复核"
    if score >= 65:
        return "优先验证"
    if score >= 50:
        return "观察验证"
    return "低优先"


def upgrade_condition_for(item: dict[str, Any]) -> str:
    parts: list[str] = []
    next_action = str(item.get("next_action") or "").strip()
    if next_action:
        parts.append(next_action)
    else:
        parts.append("先看板块扩散、核心股承接和尾盘方向是否同向确认。")
    missing = "；".join(clean_list(item.get("missing_evidence") or []))
    if "量化盘口" in missing:
        parts.append("补齐涨停/封板数量、成交放大和尾盘承接证据。")
    if "代表股" in missing:
        parts.append("至少2-3只核心股强于板块ETF或指数。")
    if item.get("quality_flags"):
        parts.append("数据质量恢复或二次行情源确认前，不升级为可用机会。")
    return trim(" ".join(ensure_sentence(part) for part in unique_keep_order(parts) if part), 220)


def ensure_sentence(text: str) -> str:
    value = str(text or "").strip().rstrip("；;")
    if not value:
        return ""
    return value if value.endswith(("。", "！", "？")) else f"{value}。"


def risk_theme_candidates(files: dict[str, Any], current_date: str) -> list[tuple[dict[str, Any], str]]:
    rows: list[tuple[dict[str, Any], str]] = []
    for item in as_list(current_payload(files, "postmarket.json", current_date).get("hotspots")):
        if isinstance(item, dict):
            rows.append((item, "postmarket.json"))
    intraday = current_payload(files, "intraday.json", current_date)
    for item in as_list(intraday.get("main_trends")) + as_list(intraday.get("themes")):
        if isinstance(item, dict):
            rows.append((item, "intraday.json"))
    midday = current_payload(files, "midday.json", current_date)
    for item in as_list(midday.get("morning_review", {}).get("main_trends")):
        if isinstance(item, dict):
            rows.append((item, "midday.json"))
    for item in as_list(current_payload(files, "topics.json", current_date).get("topics")):
        if isinstance(item, dict):
            rows.append((item, "topics.json"))
    return rows


def unplanned_theme_candidates(files: dict[str, Any], existing_titles: set[str], current_date: str) -> list[dict[str, Any]]:
    topics = files.get("topics.json") or {}
    post = current_payload(files, "postmarket.json", current_date)
    known = {theme_name(item) for item in as_list(topics.get("topics")) if isinstance(item, dict)}
    rows: list[dict[str, Any]] = []
    for item in as_list(post.get("hotspots")):
        if not isinstance(item, dict):
            continue
        name = theme_name(item)
        text = compact_json(item)
        state_text = " ".join(str(item.get(key) or "") for key in ("name", "status", "continuity", "note"))
        tags = related_tags(text)
        if name in known or name in existing_titles or is_generic_bucket(item):
            continue
        if tags and any(tag in known for tag in tags) and not re.search(r"低位|消费电子|元件|首次|轮动增强", state_text):
            continue
        if re.search(r"风险线|弱化|退潮|反抽失败|证伪", state_text):
            continue
        has_activity = re.search(r"涨停池|8%以上|5%-8%|封板|涨停|轮动增强|低位轮动|强势组", text)
        has_representatives = len(as_list(item.get("stocks"))) >= 3 or len(evidence_from(item)) >= 2
        if has_activity and has_representatives:
            rows.append(item)
    return rows[:3]


def build_risks(files: dict[str, Any], current_date: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    post = current_payload(files, "postmarket.json", current_date)
    intraday = current_payload(files, "intraday.json", current_date)
    quality = files.get("quality-report.json") or {}

    breadth = market_breadth_risk(post, intraday)
    if breadth:
        items.append(breadth)

    if quality.get("status") in {"degraded", "critical"}:
        items.append(decision_item(
            title="数据质量降级",
            item_type="data_quality",
            conclusion=quality.get("summary") or "数据源存在降级或需复核项。",
            confidence="high",
            evidence=[issue.get("message", "") for issue in quality.get("issues", []) if issue.get("severity") in {"critical", "warning"}][:4],
            watch_next=["污染 alert 修复前，盘中异动信号必须降权；观察池个股涨跌幅以已审计源为准。"],
            invalidation="审计报告恢复 ok 且 source-health 不再提示关键行情源降级。",
            tags=["数据质量", "风控"],
            source_files=["quality-report.json", "source-health.json"],
            tone="risk",
            discovery_type="risk_guardrail",
        ))

    for theme, source in risk_theme_candidates(files, current_date):
        if is_generic_bucket(theme):
            continue
        text = compact_json(theme)
        status = trend_status(theme)
        if not is_risk_text(status, text):
            continue
        items.append(decision_item(
            title=theme_name(theme),
            item_type="theme",
            conclusion=first_text(theme.get("risk"), theme.get("continuity"), theme.get("note"), status, "风险线需继续观察。"),
            confidence=confidence_from(evidence_from(theme), text, False),
            evidence=evidence_from(theme),
            watch_next=watch_next_from(theme),
            invalidation=invalidation_for(theme, mode="risk"),
            tags=related_tags(text),
            source_files=[source],
            tone="risk",
            discovery_type=discovery_type_for(source, theme, "risk"),
        ))

    for shift in theme_shift_candidates(files, {"risk", "crowded", "fading"}, current_date):
        shift_text = " ".join([shift.get("theme", ""), shift.get("conclusion", ""), shift.get("risk", "")])
        items.append(decision_item(
            title=f"主线变化：{shift.get('theme')}",
            item_type="theme_shift",
            conclusion=shift.get("conclusion") or shift.get("risk") or "主线边际转弱，需要降权。",
            confidence="high" if shift.get("state") in {"risk", "crowded"} and number(shift.get("score")) >= 70 else "medium",
            evidence=shift.get("evidence") or [],
            watch_next=shift.get("watch_next") or [],
            invalidation="风险信号收敛、后排扩散恢复且核心股放量承接。",
            tags=related_tags(shift_text),
            source_files=shift.get("source_files") or ["theme-shifts.json"],
            tone="risk",
            discovery_type="theme_shift_scan",
        ))

    return items


def build_verifications(files: dict[str, Any], current_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    intraday = current_payload(files, "intraday.json", current_date)
    midday = current_payload(files, "midday.json", current_date)
    post = current_payload(files, "postmarket.json", current_date)
    candidates = [
        ("intraday.json", intraday.get("actions")),
        ("midday.json", midday.get("afternoon_watch")),
        ("postmarket.json", post.get("next_day_watch")),
        ("postmarket.json", post.get("closing_auction_patch", {}).get("watch_next_day")),
    ]
    for shift in theme_shift_candidates(files, {"warming", "emerging", "risk", "crowded", "fading"}, current_date):
        candidates.append(("theme-shifts.json", shift.get("watch_next")))
    for watch in opportunity_watch_candidates(files)[:6]:
        title = watch.get("theme") or "盘中机会追踪"
        rows.append(decision_item(
            title=f"盘中追踪：{title}",
            item_type="opportunity_watch",
            conclusion=trim(first_text(watch.get("source_reason"), "盘前/晚间线索等待盘中量价触发。"), 150),
            confidence="low",
            evidence=watch.get("evidence") or [],
            watch_next=watch.get("confirm_rules") or [],
            invalidation=first_text(*(watch.get("invalidate_rules") or []), "未出现短周期量价、成交或扩散确认。"),
            tags=related_tags(compact_json(watch)) or [title],
            source_files=["opportunity-watch.json"],
            tone="neutral",
            discovery_type="premarket_watch_queue",
            trigger_reason="盘前/晚间注意点已转为盘中追踪清单，等待实时行情触发。",
        ))
    for source, values in candidates:
        for text in text_items(values):
            rows.append(decision_item(
                title=verification_title(text),
                item_type="verification",
                conclusion=trim(text, 150),
                confidence="actionable",
                evidence=[],
                watch_next=[trim(text, 150)],
                invalidation="条件不出现或反向出现，即撤销对应方向判断。",
                tags=related_tags(text),
                source_files=[source],
                tone="risk" if re.search(r"风险|跌停|弱|回落|低开|降级", text) else "neutral",
                discovery_type="verification_queue",
            ))
    return rows


def theme_shift_candidates(files: dict[str, Any], states: set[str], current_date: str) -> list[dict[str, Any]]:
    rows = files.get("theme-shifts.json", {}).get("shifts") if isinstance(files.get("theme-shifts.json"), dict) else []
    if not isinstance(rows, list):
        return []
    return [
        row for row in rows
        if isinstance(row, dict)
        and row.get("state") in states
        and derived_sources_current(files, row, current_date)
    ]


def theme_candidates(files: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    rows: list[tuple[dict[str, Any], str]] = []
    for item in as_list(files.get("topics.json", {}).get("topics")):
        if isinstance(item, dict):
            rows.append((item, "topics.json"))
    for item in as_list(files.get("postmarket.json", {}).get("hotspots")):
        if isinstance(item, dict):
            rows.append((item, "postmarket.json"))
    for item in as_list(files.get("intraday.json", {}).get("main_trends")) + as_list(files.get("intraday.json", {}).get("themes")):
        if isinstance(item, dict):
            rows.append((item, "intraday.json"))
    return rows


def strong_stock_candidates(post: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for theme in as_list(post.get("hotspots")):
        if not isinstance(theme, dict):
            continue
        for stock in as_list(theme.get("stocks")):
            if not isinstance(stock, dict):
                continue
            name = stock.get("name") or stock.get("symbol")
            pct = stock.get("change_pct")
            note = first_text(stock.get("note"), stock.get("reason"), stock.get("status"))
            if not name:
                continue
            text = compact_json(stock)
            if re.search(r"涨停|封板|大涨|放量|领涨|强势", text) or number(pct) >= 5:
                rows.append({
                    "title": str(name),
                    "conclusion": trim(f"{name}在{theme_name(theme)}中表现强，{note}", 140),
                    "evidence": clean_list([f"{name}涨跌幅 {pct}%" if pct is not None else note]),
                    "watch_next": [f"看{name}次日竞价和开盘30分钟承接，以及{theme_name(theme)}是否扩散。"],
                })
    return rows


def market_breadth_risk(post: dict[str, Any], intraday: dict[str, Any]) -> dict[str, Any] | None:
    text = compact_json([post.get("index"), post.get("market_breadth"), intraday.get("sentiment")])
    down5 = first_number_after(text, "跌5%以上")
    limit_down = first_number_after(text, "跌停")
    broken = first_number_after(text, "炸板")
    if max(down5, limit_down, broken) <= 0:
        return None
    if down5 >= 500 or limit_down >= 20 or broken >= 20:
        evidence = []
        if down5:
            evidence.append(f"跌5%以上约{down5}只")
        if limit_down:
            evidence.append(f"跌停约{limit_down}只")
        if broken:
            evidence.append(f"炸板约{broken}只")
        return decision_item(
            title="全市场亏钱效应",
            item_type="market_breadth",
            conclusion="跌停、炸板或大跌家数偏高，强线不能外推成全面进攻。",
            confidence="high",
            evidence=evidence,
            watch_next=["次日先看跌停/炸板是否收敛，再判断强线能否从抱团转扩散。"],
            invalidation="跌停和炸板显著回落，同时涨停扩散到多个新方向。",
            tags=["仓位", "风控"],
            source_files=["postmarket.json", "intraday.json"],
            tone="risk",
            discovery_type="risk_guardrail",
        )
    return None


def trader_text(value: Any) -> str:
    text = str(value or "")
    return text.replace("医药修复链", "创新药/CRO").replace("老登风格切换", "金融/消费防御")


def decision_item(**kwargs: Any) -> dict[str, Any]:
    evidence = clean_list([trader_text(value) for value in (kwargs.get("evidence") or [])])
    watch_next = clean_list([trader_text(value) for value in (kwargs.get("watch_next") or [])])
    sources = clean_list(kwargs.get("source_files") or [])
    invalidation = trader_text(kwargs.get("invalidation") or "等待反向量价信号确认。")
    missing = missing_evidence_for(kwargs.get("item_type") or "signal", evidence, watch_next, sources, kwargs.get("quality_flags") or [])
    evidence_score = evidence_score_for(evidence, watch_next, sources, invalidation, missing)
    confidence = kwargs.get("confidence") or ("medium" if evidence else "low")
    if not evidence and confidence == "high":
        confidence = "medium"
    item = {
        "title": trim(trader_text(kwargs.get("title") or "未命名信号"), 40),
        "type": kwargs.get("item_type") or "signal",
        "trigger_reason": trim(kwargs.get("trigger_reason") or trigger_reason_for(kwargs, evidence, watch_next), 120),
        "conclusion": trim(trader_text(kwargs.get("conclusion") or ""), 180),
        "confidence": confidence,
        "evidence": evidence[:5],
        "source_files": sources[:4],
        "watch_next": watch_next[:4],
        "invalidation": trim(invalidation, 140),
        "tags": clean_list([trader_text(value) for value in (kwargs.get("tags") or [])])[:5],
        "quality_flags": clean_list(kwargs.get("quality_flags") or [])[:4],
        "tone": kwargs.get("tone") or "neutral",
        "discovery_type": kwargs.get("discovery_type") or "derived_signal",
        "evidence_score": evidence_score,
        "missing_evidence": missing[:5],
        "next_action": trim(next_action_for(kwargs.get("item_type") or "signal", watch_next, missing, kwargs.get("tone") or "neutral"), 180),
    }
    item["observation_source"] = observation_source_label(item.get("discovery_type"), sources)
    item["independent_observation"] = is_independent_observation(item.get("discovery_type"), sources)
    item.update(signal_usability(item))
    return item


def build_observation_coverage(opportunities: list[dict[str, Any]], risks: list[dict[str, Any]], verifications: list[dict[str, Any]]) -> dict[str, Any]:
    all_items = opportunities + risks + verifications
    independent = [item for item in all_items if item.get("independent_observation")]
    inherited = [item for item in all_items if not item.get("independent_observation")]
    active_market = [item for item in all_items if item.get("discovery_type") in {"active_market_scan", "active_stock_scan"}]
    postmarket_scan = [item for item in all_items if item.get("discovery_type") in {"postmarket_theme_scan", "postmarket_risk_scan"}]
    topic_inherited = [item for item in all_items if item.get("discovery_type") == "topic_watch_scan"]
    verification = [item for item in all_items if item.get("discovery_type") == "verification_queue"]
    active_titles = [item.get("title") for item in active_market[:4] if item.get("title")]
    if active_titles:
        summary = f"主动扫描捕捉 {len(active_market)} 条：{' / '.join(active_titles)}"
    elif independent:
        summary = f"独立盘面/盘后扫描 {len(independent)} 条，但缺少纯主动新线。"
    else:
        summary = "当前雷达主要来自专题/配置继承，缺少独立盘面发现，需降权使用。"
    return {
        "summary": summary,
        "independent_count": len(independent),
        "inherited_count": len(inherited),
        "active_market_count": len(active_market),
        "postmarket_scan_count": len(postmarket_scan),
        "topic_inherited_count": len(topic_inherited),
        "verification_count": len(verification),
        "active_titles": active_titles,
        "status": "active" if active_market else ("independent" if independent else "inherited_only"),
    }


def is_independent_observation(discovery_type: Any, sources: list[str]) -> bool:
    discovery = str(discovery_type or "")
    if discovery in {"active_market_scan", "active_stock_scan", "postmarket_theme_scan", "postmarket_risk_scan", "risk_guardrail", "theme_shift_scan"}:
        return True
    source_text = " ".join(sources)
    return bool(re.search(r"intraday|postmarket|midday|theme-shifts|quality-report|source-health", source_text))


def observation_source_label(discovery_type: Any, sources: list[str]) -> str:
    discovery = str(discovery_type or "")
    if discovery in {"active_market_scan", "active_stock_scan"}:
        return "主动盘面扫描"
    if discovery in {"postmarket_theme_scan", "postmarket_risk_scan"}:
        return "盘后结构扫描"
    if discovery == "theme_shift_scan":
        return "主线变化扫描"
    if discovery == "risk_guardrail":
        return "系统风控扫描"
    if discovery == "verification_queue":
        return "验证队列"
    if discovery == "topic_watch_scan":
        return "专题继承"
    if sources:
        return "数据派生"
    return "来源待确认"


def next_action_for(item_type: str, watch_next: list[str], missing: list[str], tone: str) -> str:
    if watch_next:
        return watch_next[0]
    joined = " ".join(missing)
    actions: list[str] = []
    if "量化盘口" in joined:
        actions.append("先看涨停/封板数量、成交放大和尾盘承接，确认后再升级。")
    if "代表股" in joined:
        actions.append("补看代表股是否强于板块 ETF，至少 2-3 只核心股同向确认。")
    if "数据源降级" in joined:
        actions.append("等待二次行情源或数据质量恢复，未恢复前只做观察不触发交易。")
    if "来源文件" in joined:
        actions.append("补充来源文件后再使用该信号。")
    if "下一步验证" in joined:
        actions.append("补写可证伪条件：看竞价、开盘 15 分钟、午后承接或尾盘方向。")
    if actions:
        return "；".join(actions[:2])
    if item_type == "risk" or tone == "risk":
        return "先按风险项处理，等待风险收敛后再恢复进攻判断。"
    if item_type == "verification":
        return "按验证条件观察，不满足即不升级。"
    return "等待量价、代表股和数据质量同时确认后再升级。"


def trigger_reason_for(kwargs: dict[str, Any], evidence: list[str], watch_next: list[str]) -> str:
    discovery = kwargs.get("discovery_type") or "derived_signal"
    item_type = kwargs.get("item_type") or "signal"
    confidence = kwargs.get("confidence") or ""
    evidence_text = " ".join(evidence)
    watch_text = " ".join(watch_next)
    if discovery == "risk_guardrail":
        return "风控兜底触发：市场宽度、数据质量或回撤条件触发风险优先。"
    if discovery == "theme_shift_scan":
        return "主线变化扫描触发：升温/降温/抱团/风险状态出现边际变化。"
    if discovery == "active_market_scan":
        return "主动盘面扫描触发：涨跌停、炸板、尾盘承接或板块扩散出现可验证变化。"
    if discovery == "active_stock_scan":
        return "主动个股扫描触发：观察池或热点代表股出现强弱变化。"
    if discovery == "postmarket_risk_scan":
        return "盘后风险扫描触发：收盘复盘出现持续性、尾盘或次日风险线。"
    if discovery == "postmarket_theme_scan":
        return "盘后主线扫描触发：热点持续性、代表股和尾盘校验进入次日观察。"
    if discovery == "topic_watch_scan":
        if re.search(r"涨停|跌停|炸板|封板|放量|尾盘|竞价|\d", evidence_text):
            return "专题观察触发：既有专题出现新的量价证据或代表股变化。"
        return "专题观察触发：既有重点方向出现状态更新，需等待盘口量化验证。"
    if discovery == "verification_queue":
        return "验证队列触发：前序结论需要用下一交易窗口确认或证伪。"
    if item_type == "verification" or watch_text:
        return "待验证信号触发：存在明确下一步观察条件。"
    if confidence == "high":
        return "高置信信号触发：证据链较完整，优先进入雷达。"
    return "模型派生触发：多源结论汇总后形成候选信号。"


def signal_usability(item: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    score = 0
    confidence = item.get("confidence")
    evidence = clean_list(item.get("evidence") or [])
    watch_next = clean_list(item.get("watch_next") or [])
    sources = clean_list(item.get("source_files") or [])
    quality_flags = clean_list(item.get("quality_flags") or [])
    invalidation = str(item.get("invalidation") or "").strip()
    missing_evidence = clean_list(item.get("missing_evidence") or [])
    evidence_score = number(item.get("evidence_score"))

    if evidence:
        score += min(35, 12 + len(evidence) * 7)
        reasons.append("有可核验证据")
    else:
        reasons.append("缺少证据")
    if watch_next:
        score += 20
        reasons.append("有下一步验证")
    else:
        reasons.append("缺少下一步验证")
    if invalidation:
        score += 15
        reasons.append("有证伪条件")
    else:
        reasons.append("缺少证伪条件")
    if sources:
        score += 15
        reasons.append("有来源文件")
    else:
        reasons.append("缺少来源文件")
    if confidence == "high":
        score += 15
    elif confidence == "medium":
        score += 8
    elif confidence == "actionable":
        score += 10
    elif confidence == "low":
        score += 2
    if quality_flags:
        score -= min(30, 10 + len(quality_flags) * 5)
        reasons.append("数据质量降权")
    if missing_evidence:
        score -= min(20, len(missing_evidence) * 5)
        reasons.append("有证据缺口")
    if evidence_score >= 80:
        score += 5
        reasons.append("证据链较完整")

    score = max(0, min(100, score))
    if not evidence and item.get("type") not in {"verification", "data_quality"}:
        grade, action = "D", "仅复核"
    elif quality_flags:
        grade, action = ("C", "降权观察") if score >= 45 else ("D", "仅复核")
    elif score >= 80:
        grade, action = "A", "可跟踪"
    elif score >= 60:
        grade, action = "B", "等待确认"
    elif score >= 40:
        grade, action = "C", "降权观察"
    else:
        grade, action = "D", "仅复核"

    return {
        "signal_score": score,
        "signal_grade": grade,
        "use_action": action,
        "use_reasons": clean_list(reasons)[:5],
    }


def quality_gate(quality: dict[str, Any]) -> dict[str, Any]:
    status = quality.get("status") or "unknown"
    actionable_issues = [
        issue
        for issue in as_list(quality.get("issues"))
        if isinstance(issue, dict)
        and issue.get("severity") in {"critical", "warning"}
        and issue.get("impact_level") in {"blocking", "price_review", "signal_review"}
    ]
    flags = []
    for issue in actionable_issues:
        text = issue.get("message", "")
        impact = issue.get("impact_level", "")
        if impact == "blocking":
            flags.append("交易阻断项未修复，相关信号不可直接用")
        if impact == "price_review":
            flags.append("行情/涨跌幅需二次源复核")
        if impact == "signal_review":
            flags.append("机会信号需降权转验证")
        if "alert" in text or "异动" in text or "污染" in text:
            flags.append("盘中异动源降级，alert 类信号降权")
        if "quote_time" in text or "港" in text:
            flags.append("港股收盘窗口可能非终值")
        if "decode" in text or "数据源" in text or "source" in text:
            flags.append("行情源降级，需复核涨跌幅")
    flags = clean_list(flags) or (["数据质量待确认"] if status in {"degraded", "critical"} else [])
    return {
        "status": status,
        "summary": quality.get("summary") or "",
        "decision_flags": flags[:4],
        "blocking_count": (quality.get("counts") or {}).get("blocking", 0),
        "price_review_count": (quality.get("counts") or {}).get("price_review", 0),
        "background_review_count": (quality.get("counts") or {}).get("background_review", 0),
    }


def discovery_type_for(source: str, item: dict[str, Any], mode: str) -> str:
    text = compact_json(item)
    if source == "intraday.json":
        return "active_market_scan"
    if source == "postmarket.json" and mode == "risk":
        return "postmarket_risk_scan"
    if source == "postmarket.json":
        return "postmarket_theme_scan"
    if source == "topics.json":
        return "topic_watch_scan"
    if re.search(r"涨停|跌停|炸板|成交|尾盘|竞价", text):
        return "active_market_scan"
    return "derived_signal"


def missing_evidence_for(item_type: str, evidence: list[str], watch_next: list[str], sources: list[str], quality_flags: list[str]) -> list[str]:
    missing: list[str] = []
    joined = " ".join(evidence)
    if item_type not in {"verification", "data_quality"} and not evidence:
        missing.append("缺少可核验证据")
    if item_type in {"theme", "stock", "unplanned_theme"} and not re.search(r"\d|涨停|跌停|封板|成交|放量|尾盘|竞价|高开|低开", joined):
        missing.append("缺少量化盘口证据")
    if item_type in {"theme", "unplanned_theme"} and not re.search(r"代表股|核心股|龙头|涨停|封板|北方|中微|安集|雅克|华海|绿的|埃斯顿|恒瑞|券商|视源|威尔高|魅视|实益达|力鼎|双星", joined):
        missing.append("缺少代表股验证")
    if not watch_next:
        missing.append("缺少下一步验证")
    if not sources:
        missing.append("缺少来源文件")
    if quality_flags:
        missing.append("数据源降级需二次确认")
    return clean_list(missing)


def evidence_score_for(evidence: list[str], watch_next: list[str], sources: list[str], invalidation: Any, missing: list[str]) -> int:
    score = 0
    joined = " ".join(evidence)
    if evidence:
        score += min(35, 12 + len(evidence) * 7)
    if re.search(r"\d|涨停|跌停|封板|成交|放量|尾盘|竞价|高开|低开", joined):
        score += 20
    if re.search(r"北方|中微|安集|雅克|华海|绿的|埃斯顿|恒瑞|券商|ETF|代表股|核心股|龙头", joined):
        score += 15
    if watch_next:
        score += 15
    if sources:
        score += 10
    if invalidation:
        score += 10
    score -= min(35, len(missing) * 7)
    return max(0, min(100, score))


def latest_signal_date(files: dict[str, Any]) -> str:
    dates = []
    for name in ("premarket.json", "alert.json", "intraday.json", "midday.json", "postmarket.json", "topics.json"):
        date = signal_date((files.get(name) or {}).get("timestamp"))
        if date:
            dates.append(date)
    return sorted(dates)[-1] if dates else now_iso()[:10]


def signal_date(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


def current_payload(files: dict[str, Any], name: str, current_date: str) -> dict[str, Any]:
    payload = files.get(name) or {}
    if not isinstance(payload, dict):
        return {}
    return payload if signal_date(payload.get("timestamp")) == current_date else {}


def derived_sources_current(files: dict[str, Any], item: dict[str, Any], current_date: str) -> bool:
    source_names = [
        Path(str(source)).name
        for source in as_list(item.get("source_files"))
        if str(source).endswith(".json")
    ]
    primary = [
        name for name in source_names
        if name in {"alert.json", "intraday.json", "midday.json", "postmarket.json", "topics.json"}
    ]
    if not primary:
        return True
    return any(current_payload(files, name, current_date) for name in primary)


def now_iso() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


def trend_status(item: dict[str, Any]) -> str:
    return str(item.get("status") or item.get("strength") or item.get("trend") or item.get("name") or "")


def theme_name(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("sector") or item.get("theme") or item.get("title") or "未命名主题")


def is_opportunity_text(status: str, text: str) -> bool:
    full_text = status + text
    hard_negative = r"回避/降级|回避|降级|退潮|明显风险|风险线|风险转观察|不作?为进攻|风险集合|未触发|偏弱|弱化|反抽失败|不追高|外部.*压制"
    if re.search(hard_negative, full_text):
        return False
    has_strength = bool(re.search(r"强主线|强化|偏强|最强|领涨|封板|涨停|放量|承接|核心强线", full_text))
    if not has_strength:
        return False
    if re.search(r"不升级|不共振|不能定义为强主线|未形成|弱于|只作|只按|防守|高位分歧|炸板|跌停", full_text):
        return bool(re.search(r"强主线|强化|核心强线|最强", status))
    return True


def is_generic_bucket(item: dict[str, Any]) -> bool:
    name = theme_name(item)
    status = trend_status(item)
    return name in {"强逻辑", "观察线", "资金博弈线", "风险线"} and name == status


def has_stale_relative_time(text: str, current_date: str) -> bool:
    try:
        weekday = datetime.fromisoformat(current_date).weekday()
    except Exception:
        return False
    weekday_words = {
        "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6, "周天": 6,
    }
    next_trading_weekday = 0 if weekday == 4 else weekday + 1
    allowed = {weekday, next_trading_weekday}
    return any(word in text and day not in allowed for word, day in weekday_words.items())


def is_risk_text(status: str, text: str) -> bool:
    return bool(re.search(r"风险|弱|退潮|回避|降级|回落|分歧|压制|补跌|炸板|跌停", status + text))


def confidence_from(evidence: list[str], text: str, quality_degraded: bool) -> str:
    if quality_degraded:
        return "low"
    if len(evidence) >= 3 or re.search(r"\d+|涨停|跌停|成交|尾盘|封板", text):
        return "high"
    if evidence:
        return "medium"
    return "low"


def evidence_from(item: dict[str, Any]) -> list[str]:
    rows = []
    for key in ("evidence", "signals", "stocks"):
        for value in as_list(item.get(key)):
            if isinstance(value, str):
                rows.append(value)
            elif isinstance(value, dict):
                name = value.get("name") or value.get("title") or value.get("sector")
                pct = value.get("change_pct")
                note = first_text(value.get("note"), value.get("reason"), value.get("status"))
                if name and pct is not None:
                    rows.append(f"{name} {pct}%")
                elif name or note:
                    rows.append(" ".join(str(x) for x in (name, note) if x))
    for key in ("note", "continuity", "reason"):
        value = item.get(key)
        if value:
            rows.append(str(value))
    return clean_list(rows)


def watch_next_from(item: dict[str, Any]) -> list[str]:
    rows = []
    for key in ("watch_next_day", "watch_next", "action"):
        rows.extend(text_items(item.get(key)))
    return clean_list(rows) or ["看核心个股、ETF、后排扩散和尾盘承接是否同向确认。"]


def invalidation_for(item: dict[str, Any], mode: str) -> str:
    name = theme_name(item)
    if mode == "opportunity":
        return f"{name}核心股冲高回落、ETF转弱或后排不扩散，则机会降级为观察。"
    return f"{name}风险信号收敛、核心股重新放量承接，则风险降级。"


def verification_title(text: str) -> str:
    tags = related_tags(text)
    return f"{tags[0]}验证" if tags else "验证条件"


def related_tags(text: str) -> list[str]:
    mapping = [
        ("科技硬件链", r"半导体|设备|材料|CPO|光模块|存储|HBM|PCB|电子布|封装|硅片|算力|芯片|北方|中微|华海|安集|雅克|澜起|兆易|中际|新易盛|沪电|胜宏"),
        ("机器人/工业自动化", r"机器人|工业自动化|通用设备|自动化设备|减速器|伺服|控制器|机器视觉|步科|绿的|埃斯顿|中大力德|双环|拓斯达|汇川|奥普特"),
        ("医药修复链", r"医药|化学制药|创新药|原料药|制剂|CRO|恒瑞|科伦|普洛|九典|金城|赛托|共同药业|广生堂|艾力斯|百济|诺诚|荣昌"),
        ("老登风格切换", r"券商|证券|保险|白酒|酒|畜牧|银行|地产|中字头|权重|中信证券|国泰海通|东方财富|平安|茅台|五粮液|牧原|温氏"),
        ("风控", r"风险|回避|降级|暴跌|减持|监管|澄清|跌停|炸板|回撤|数据质量"),
    ]
    return [name for name, pattern in mapping if re.search(pattern, text or "")]


def first_number_after(text: str, marker: str) -> float:
    idx = text.find(marker)
    if idx < 0:
        return 0
    match = re.search(r"(\d+(?:\.\d+)?)", text[idx + len(marker):idx + len(marker) + 30])
    return float(match.group(1)) if match else 0


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return ""


def text_items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        rows = []
        for item in value:
            if isinstance(item, str):
                rows.append(item)
            elif isinstance(item, dict):
                rows.append(first_text(item.get("text"), item.get("action"), item.get("note"), item.get("summary"), compact_json(item)))
        return clean_list(rows)
    if isinstance(value, dict):
        return clean_list([first_text(value.get("text"), value.get("summary"), compact_json(value))])
    return []


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value:
        return [value]
    return []


def clean_list(values: list[Any]) -> list[str]:
    seen = set()
    rows = []
    for value in values:
        text = trim(str(value or "").replace("\n", " "), 180)
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def unique_keep_order(values: list[str]) -> list[str]:
    seen = set()
    rows = []
    for value in values:
        text = trim(str(value or "").replace("\n", " "), 240)
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def build_signal_conflicts(opportunities: list[dict[str, Any]], risks: list[dict[str, Any]], verifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for section, rows in (("opportunities", opportunities), ("risks", risks), ("verifications", verifications)):
        for item in rows:
            key = conflict_key(item.get("title"))
            if not key:
                continue
            buckets.setdefault(key, {"opportunities": [], "risks": [], "verifications": []})[section].append(item)
    conflicts: list[dict[str, Any]] = []
    for key, rows in buckets.items():
        sections = [name for name, values in rows.items() if values]
        if len(sections) < 2:
            continue
        risk_best = max((grade_rank(item.get("signal_grade")) for item in rows["risks"]), default=0)
        opportunity_best = max((grade_rank(item.get("signal_grade")) for item in rows["opportunities"]), default=0)
        downgraded_opportunity = any(re.search(r"仅复核|降权|等待", str(item.get("use_action") or "")) for item in rows["opportunities"])
        if risk_best >= 3 and (opportunity_best <= 2 or downgraded_opportunity):
            verdict = "风险优先，只做验证"
            action = "先按风险栏处理；只有风险收敛、核心股承接和数据质量恢复后，才允许从验证栏升级。"
            severity = "risk_first"
        elif risk_best >= 3 and opportunity_best >= 3:
            verdict = "多空冲突，等待确认"
            action = "不直接追高；等竞价、开盘15分钟和尾盘承接给出同向确认。"
            severity = "conflict"
        else:
            verdict = "候选分歧，观察验证"
            action = "保留验证，不升级为交易机会。"
            severity = "watch"
        conflicts.append({
            "theme": key,
            "sections": sections,
            "verdict": verdict,
            "severity": severity,
            "action": action,
            "evidence": conflict_evidence(rows),
        })
    return conflicts[:6]


def conflict_key(title: Any) -> str:
    text = trim(title, 80)
    if not text:
        return ""
    text = re.sub(r"^(主线变化：|新线观察：)", "", text)
    text = re.sub(r"(候选验证|验证)$", "", text)
    text = text.strip()
    aliases = {
        "科技硬件链": "科技硬件链",
        "半导体设备": "科技硬件链",
        "半导体材料": "科技硬件链",
        "半导体零部件": "科技硬件链",
        "创新药/CRO": "医药修复链",
        "医药": "医药修复链",
        "医药修复链": "医药修复链",
        "老登风格切换": "老登风格切换",
    }
    return aliases.get(text, text)


def grade_rank(value: Any) -> int:
    return {"A": 4, "B": 3, "C": 2, "D": 1}.get(str(value or "").upper(), 0)


def conflict_evidence(rows: dict[str, list[dict[str, Any]]]) -> list[str]:
    evidence: list[str] = []
    for label, values in (("机会", rows.get("opportunities") or []), ("风险", rows.get("risks") or []), ("验证", rows.get("verifications") or [])):
        if not values:
            continue
        item = values[0]
        evidence.append(f"{label}：{item.get('signal_grade') or '-'}级/{item.get('use_action') or item.get('confidence') or '-'}，{trim(item.get('conclusion') or item.get('next_action') or '', 80)}")
    return clean_list(evidence)[:4]


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    rows = []
    for item in items:
        key = item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(item)
    return rows


def compact_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(value)


def trim(text: Any, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def number(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())

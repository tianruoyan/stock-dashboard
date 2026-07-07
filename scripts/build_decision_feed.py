#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
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
        )
    }
    signal_date = latest_signal_date(files)
    feed = {
        "timestamp": now_iso(),
        "current_signal_date": signal_date,
        "quality_gate": quality_gate(files.get("quality-report.json") or {}),
        "summary": build_summary(files),
        "opportunities": dedupe_items(build_opportunities(files, signal_date))[:8],
        "risks": dedupe_items(build_risks(files))[:8],
        "verifications": dedupe_items(build_verifications(files))[:8],
        "rules": [
            "每条机会/风险必须带 source_files；没有证据时置信度不得高于 low。",
            "机会只代表候选方向，必须经过下一步验证，不生成交易指令。",
            "quality-report 为 degraded/critical 时，所有机会必须带 quality_flags 并自动降权。",
            "每条信号必须输出 signal_grade/use_action/use_reasons，前端按可用性而不是标题强弱展示。",
            "每条信号必须输出 discovery_type/evidence_score/missing_evidence，用于区分主动发现、继承专题、风险兜底和证据缺口。",
            "theme-shifts 用于识别升温、新线、抱团、降温和风险变化，并进入机会/风险/验证栏。",
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


def build_summary(files: dict[str, Any]) -> str:
    post = files.get("postmarket.json") or {}
    intraday = files.get("intraday.json") or {}
    quality = files.get("quality-report.json") or {}
    base = first_text(post.get("review", {}).get("one_sentence"), post.get("index", {}).get("summary"), intraday.get("summary"))
    if quality.get("status") in {"degraded", "critical"}:
        return trim(f"{base} 数据质量：{quality.get('summary')}", 180)
    return trim(base, 180)


def build_opportunities(files: dict[str, Any], current_date: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    quality = files.get("quality-report.json") or {}
    gate = quality_gate(quality)
    quality_degraded = gate["status"] in {"degraded", "critical"}

    for theme, source in theme_candidates(files):
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

    for shift in theme_shift_candidates(files, {"warming", "emerging"}):
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

    post = files.get("postmarket.json") or {}
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
    return items


def build_risks(files: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    post = files.get("postmarket.json") or {}
    intraday = files.get("intraday.json") or {}
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

    for shift in theme_shift_candidates(files, {"risk", "crowded", "fading"}):
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

    for theme, source in theme_candidates(files):
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

    return items


def build_verifications(files: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidates = [
        ("intraday.json", files.get("intraday.json", {}).get("actions")),
        ("midday.json", files.get("midday.json", {}).get("afternoon_watch")),
        ("postmarket.json", files.get("postmarket.json", {}).get("next_day_watch")),
        ("postmarket.json", files.get("postmarket.json", {}).get("closing_auction_patch", {}).get("watch_next_day")),
    ]
    for shift in theme_shift_candidates(files, {"warming", "emerging", "risk", "crowded", "fading"}):
        candidates.append(("theme-shifts.json", shift.get("watch_next")))
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


def theme_shift_candidates(files: dict[str, Any], states: set[str]) -> list[dict[str, Any]]:
    rows = files.get("theme-shifts.json", {}).get("shifts") if isinstance(files.get("theme-shifts.json"), dict) else []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("state") in states]


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


def decision_item(**kwargs: Any) -> dict[str, Any]:
    evidence = clean_list(kwargs.get("evidence") or [])
    watch_next = clean_list(kwargs.get("watch_next") or [])
    sources = clean_list(kwargs.get("source_files") or [])
    missing = missing_evidence_for(kwargs.get("item_type") or "signal", evidence, watch_next, sources, kwargs.get("quality_flags") or [])
    evidence_score = evidence_score_for(evidence, watch_next, sources, kwargs.get("invalidation"), missing)
    confidence = kwargs.get("confidence") or ("medium" if evidence else "low")
    if not evidence and confidence == "high":
        confidence = "medium"
    item = {
        "title": trim(kwargs.get("title") or "未命名信号", 40),
        "type": kwargs.get("item_type") or "signal",
        "conclusion": trim(kwargs.get("conclusion") or "", 180),
        "confidence": confidence,
        "evidence": evidence[:5],
        "source_files": sources[:4],
        "watch_next": watch_next[:4],
        "invalidation": trim(kwargs.get("invalidation") or "等待反向量价信号确认。", 140),
        "tags": clean_list(kwargs.get("tags") or [])[:5],
        "quality_flags": clean_list(kwargs.get("quality_flags") or [])[:4],
        "tone": kwargs.get("tone") or "neutral",
        "discovery_type": kwargs.get("discovery_type") or "derived_signal",
        "evidence_score": evidence_score,
        "missing_evidence": missing[:5],
    }
    item.update(signal_usability(item))
    return item


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
    issues = [
        issue.get("message", "")
        for issue in as_list(quality.get("issues"))
        if isinstance(issue, dict) and issue.get("severity") in {"critical", "warning"}
    ]
    flags = []
    for text in issues:
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
    if item_type in {"theme", "stock"} and not re.search(r"\d|涨停|跌停|封板|成交|放量|尾盘|竞价|高开|低开", joined):
        missing.append("缺少量化盘口证据")
    if item_type == "theme" and not re.search(r"代表股|核心股|龙头|涨停|封板|北方|中微|安集|雅克|华海|绿的|埃斯顿|恒瑞|券商", joined):
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
    for name in ("alert.json", "intraday.json", "midday.json", "postmarket.json", "topics.json"):
        date = signal_date((files.get(name) or {}).get("timestamp"))
        if date:
            dates.append(date)
    return sorted(dates)[-1] if dates else now_iso()[:10]


def signal_date(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


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
    return any(word in text and weekday != day for word, day in weekday_words.items())


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

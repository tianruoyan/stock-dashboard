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
        )
    }
    signal_date = latest_signal_date(files)
    feed = {
        "timestamp": now_iso(),
        "current_signal_date": signal_date,
        "summary": build_summary(files),
        "opportunities": dedupe_items(build_opportunities(files))[:8],
        "risks": dedupe_items(build_risks(files))[:8],
        "verifications": dedupe_items(build_verifications(files))[:8],
        "rules": [
            "每条机会/风险必须带 source_files；没有证据时置信度不得高于 low。",
            "机会只代表候选方向，必须经过下一步验证，不生成交易指令。",
            "quality-report 为 degraded/critical 时，所有机会自动降权。",
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


def build_opportunities(files: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    quality = files.get("quality-report.json") or {}
    quality_degraded = quality.get("status") in {"degraded", "critical"}

    for theme, source in theme_candidates(files):
        text = compact_json(theme)
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
        ))

    for theme, source in theme_candidates(files):
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
            ))
    return rows


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
                    "evidence": [f"{name}涨跌幅 {pct}%" if pct is not None else note].filter(Boolean),
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
        )
    return None


def decision_item(**kwargs: Any) -> dict[str, Any]:
    evidence = clean_list(kwargs.get("evidence") or [])
    confidence = kwargs.get("confidence") or ("medium" if evidence else "low")
    if not evidence and confidence == "high":
        confidence = "medium"
    return {
        "title": trim(kwargs.get("title") or "未命名信号", 40),
        "type": kwargs.get("item_type") or "signal",
        "conclusion": trim(kwargs.get("conclusion") or "", 180),
        "confidence": confidence,
        "evidence": evidence[:5],
        "source_files": clean_list(kwargs.get("source_files") or [])[:4],
        "watch_next": clean_list(kwargs.get("watch_next") or [])[:4],
        "invalidation": trim(kwargs.get("invalidation") or "等待反向量价信号确认。", 140),
        "tags": clean_list(kwargs.get("tags") or [])[:5],
        "tone": kwargs.get("tone") or "neutral",
    }


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
    if re.search(r"回避/降级|回避|降级|退潮|明显风险|不作?为进攻|风险集合", full_text):
        return False
    return bool(re.search(r"强|强化|主线|领涨|封板|涨停|放量|承接|修复", full_text))


def is_risk_text(status: str, text: str) -> bool:
    return bool(re.search(r"风险|弱|退潮|回避|降级|回落|分歧|压制|补跌|炸板|跌停", status + text))


def confidence_from(evidence: list[str], text: str, quality_degraded: bool) -> str:
    if quality_degraded:
        return "low" if len(evidence) < 3 else "medium"
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

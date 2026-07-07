#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "theme-shifts.json"
TZ = timezone(timedelta(hours=8))


def main() -> int:
    intraday = load_json(DATA_DIR / "intraday.json")
    postmarket = load_json(DATA_DIR / "postmarket.json")
    topics = load_json(DATA_DIR / "topics.json")
    quality = load_json(DATA_DIR / "quality-report.json")
    current_date = latest_signal_date([intraday, postmarket, topics])
    candidates = collect_candidates(intraday, postmarket, topics)
    shifts = classify_shifts(candidates, quality, current_date)
    report = {
        "timestamp": now_iso(),
        "current_signal_date": current_date,
        "summary": summarize(shifts),
        "shifts": shifts[:10],
        "rules": [
            "warming/emerging：可能形成或重新升温的方向，只作为候选，不直接追高。",
            "crowded：强点集中在少数核心股但扩散不足，按抱团风险处理。",
            "fading/risk：负反馈、分歧、退潮、弱化或外部映射压制。",
            "每条变化必须给证据、下一步验证和来源文件。",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"theme-shifts: {len(report['shifts'])} shifts - {report['summary']}")
    return 0


def collect_candidates(intraday: dict[str, Any], postmarket: dict[str, Any], topics: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source, values in (
        ("intraday.json", as_list(intraday.get("main_trends"))),
        ("intraday.json", as_list(intraday.get("themes"))),
        ("postmarket.json", as_list(postmarket.get("hotspots"))),
        ("topics.json", as_list(topics.get("topics"))),
    ):
        for item in values:
            if isinstance(item, dict):
                rows.append(normalize_item(item, source))
            elif isinstance(item, str):
                rows.append(normalize_item({"name": item, "status": item}, source))
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = theme_key(row["name"] + " " + row["text"])
        if not key:
            continue
        target = merged.setdefault(key, {
            "theme": key,
            "display_name": row["display_name"],
            "texts": [],
            "evidence": [],
            "watch_next": [],
            "source_files": [],
            "stocks": [],
        })
        target["texts"].append(row["text"])
        target["evidence"].extend(row["evidence"])
        target["watch_next"].extend(row["watch_next"])
        target["source_files"].append(row["source_file"])
        target["stocks"].extend(row["stocks"])
    return list(merged.values())


def normalize_item(item: dict[str, Any], source: str) -> dict[str, Any]:
    name = str(item.get("name") or item.get("sector") or item.get("theme") or item.get("title") or item.get("group") or "未命名主题")
    evidence = evidence_from(item)
    watch = text_items(item.get("watch_next_day")) + text_items(item.get("watch_next")) + text_items(item.get("action"))
    stocks = stock_names(item.get("stocks")) + stock_names(item.get("leaders")) + stock_names(item.get("items"))
    text = " ".join([
        name,
        str(item.get("status") or ""),
        str(item.get("continuity") or ""),
        str(item.get("risk") or ""),
        str(item.get("note") or ""),
        " ".join(evidence),
        " ".join(watch),
        " ".join(stocks),
    ])
    return {
        "display_name": display_name_for(name, text),
        "name": name,
        "text": text,
        "evidence": evidence,
        "watch_next": watch,
        "stocks": stocks,
        "source_file": source,
    }


def classify_shifts(candidates: list[dict[str, Any]], quality: dict[str, Any], current_date: str) -> list[dict[str, Any]]:
    quality_degraded = quality.get("status") in {"degraded", "critical"}
    rows = []
    for item in candidates:
        text = " ".join(item["texts"])
        if is_generic_theme(item["display_name"], text) or has_stale_relative_time(text, current_date):
            continue
        evidence = clean_list(item["evidence"])[:5]
        watch = clean_list(item["watch_next"])[:4] or default_watch(item["display_name"], text)
        sources = clean_list(item["source_files"])[:4]
        stocks = clean_list(item["stocks"])[:8]
        state, score, conclusion = state_for(item["display_name"], text, evidence, stocks, quality_degraded)
        if score < 35:
            continue
        rows.append({
            "theme": item["display_name"],
            "state": state,
            "score": score,
            "conclusion": conclusion,
            "evidence": evidence or [trim(text, 120)],
            "watch_next": watch,
            "risk": risk_for(state, item["display_name"], text),
            "stocks": stocks,
            "source_files": sources,
            "quality_flags": ["全局数据降级，主线变化需二次确认"] if quality_degraded else [],
        })
    order = {"risk": 0, "crowded": 1, "warming": 2, "emerging": 3, "fading": 4, "watch": 5}
    return sorted(rows, key=lambda row: (order.get(row["state"], 9), -row["score"], row["theme"]))


def state_for(theme: str, text: str, evidence: list[str], stocks: list[str], quality_degraded: bool) -> tuple[str, int, str]:
    score = 20
    if evidence:
        score += min(25, len(evidence) * 7)
    if stocks:
        score += min(15, len(stocks) * 2)
    if re.search(r"涨停|封板|8%以上|5%-8%|放量|承接|扩散|轮动增强|偏强|强", text):
        score += 25
    if re.search(r"风险|弱化|弱|退潮|回落|分歧|压制|炸板|跌停|负反馈|证伪", text):
        score += 20
    if quality_degraded:
        score -= 10

    if re.search(r"跌停|退潮|负反馈|压制|证伪|风险线|弱化|明显负反馈", text):
        return "risk", clamp(score), f"{theme} 出现负反馈或风险信号，优先作为风险观察。"
    if re.search(r"抱团|未扩散|不健康|分化|只.*情绪锚|不能.*升级|核心.*未形成一致", text):
        return "crowded", clamp(score), f"{theme} 强点集中但扩散不足，属于抱团/拥挤结构。"
    if re.search(r"轮动增强|低位轮动|首次|新增|扩散|涨停池|观察线", text):
        return "emerging", clamp(score), f"{theme} 有新出现或轮动增强迹象，需看次日扩散确认。"
    if re.search(r"偏强|强|承接|封板|涨停|放量", text):
        return "warming", clamp(score), f"{theme} 有升温迹象，但仍需量价和后排扩散验证。"
    if re.search(r"弱化|回落|转弱|不共振", text):
        return "fading", clamp(score), f"{theme} 边际降温，反抽先按观察处理。"
    return "watch", clamp(score), f"{theme} 暂未形成明确变化，保留观察。"


def theme_key(text: str) -> str:
    mapping = [
        ("科技硬件链", r"半导体|硅片|封装|设备|零部件|材料|CPO|光模块|PCB|电子布|存储|HBM|元件|消费电子|低位硬件"),
        ("机器人/工业自动化", r"机器人|通用设备|自动化|减速器|伺服|控制器|机器视觉"),
        ("医药修复链", r"医药|创新药|化学制药|CRO|原料药|制剂"),
        ("AI应用/物理AI", r"AI应用|物理AI|传媒|游戏|商汤|快手|多模态"),
        ("化工/材料/资源轮动", r"化工|化学制品|材料|资源|锂电材料|雅化|佛塑|晨光新材|百合花|宝地矿业"),
        ("老登风格切换", r"券商|证券|保险|白酒|畜牧|银行|地产|权重"),
    ]
    for name, pattern in mapping:
        if re.search(pattern, text):
            return name
    raw = re.split(r"[/、，,\s-]+", text.strip())[0]
    return raw[:18]


def is_generic_theme(name: str, text: str) -> bool:
    generic_names = {"回避", "风险", "风险集合", "强逻辑", "观察线", "资金博弈线", "待验证", "配置"}
    return name in generic_names or bool(re.fullmatch(r"(回避|风险|观察|待验证).{0,6}", name)) or "页面提示要集中成一个风险集合" in text


def has_stale_relative_time(text: str, current_date: str) -> bool:
    try:
        weekday = datetime.fromisoformat(current_date).weekday()
    except Exception:
        return False
    weekday_words = {
        "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6, "周天": 6,
    }
    return any(word in text and weekday != day for word, day in weekday_words.items())


def display_name_for(name: str, text: str) -> str:
    return theme_key(name + " " + text) or name


def default_watch(theme: str, text: str) -> list[str]:
    if re.search(r"风险|弱|退潮|跌停|炸板", text):
        return [f"看{theme}负反馈是否收敛，跌停/炸板是否减少。"]
    return [f"看{theme}核心股是否继续承接，并扩散到后排。"]


def risk_for(state: str, theme: str, text: str) -> str:
    if state == "crowded":
        return f"{theme} 若只有少数核心股强、后排不扩散，次日容易冲高回落。"
    if state in {"risk", "fading"}:
        return f"{theme} 反抽不能直接当修复，先看负反馈是否收敛。"
    if re.search(r"高位|抱团|分化", text):
        return f"{theme} 存在高位分化，不能只看单只强股。"
    return f"{theme} 需要次日竞价、量能和后排扩散共同确认。"


def summarize(shifts: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for row in shifts:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    if not shifts:
        return "未发现可用的主线变化信号。"
    return "；".join(f"{label}{counts.get(key, 0)}" for key, label in [
        ("risk", "风险"),
        ("crowded", "抱团"),
        ("warming", "升温"),
        ("emerging", "新线"),
        ("fading", "降温"),
    ] if counts.get(key))


def evidence_from(item: dict[str, Any]) -> list[str]:
    rows = []
    for key in ("evidence", "signals"):
        for value in as_list(item.get(key)):
            rows.append(text_from(value))
    for key in ("continuity", "risk", "note", "reason"):
        if item.get(key):
            rows.append(str(item.get(key)))
    return clean_list(rows)


def text_items(value: Any) -> list[str]:
    return clean_list([text_from(item) for item in as_list(value)])


def stock_names(value: Any) -> list[str]:
    rows = []
    for item in as_list(value):
        if isinstance(item, dict):
            rows.append(str(item.get("name") or item.get("symbol") or item.get("title") or ""))
        else:
            rows.append(str(item or ""))
    return clean_list(rows)


def text_from(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or value.get("detail") or value.get("name") or value.get("title") or compact_json(value))
    return str(value or "")


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
        text = trim(str(value or ""), 180)
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def latest_signal_date(payloads: list[dict[str, Any]]) -> str:
    dates = [signal_date(item.get("timestamp")) for item in payloads if isinstance(item, dict)]
    dates = [date for date in dates if date]
    return sorted(dates)[-1] if dates else now_iso()[:10]


def signal_date(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def compact_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(value)


def trim(text: Any, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def clamp(value: int) -> int:
    return max(0, min(100, value))


def now_iso() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"
OUT = DATA_DIR / "section-health.json"
TZ = timezone(timedelta(hours=8))
BAD_LITERALS = ("[object Object]", "undefined", "None%", "NaN", "Infinity")

SECTIONS = [
    {"id": "control", "label": "今日总控", "files": ["data/intraday.json", "data/postmarket.json", "data/quality-report.json", "data/theme-shifts.json", "data/decision-feed.json"]},
    {"id": "watchlist", "label": "我的观察池", "files": ["config/watchlist.json", "data/premarket.json", "data/intraday.json", "data/postmarket.json", "data/topics.json", "data/quality-report.json"]},
    {"id": "alerts", "label": "盘中异动", "files": ["data/alert.json", "data/opportunity-watch.json", "data/source-health.json"]},
    {"id": "intraday", "label": "盘中全景", "files": ["data/intraday.json", "data/source-health.json"]},
    {"id": "premarket", "label": "早盘盘前", "files": ["data/premarket.json", "data/source-health.json"]},
    {"id": "midday", "label": "午盘盘前", "files": ["data/midday.json"]},
    {"id": "postmarket", "label": "午盘盘后", "files": ["data/postmarket.json", "data/source-health.json"]},
    {"id": "evening", "label": "晚间舆情", "files": ["data/evening-sentiment.json"]},
    {"id": "topics", "label": "专题跟踪", "files": ["data/topics.json", "config/topics-list.json", "data/quality-report.json"]},
]


def main() -> int:
    payloads = {rel: load_json(ROOT / rel) for spec in SECTIONS for rel in spec["files"]}
    current_date = latest_signal_date(payloads)
    source_flags = source_health_flags(payloads.get("data/source-health.json") or {})
    sections = [build_section(spec, payloads, current_date, source_flags) for spec in SECTIONS]
    counts = {status: sum(1 for item in sections if item["status"] == status) for status in ("ok", "degraded", "stale", "invalidated", "missing")}
    report = {
        "timestamp": now_iso(),
        "current_signal_date": current_date,
        "overall_status": overall_status(sections),
        "summary": summarize(sections),
        "counts": counts,
        "sections": sections,
        "rules": [
            "missing/invalidated 为区块不可直接使用。",
            "stale 表示非当前交易日，只能作为历史背景。",
            "degraded 表示可看但要降权，原因必须展示。",
            "source-health 降级会传递到依赖行情源的区块。",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"section-health: {report['overall_status']} - {report['summary']}")
    return 0


def build_section(spec: dict[str, Any], payloads: dict[str, Any], current_date: str, source_flags: list[str]) -> dict[str, Any]:
    reasons: list[str] = []
    file_rows: list[dict[str, Any]] = []
    status_rank = 0
    has_current_watch_context = spec["id"] == "watchlist" and any(
        payload_signal_date(payloads.get(rel) or {}) == current_date
        for rel in ("data/premarket.json", "data/intraday.json", "data/midday.json", "data/topics.json")
    )
    for rel in spec["files"]:
        path = ROOT / rel
        data = payloads.get(rel)
        file_status = "ok"
        status_for_rank = "ok"
        ts = data.get("timestamp") if isinstance(data, dict) else ""
        row_date = payload_signal_date(data) if isinstance(data, dict) else ""
        if not path.exists() or data in (None, {}):
            file_status = "missing"
            status_for_rank = file_status
            reasons.append(f"{rel} 缺失或不可读")
        elif isinstance(data, dict) and data.get("source_status") == "invalidated":
            file_status = "invalidated"
            status_for_rank = file_status
            reasons.append(data.get("note") or f"{rel} 已撤下污染批次")
        elif row_date and current_date and row_date != current_date:
            file_status = "stale"
            if not (has_current_watch_context and rel == "data/postmarket.json"):
                status_for_rank = file_status
                reasons.append(f"{rel} 非当前交易日：{row_date}")
        elif contains_bad_literal(path):
            file_status = "missing"
            status_for_rank = file_status
            reasons.append(f"{rel} 含异常文本")
        elif isinstance(data, dict) and data.get("status") in {"degraded", "critical"}:
            file_status = "degraded"
            status_for_rank = file_status
            reasons.append(f"{rel} {data.get('summary') or data.get('status')}")
        elif isinstance(data, dict) and data.get("overall_status") == "degraded":
            file_status = "degraded"
            status_for_rank = file_status
            reasons.append(f"{rel} 数据源整体降级")
        status_rank = max(status_rank, rank(status_for_rank))
        file_rows.append({"file": rel, "status": file_status, "timestamp": ts or "", "signal_date": row_date})

    if "data/source-health.json" in spec["files"] and source_flags:
        status_rank = max(status_rank, rank("degraded"))
        reasons.extend(source_flags[:2])

    status = unrank(status_rank)
    return {
        "id": spec["id"],
        "label": spec["label"],
        "status": status,
        "usable": status not in {"missing", "invalidated"},
        "reason": trim("；".join(clean_list(reasons)) or "区块数据可用", 180),
        "action": action_for(status),
        "files": file_rows,
        "latest_timestamp": latest_timestamp([row["timestamp"] for row in file_rows]),
    }


def source_health_flags(source_health: dict[str, Any]) -> list[str]:
    rows = []
    sources = source_health.get("sources") or {}
    iterator = sources.items() if isinstance(sources, dict) else []
    for name, source in iterator:
        if not isinstance(source, dict):
            continue
        if source.get("status") in {"degraded", "bad", "failed"}:
            rows.append(source_flag_message(name, source))
    return clean_list(rows)


def payload_signal_date(data: dict[str, Any]) -> str:
    current = str(data.get("current_signal_date") or "").strip()
    if current:
        return current
    return signal_date(data.get("timestamp"))


def source_flag_message(name: str, source: dict[str, Any]) -> str:
    text = f"{name}: {source.get('note') or source.get('detail') or source.get('usage') or source.get('status')}"
    if re.search(r"Can not decode value starting with|JSON decode failed|proxy disconnect|failed with|decode failed", text, re.I):
        if re.search(r"hk|港股|stock_hk|Eastmoney|push2", text, re.I):
            return "港股结构行情源连接/解码异常，港股映射和收盘窗口价格需二次复核。"
        if re.search(r"japan|korea|nikkei|kospi|日韩|日经|韩国", text, re.I):
            return "日韩早盘实时源异常，页面仅保留待复核清单，不展示未核实数值。"
        return "A股补充行情源解码异常，盘中异动和个股涨跌幅需以已审计源复核。"
    return text


def latest_signal_date(payloads: dict[str, Any]) -> str:
    dates = []
    for rel in ("data/premarket.json", "data/alert.json", "data/intraday.json", "data/midday.json", "data/postmarket.json", "data/topics.json"):
        data = payloads.get(rel)
        date = signal_date(data.get("timestamp") if isinstance(data, dict) else "")
        if date:
            dates.append(date)
    return sorted(dates)[-1] if dates else now_iso()[:10]


def overall_status(sections: list[dict[str, Any]]) -> str:
    statuses = {item["status"] for item in sections}
    if statuses & {"missing", "invalidated"}:
        return "degraded"
    if statuses & {"degraded", "stale"}:
        return "degraded"
    return "ok"


def summarize(sections: list[dict[str, Any]]) -> str:
    bad = [item for item in sections if item["status"] in {"missing", "invalidated"}]
    degraded = [item for item in sections if item["status"] in {"degraded", "stale"}]
    if bad:
        return f"{len(bad)} 个区块不可直接使用，{len(degraded)} 个区块需降权。"
    if degraded:
        return f"{len(degraded)} 个区块需降权查看。"
    return "所有核心区块数据可用。"


def action_for(status: str) -> str:
    return {
        "ok": "正常使用",
        "degraded": "可看但降权",
        "stale": "仅作历史背景",
        "invalidated": "等待重新产出",
        "missing": "待接入/修复",
    }.get(status, "待确认")


def rank(status: str) -> int:
    return {"ok": 0, "degraded": 1, "stale": 2, "invalidated": 3, "missing": 4}.get(status, 1)


def unrank(value: int) -> str:
    return {0: "ok", 1: "degraded", 2: "stale", 3: "invalidated", 4: "missing"}.get(value, "degraded")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def contains_bad_literal(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False
    return any(literal in text for literal in BAD_LITERALS)


def latest_timestamp(values: list[str]) -> str:
    valid = [value for value in values if value]
    return sorted(valid)[-1] if valid else ""


def signal_date(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


def clean_list(values: list[Any]) -> list[str]:
    seen = set()
    rows = []
    for value in values:
        text = trim(str(value or ""), 220)
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def trim(text: Any, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def now_iso() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

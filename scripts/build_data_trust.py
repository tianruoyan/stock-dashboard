#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "data-trust.json"
TZ = timezone(timedelta(hours=8))
FUTURE_TIMESTAMP_TOLERANCE_SECONDS = 120
BAD_LITERALS = ("[object Object]", "undefined", "None%", "NaN", "Infinity")
MOJIBAKE_PATTERN = re.compile(r"[�ÃÂ]|(?:æ|å|ç|è|é)[A-Za-z0-9_\- ]{0,8}")

CORE_FILES = [
    {"file": "data/alert.json", "label": "盘中异动", "depends_on_source": True, "role": "高频触发信号", "session": "market", "freshness_minutes": 5},
    {"file": "data/intraday.json", "label": "盘中全景", "depends_on_source": True, "role": "盘面结构和情绪", "session": "market", "freshness_minutes": 15},
    {"file": "data/premarket.json", "label": "早盘盘前", "depends_on_source": True, "role": "开盘前研判", "session": "premarket", "freshness_minutes": 90},
    {"file": "data/midday.json", "label": "午盘盘前", "depends_on_source": False, "role": "午后验证框架", "session": "midday", "freshness_minutes": 120},
    {"file": "data/postmarket.json", "label": "盘后复盘", "depends_on_source": True, "role": "收盘复盘和次日观察", "session": "postmarket", "freshness_minutes": 360},
    {"file": "data/evening-sentiment.json", "label": "晚间舆情", "depends_on_source": False, "role": "隔夜事件和公告", "session": "evening", "freshness_minutes": 720},
    {"file": "data/topics.json", "label": "专题跟踪", "depends_on_source": False, "role": "中期专题结论", "session": "background", "freshness_minutes": 10080},
    {"file": "data/opportunity-watch.json", "label": "盘中机会追踪", "depends_on_source": False, "role": "盘前/晚间线索转盘中待触发清单", "session": "decision", "freshness_minutes": 720},
    {"file": "data/theme-shifts.json", "label": "主线变化", "depends_on_source": False, "role": "升温/降温/抱团/风险变化", "session": "decision", "freshness_minutes": 30},
    {"file": "data/decision-feed.json", "label": "机会风险流", "depends_on_source": False, "role": "结构化机会/风险/验证", "session": "decision", "freshness_minutes": 30},
]


def main() -> int:
    now = datetime.now(TZ)
    phase = trading_phase(now)
    payloads = {spec["file"]: load_json(ROOT / spec["file"]) for spec in CORE_FILES}
    quality = load_json(DATA_DIR / "quality-report.json")
    source_health = load_json(DATA_DIR / "source-health.json")
    current_date = latest_signal_date(payloads)
    quality_issues = quality.get("issues") if isinstance(quality, dict) else []
    source_flags = degraded_source_flags(source_health)
    files = [
        trust_row(spec, payloads.get(spec["file"]), current_date, quality_issues, source_flags, phase, now)
        for spec in CORE_FILES
    ]
    counts = {status: sum(1 for row in files if row["status"] == status) for status in ("trusted", "degraded", "stale", "invalidated", "missing")}
    report = {
        "timestamp": now_iso(),
        "current_signal_date": current_date,
        "session_phase": phase,
        "overall_status": overall_status(files),
        "summary": summarize(files),
        "counts": counts,
        "files": files,
        "rules": [
            "trusted：可作为当前阶段交易辅助依据。",
            "degraded：可参考但必须降权，需要结合下一步验证。",
            "stale：非当前交易日或阶段，只能作为历史背景。",
            "invalidated/missing：不得作为盘中交易依据，等待重产或修复。",
            "session_relevance：区分同一交易日内的当前可用、阶段回看、待产出和背景参考。",
            "freshness_status：当前阶段文件必须满足各自延迟 SLA；过期实时数据自动降权。",
            "future：文件时间戳超前当前时间，视为时间错位并降权，不参与最新有效时间。",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"data-trust: {report['overall_status']} - {report['summary']}")
    return 0


def trust_row(spec: dict[str, Any], data: Any, current_date: str, quality_issues: list[Any], source_flags: list[str], phase: str, now: datetime) -> dict[str, Any]:
    rel = spec["file"]
    path = ROOT / rel
    reasons: list[str] = []
    status = "trusted"
    ts = data.get("timestamp") if isinstance(data, dict) else ""

    row_signal_date = signal_date_for_row(rel, data, ts)
    if not path.exists() or data in (None, {}):
        status = "missing"
        reasons.append("文件缺失或不可读")
    elif contains_bad_text(path):
        status = "missing"
        reasons.append("文件含异常文本或疑似乱码")
    elif isinstance(data, dict) and data.get("source_status") == "invalidated":
        status = "invalidated"
        reasons.append(data.get("note") or "数据批次已撤下")
    elif row_signal_date and current_date and row_signal_date != current_date:
        status = "stale"
        reasons.append(f"数据交易日不是当前交易日：{row_signal_date}")
    elif rel.endswith("decision-feed.json"):
        feed_status, feed_reasons = decision_feed_status(data)
        status = worse_status(status, feed_status)
        reasons.extend(feed_reasons)

    file_issues = [
        issue.get("message", "")
        for issue in quality_issues
        if isinstance(issue, dict) and issue.get("file") == Path(rel).name and issue.get("severity") in {"critical", "warning"}
    ]
    if file_issues and status not in {"missing", "invalidated"}:
        status = worse_status(status, "degraded")
        reasons.extend(file_issues[:2])
    if spec.get("depends_on_source") and source_flags and status not in {"missing", "invalidated", "stale"}:
        status = worse_status(status, "degraded")
        reasons.extend(source_flags[:2])

    reasons = clean_list(reasons)
    session = session_relevance(spec, status, phase)
    freshness_limit = effective_freshness_minutes(spec, phase)
    freshness = freshness_state(spec, ts, status, session["relevance"], phase, now)
    if freshness["status"] in {"stale", "future"} and status not in {"missing", "invalidated", "stale"}:
        status = worse_status(status, "degraded")
        reasons = clean_list([*reasons, freshness["reason"]])
    return {
        "file": rel,
        "label": spec["label"],
        "role": spec["role"],
        "timestamp": ts or "",
        "signal_date": row_signal_date or "",
        "status": status,
        "session_phase": phase,
        "session_relevance": session["relevance"],
        "session_action": session["action"],
        "session_reason": session["reason"],
        "freshness_status": freshness["status"],
        "freshness_minutes": freshness_limit,
        "age_minutes": freshness["age_minutes"],
        "freshness_action": freshness["action"],
        "freshness_reason": freshness["reason"],
        "trust_score": trust_score(status, reasons, session["relevance"], freshness["status"]),
        "usable": status in {"trusted", "degraded", "stale"},
        "use_action": action_for(status),
        "reason": trim("；".join(reasons) or "结构与时间戳正常", 220),
    }


def decision_feed_status(data: Any) -> tuple[str, list[str]]:
    if not isinstance(data, dict):
        return "missing", ["机会风险流不是对象"]
    reasons = []
    status = "trusted"
    for section in ("opportunities", "risks", "verifications"):
        rows = data.get(section)
        if not isinstance(rows, list):
            status = worse_status(status, "degraded")
            reasons.append(f"{section} 缺失或不是数组")
            continue
        for index, item in enumerate(rows):
            if not isinstance(item, dict):
                status = worse_status(status, "degraded")
                reasons.append(f"{section}[{index}] 不是对象")
                continue
            if item.get("signal_grade") not in {"A", "B", "C", "D"}:
                status = worse_status(status, "degraded")
                reasons.append(f"{section}[{index}] 缺少有效信号等级")
            if not item.get("use_action"):
                status = worse_status(status, "degraded")
                reasons.append(f"{section}[{index}] 缺少使用动作")
    quality_gate = data.get("quality_gate") or {}
    if quality_gate.get("status") in {"degraded", "critical"}:
        status = worse_status(status, "degraded")
        reasons.append(quality_gate.get("summary") or "决策流继承全局数据降级")
    return status, clean_list(reasons)[:4]


def degraded_source_flags(source_health: Any) -> list[str]:
    if not isinstance(source_health, dict):
        return []
    rows = []
    sources = source_health.get("sources") or {}
    iterator = sources.items() if isinstance(sources, dict) else []
    for name, source in iterator:
        if not isinstance(source, dict):
            continue
        if source.get("status") in {"degraded", "bad", "failed"}:
            rows.append(source_flag_message(name, source))
    return clean_list(rows)


def source_flag_message(name: str, source: dict[str, Any]) -> str:
    text = f"{name}: {source.get('note') or source.get('detail') or source.get('usage') or source.get('status')}"
    if re.search(r"Can not decode value starting with|JSON decode failed|proxy disconnect|failed with|decode failed", text, re.I):
        if re.search(r"hk|港股|stock_hk|Eastmoney|push2", text, re.I):
            return "港股结构行情源连接/解码异常，港股映射和收盘窗口价格需二次复核。"
        if re.search(r"japan|korea|nikkei|kospi|日韩|日经|韩国", text, re.I):
            return "日韩早盘实时源异常，页面仅保留待复核清单，不展示未核实数值。"
        return "A股补充行情源解码异常，盘中异动和个股涨跌幅需以已审计源复核。"
    return text


def overall_status(files: list[dict[str, Any]]) -> str:
    statuses = {row["status"] for row in files}
    if statuses & {"missing", "invalidated"}:
        return "degraded"
    if statuses & {"degraded", "stale"}:
        return "degraded"
    return "trusted"


def summarize(files: list[dict[str, Any]]) -> str:
    blocked = [row for row in files if row["status"] in {"missing", "invalidated"}]
    degraded = [row for row in files if row["status"] == "degraded"]
    stale = [row for row in files if row["status"] == "stale"]
    historical = [row for row in files if row.get("session_relevance") == "historical" and row["status"] not in {"stale", "missing", "invalidated"}]
    freshness_stale = [row for row in files if row.get("freshness_status") == "stale" and row.get("session_relevance") == "current"]
    suffix_parts = []
    if historical:
        suffix_parts.append(f"{len(historical)} 个同日文件已过当前阶段")
    if freshness_stale:
        suffix_parts.append(f"{len(freshness_stale)} 个当前阶段文件超时")
    suffix = "，" + "，".join(suffix_parts) if suffix_parts else ""
    if blocked:
        names = "、".join(row["label"] for row in blocked[:3])
        return f"{len(blocked)} 个数据文件不可用（{names}），{len(degraded)} 个文件需降权{suffix}。"
    if degraded or stale:
        return f"{len(degraded)} 个数据文件需降权，{len(stale)} 个文件仅作历史背景{suffix}。"
    return "核心数据文件可信，可作为当前阶段辅助依据。"


def action_for(status: str) -> str:
    return {
        "trusted": "正常使用",
        "degraded": "降权参考",
        "stale": "仅作背景",
        "invalidated": "等待重产",
        "missing": "修复后再用",
    }.get(status, "待确认")


def trust_score(status: str, reasons: list[str], relevance: str = "current", freshness: str = "fresh") -> int:
    base = {
        "trusted": 92,
        "degraded": 62,
        "stale": 45,
        "invalidated": 10,
        "missing": 0,
    }.get(status, 50)
    session_penalty = {"historical": 18, "upcoming": 10, "background": 0, "current": 0}.get(relevance, 0)
    freshness_penalty = {"future": 28, "stale": 24, "aging": 10, "unknown": 8, "phase_expired": 0, "fresh": 0}.get(freshness, 0)
    return max(0, min(100, base - min(20, len(reasons) * 4) - session_penalty - freshness_penalty))


def freshness_state(spec: dict[str, Any], ts: Any, status: str, relevance: str, phase: str, now: datetime) -> dict[str, Any]:
    if status in {"missing", "invalidated"}:
        return {
            "status": "blocked",
            "age_minutes": None,
            "action": "等待修复",
            "reason": "文件不可用，无法判断新鲜度",
        }
    parsed = parse_timestamp(ts)
    if not parsed:
        return {
            "status": "unknown",
            "age_minutes": None,
            "action": "时间待确认",
            "reason": "缺少可解析 timestamp",
        }
    future_seconds = (parsed - now).total_seconds()
    if future_seconds > FUTURE_TIMESTAMP_TOLERANCE_SECONDS:
        future_minutes = int(future_seconds // 60)
        return {
            "status": "future",
            "age_minutes": -future_minutes,
            "action": "时间超前，降权复核",
            "reason": f"{spec.get('label', '该文件')} timestamp 超前当前时间约 {future_minutes} 分钟",
        }
    age = max(0, int((now - parsed).total_seconds() // 60))
    limit = effective_freshness_minutes(spec, phase)
    label = spec.get("label", "该文件")
    if relevance != "current":
        return {
            "status": "phase_expired",
            "age_minutes": age,
            "action": "不按实时新鲜度使用",
            "reason": f"{label}不是当前实时阶段，按阶段状态处理",
        }
    if limit and age > limit:
        return {
            "status": "stale",
            "age_minutes": age,
            "action": "当前阶段降权",
            "reason": f"{label}已 {age} 分钟未刷新，超过 {limit} 分钟 SLA",
        }
    if limit and age > max(1, int(limit * 0.7)):
        return {
            "status": "aging",
            "age_minutes": age,
            "action": "临近超时",
            "reason": f"{label}已 {age} 分钟未刷新，接近 {limit} 分钟 SLA",
        }
    return {
        "status": "fresh",
        "age_minutes": age,
        "action": "新鲜度正常",
        "reason": f"{label}刷新延迟 {age} 分钟，未超过 {limit} 分钟 SLA",
    }


def effective_freshness_minutes(spec: dict[str, Any], phase: str) -> int:
    session = spec.get("session")
    base = int(spec.get("freshness_minutes") or 0)
    if session == "postmarket" and phase in {"evening", "overnight", "premarket"}:
        return max(base, 1080)
    if session == "evening" and phase in {"overnight", "premarket"}:
        return max(base, 900)
    return base


def parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?", text)
        if not match:
            return None
        try:
            parsed = datetime.fromisoformat(match.group(0))
        except Exception:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def trading_phase(now: datetime) -> str:
    hhmm = now.hour * 100 + now.minute
    if 830 <= hhmm < 930:
        return "premarket"
    if 930 <= hhmm < 1130:
        return "morning"
    if 1130 <= hhmm < 1300:
        return "midday"
    if 1300 <= hhmm < 1500:
        return "afternoon"
    if 1500 <= hhmm < 2000:
        return "postmarket"
    if hhmm >= 2000:
        return "evening"
    return "overnight"


def session_relevance(spec: dict[str, Any], status: str, phase: str) -> dict[str, str]:
    if status in {"missing", "invalidated"}:
        return {
            "relevance": "blocked",
            "action": "不可用于当前决策",
            "reason": "文件不可用或已撤下，阶段判断让位于重产/修复",
        }
    session = spec.get("session", "background")
    label = spec.get("label", "该文件")
    if status == "stale":
        return {
            "relevance": "historical",
            "action": "仅作历史背景",
            "reason": f"{label}不是当前交易日数据",
        }
    if session == "background":
        return {
            "relevance": "background",
            "action": "中期背景参考",
            "reason": "专题/配置类结论不绑定单一盘中阶段",
        }
    if session == "decision":
        current_phases = {"premarket", "morning", "midday", "afternoon", "postmarket", "evening", "overnight"}
        return {
            "relevance": "current" if phase in current_phases else "historical",
            "action": "当前决策流" if phase in current_phases else "隔夜前需重刷",
            "reason": "机会风险流随核心数据刷新，需结合文件可信度使用",
        }
    matrix = {
        "premarket": {"current": {"premarket", "morning"}, "upcoming": {"overnight"}, "historical": {"midday", "afternoon", "postmarket", "evening"}},
        "midday": {"current": {"midday", "afternoon"}, "upcoming": {"overnight", "premarket", "morning"}, "historical": {"postmarket", "evening"}},
        "market": {"current": {"morning", "afternoon"}, "upcoming": {"overnight", "premarket"}, "historical": {"midday", "postmarket", "evening"}},
        "postmarket": {"current": {"postmarket", "evening", "overnight", "premarket"}, "upcoming": {"morning", "midday", "afternoon"}, "historical": set()},
        "evening": {"current": {"evening", "overnight", "premarket"}, "upcoming": {"morning", "midday", "afternoon", "postmarket"}, "historical": set()},
    }
    bucket = matrix.get(session, {})
    for relevance, phases in bucket.items():
        if phase in phases:
            return session_action(label, session, relevance, phase)
    return {
        "relevance": "background",
        "action": "背景参考",
        "reason": f"{label}与当前阶段 {phase} 不直接匹配",
    }


def session_action(label: str, session: str, relevance: str, phase: str) -> dict[str, str]:
    if relevance == "current":
        return {
            "relevance": "current",
            "action": "当前阶段可用",
            "reason": f"{label}匹配当前交易阶段：{phase}",
        }
    if relevance == "upcoming":
        return {
            "relevance": "upcoming",
            "action": "等待对应阶段产出",
            "reason": f"{label}对应阶段尚未到来，不能提前当成已验证信号",
        }
    notes = {
        "premarket": "早盘研判已过当前阶段，只能复盘开盘假设是否兑现",
        "midday": "午盘研判已过当前阶段，只能回看午后验证框架",
        "market": "盘中实时信号已过交易窗口，只能复盘当日结构",
    }
    return {
        "relevance": "historical",
        "action": "阶段回看",
        "reason": notes.get(session, f"{label}已过当前阶段"),
    }


def worse_status(left: str, right: str) -> str:
    order = {"trusted": 0, "degraded": 1, "stale": 2, "invalidated": 3, "missing": 4}
    reverse = {value: key for key, value in order.items()}
    return reverse[max(order.get(left, 1), order.get(right, 1))]


def latest_signal_date(payloads: dict[str, Any]) -> str:
    dates = []
    for rel in ("data/theme-shifts.json", "data/decision-feed.json"):
        data = payloads.get(rel)
        if isinstance(data, dict) and data.get("current_signal_date"):
            dates.append(str(data.get("current_signal_date")))
    for rel in ("data/premarket.json", "data/opportunity-watch.json", "data/alert.json", "data/intraday.json", "data/midday.json", "data/postmarket.json", "data/topics.json"):
        data = payloads.get(rel)
        date = signal_date(data.get("timestamp") if isinstance(data, dict) else "")
        if date:
            dates.append(date)
    return sorted(dates)[-1] if dates else now_iso()[:10]


def signal_date_for_row(rel: str, data: Any, timestamp: Any) -> str:
    if isinstance(data, dict) and rel in {"data/theme-shifts.json", "data/decision-feed.json"}:
        current_signal_date = data.get("current_signal_date")
        if current_signal_date:
            return str(current_signal_date)
    return signal_date(timestamp)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def contains_bad_text(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return True
    return any(literal in text for literal in BAD_LITERALS) or bool(MOJIBAKE_PATTERN.search(text))


def signal_date(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


def clean_list(values: list[Any]) -> list[str]:
    rows = []
    seen = set()
    for value in values:
        text = trim(value, 240)
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

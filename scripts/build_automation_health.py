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
OUT = DATA_DIR / "automation-health.json"
TZ = timezone(timedelta(hours=8))


EXPECTED = [
    {"id": "premarket", "label": "盘前简报", "file": "premarket.json", "due": "09:25", "grace_minutes": 20, "blocking": False},
    {"id": "intraday", "label": "盘中全景", "file": "intraday.json", "due": "15:05", "grace_minutes": 90, "blocking": False},
    {"id": "alerts", "label": "盘中异动", "file": "alert.json", "due": "15:00", "grace_minutes": 5, "blocking": True},
    {"id": "midday", "label": "午盘分析", "file": "midday.json", "due": "11:30", "grace_minutes": 30, "blocking": False},
    {"id": "postmarket", "label": "盘后复盘", "file": "postmarket.json", "due": "15:30", "grace_minutes": 60, "blocking": False},
    {"id": "evening", "label": "晚间舆情", "file": "evening-sentiment.json", "due": "20:00", "grace_minutes": 90, "blocking": False},
    {"id": "topics", "label": "专题跟踪", "file": "topics.json", "due": "15:30", "grace_minutes": 180, "blocking": False},
]


def main() -> int:
    now = datetime.now(TZ)
    current_date = current_signal_date()
    context = resolve_cn_trading_context(ROOT, now, [current_date])
    target_date = context.target_trade_date.isoformat()
    source_health = load_json(DATA_DIR / "source-health.json")
    quality = load_json(DATA_DIR / "quality-report.json")
    rows = [check_expected(item, now, current_date, target_date, source_health, quality) for item in EXPECTED]
    next_session = build_next_session_readiness(now, target_date)
    counts = {
        "ok": sum(1 for row in rows if row["status"] == "ok"),
        "late": sum(1 for row in rows if row["status"] == "late"),
        "missing": sum(1 for row in rows if row["status"] == "missing"),
        "invalidated": sum(1 for row in rows if row["status"] == "invalidated"),
        "waiting": sum(1 for row in rows if row["status"] == "waiting"),
    }
    report = {
        "timestamp": now_iso(now),
        "current_signal_date": current_date,
        "target_trade_date": target_date,
        "calendar_version": context.calendar_version,
        "calendar_state": context.phase,
        "overall_status": overall_status(rows),
        "summary": summarize(rows),
        "counts": counts,
        "processes": rows,
        "next_session_readiness": next_session,
        "rules": [
            "ok：当日文件已产出且未撤下。",
            "waiting：当前时间尚未到该自动化应产出窗口。",
            "late/missing：到点后仍未产出或时间戳非当日。",
            "invalidated：文件存在但 source_status=invalidated，不得作为交易依据。",
            "failure_type/diagnosis/next_actions 用于区分数据源污染、产出缺失、时间戳异常和等待窗口。",
            "next_session_readiness 用于跨日/开盘前提示下一交易日必须产出的文件，不替代当前信号日期状态。",
            "休市日以交易所日历定位上一市场日和下一交易日；周末/节假日不产生虚假逾期。",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"automation-health: {report['overall_status']} - {report['summary']}")
    return 0


def build_next_session_readiness(now: datetime, target_date: str) -> dict[str, Any]:
    rows = [next_session_row(spec, now, target_date) for spec in EXPECTED]
    pending = [row for row in rows if row["status"] == "pending"]
    ready = [row for row in rows if row["status"] == "ready"]
    overdue = [row for row in rows if row["status"] == "overdue"]
    status = "overdue" if overdue else ("pending" if pending else "ready")
    if overdue:
        summary = f"{target_date} 有 {len(overdue)} 个产出已过窗口未更新。"
    elif pending:
        first = pending[0]
        summary = f"{target_date} 开盘链路待产出：{first['label']} {first['due']}。"
    else:
        summary = f"{target_date} 关键产出已就绪。"
    return {
        "target_trade_date": target_date,
        "status": status,
        "summary": summary,
        "pending_count": len(pending),
        "ready_count": len(ready),
        "overdue_count": len(overdue),
        "items": rows,
    }


def next_session_row(spec: dict[str, Any], now: datetime, target_date: str) -> dict[str, Any]:
    path = DATA_DIR / spec["file"]
    data = load_json(path)
    ts = data.get("timestamp") if isinstance(data, dict) else ""
    file_date = signal_date(ts)
    due_at = due_datetime(target_date, spec["due"])
    deadline = due_at + timedelta(minutes=int(spec["grace_minutes"]))
    if file_date == target_date and isinstance(data, dict) and data.get("source_status") != "invalidated":
        status = "ready"
        action = "已产出"
        reason = "目标交易日文件已更新"
    elif now < due_at:
        status = "pending"
        action = "等待产出"
        reason = f"计划 {spec['due']} 后产出"
    elif now < deadline:
        status = "pending"
        action = "等待宽限"
        reason = f"已到计划时间，宽限至 {deadline.strftime('%H:%M')}"
    else:
        status = "overdue"
        action = "需要重跑"
        reason = f"目标交易日尚未产出：当前文件日期 {file_date or '无'}"
    return {
        "id": spec["id"],
        "label": spec["label"],
        "file": f"data/{spec['file']}",
        "due": spec["due"],
        "deadline": now_iso(deadline),
        "timestamp": ts or "",
        "file_date": file_date or "",
        "status": status,
        "action": action,
        "reason": reason,
    }


def check_expected(spec: dict[str, Any], now: datetime, current_date: str, target_date: str, source_health: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    path = DATA_DIR / spec["file"]
    due_at = due_datetime(current_date, spec["due"])
    deadline = due_at + timedelta(minutes=int(spec["grace_minutes"]))
    data = load_json(path)
    ts = data.get("timestamp") if isinstance(data, dict) else ""
    file_date = signal_date(ts)
    status = "ok"
    action = "正常使用"
    reason = "当日产出已到位"
    weekend_evening_update = spec["id"] == "evening" and current_date < file_date < target_date
    if weekend_evening_update:
        status = "ok"
        action = "用于下一交易日预案"
        reason = f"休市期间增量已更新：{file_date}，目标交易日 {target_date}"
    elif now < due_at:
        status = "waiting"
        action = "等待产出"
        reason = f"计划 {spec['due']} 后产出"
    elif not path.exists() or not isinstance(data, dict) or not ts:
        status = "missing" if now >= deadline else "waiting"
        action = "检查自动化进程" if status == "missing" else "等待产出"
        reason = "文件缺失或缺少 timestamp"
    elif file_date != current_date:
        status = "late" if now >= deadline else "waiting"
        action = "重跑该自动化" if status == "late" else "等待当日产出"
        reason = f"时间戳不是当前交易日：{ts}"
    elif data.get("source_status") == "invalidated":
        status = "invalidated"
        action = "等待重产"
        reason = data.get("note") or "文件已撤下污染批次"
    elif parse_timestamp(ts) and parse_timestamp(ts) > deadline + timedelta(hours=12):
        status = "late"
        action = "复核时间戳"
        reason = f"时间戳异常超前：{ts}"
    diagnosis = diagnose(spec, status, reason, data if isinstance(data, dict) else {}, source_health, quality)
    return {
        "id": spec["id"],
        "label": spec["label"],
        "file": f"data/{spec['file']}",
        "due": spec["due"],
        "deadline": now_iso(deadline),
        "timestamp": ts or "",
        "status": status,
        "blocking": bool(spec.get("blocking")) and status in {"missing", "invalidated", "late"},
        "action": action,
        "reason": reason,
        "failure_type": diagnosis["failure_type"],
        "diagnosis": diagnosis["diagnosis"],
        "next_actions": diagnosis["next_actions"],
        "related_sources": diagnosis["related_sources"],
    }


def diagnose(spec: dict[str, Any], status: str, reason: str, data: dict[str, Any], source_health: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    source_flags = degraded_sources(source_health)
    quality_hits = [
        item.get("message", "")
        for item in quality.get("issues", [])
        if isinstance(item, dict) and item.get("file") == spec["file"]
    ]
    if status == "ok":
        return {
            "failure_type": "none",
            "diagnosis": "产出正常，未发现自动化层异常。",
            "next_actions": ["正常读取；仍需结合数据质量卡判断是否降权。"],
            "related_sources": [],
        }
    if status == "waiting":
        return {
            "failure_type": "not_due",
            "diagnosis": "尚未到该自动化的计划产出窗口。",
            "next_actions": [f"到 {spec['due']} 后再检查是否产出。"],
            "related_sources": [],
        }
    if status == "invalidated":
        related = [name for name, text in source_flags if any(token in text for token in ("污染", "decode", "akshare", "异常"))]
        return {
            "failure_type": "invalidated_source_batch",
            "diagnosis": reason,
            "next_actions": [
                "先修复或切换污染行情源，禁止直接恢复旧 alert。",
                "重跑对应自动化，写入新的 JSON 后再执行统一构建。",
                "重产前盘中异动只作为监测盲区，不作为交易触发依据。",
            ],
            "related_sources": related or [name for name, _ in source_flags[:3]],
        }
    if status == "missing":
        return {
            "failure_type": "missing_output",
            "diagnosis": "到点后没有看到有效 JSON 产出，优先检查自动化进程是否运行。",
            "next_actions": [
                "检查对应自动化进程是否仍在运行。",
                "查看最近一次模型/脚本输出是否报错。",
                "手动重跑该自动化并触发统一构建。",
            ],
            "related_sources": [name for name, _ in source_flags[:3]],
        }
    if status == "late":
        return {
            "failure_type": "stale_or_time_anomaly",
            "diagnosis": reason,
            "next_actions": [
                "核对文件 timestamp 是否由自动化真实写入。",
                "重跑自动化，避免使用上一交易日或异常超前数据。",
            ],
            "related_sources": [name for name, _ in source_flags[:3]],
        }
    return {
        "failure_type": "unknown",
        "diagnosis": reason or "自动化状态未知。",
        "next_actions": ["检查自动化日志并重跑统一构建。"],
        "related_sources": [name for name, _ in source_flags[:3]],
    }


def degraded_sources(source_health: dict[str, Any]) -> list[tuple[str, str]]:
    sources = source_health.get("sources") if isinstance(source_health, dict) else {}
    rows = []
    iterator = sources.items() if isinstance(sources, dict) else []
    for name, source in iterator:
        if not isinstance(source, dict):
            continue
        if source.get("status") in {"degraded", "bad", "failed"}:
            rows.append((str(name), str(source.get("note") or source.get("detail") or source.get("usage") or source.get("status"))))
    return rows


def overall_status(rows: list[dict[str, Any]]) -> str:
    if any(row["blocking"] for row in rows):
        return "blocked"
    if any(row["status"] in {"missing", "invalidated", "late"} for row in rows):
        return "degraded"
    if any(row["status"] == "waiting" for row in rows):
        return "waiting"
    return "ok"


def summarize(rows: list[dict[str, Any]]) -> str:
    bad = [row for row in rows if row["status"] in {"missing", "invalidated", "late"}]
    waiting = [row for row in rows if row["status"] == "waiting"]
    if bad:
        names = "、".join(row["label"] for row in bad[:4])
        return f"{len(bad)} 个自动化产出异常：{names}。"
    if waiting:
        names = "、".join(row["label"] for row in waiting[:4])
        return f"{len(waiting)} 个自动化尚未到产出窗口：{names}。"
    return "关键自动化产出均已到位。"


def current_signal_date() -> str:
    dates = []
    for name in ("alert.json", "intraday.json", "midday.json", "postmarket.json", "topics.json", "premarket.json"):
        data = load_json(DATA_DIR / name)
        date = signal_date(data.get("timestamp") if isinstance(data, dict) else "")
        if date:
            dates.append(date)
    return sorted(dates)[-1] if dates else now_iso(datetime.now(TZ))[:10]


def due_datetime(date: str, hhmm: str) -> datetime:
    hour, minute = [int(part) for part in hhmm.split(":")]
    return datetime.fromisoformat(date).replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=TZ)


def parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def signal_date(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def now_iso(value: datetime) -> str:
    return value.astimezone(TZ).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

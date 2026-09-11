#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from data_validity import source_window


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "automation-health.json"
TZ = timezone(timedelta(hours=8))


EXPECTED = [
    {"id": "premarket", "label": "盘前简报", "file": "premarket.json", "due": "08:30", "grace_minutes": 5, "blocking": False},
    {"id": "intraday", "label": "盘中全景", "file": "intraday.json", "due": "15:05", "grace_minutes": 90, "blocking": False},
    {"id": "alerts", "label": "盘中异动", "file": "alert.json", "due": "15:00", "grace_minutes": 5, "blocking": True},
    {"id": "midday", "label": "午盘分析", "file": "midday.json", "due": "11:30", "grace_minutes": 30, "blocking": False},
    {"id": "postmarket", "label": "盘后复盘", "file": "postmarket.json", "due": "16:30", "grace_minutes": 10, "blocking": False},
    {"id": "evening", "label": "晚间舆情", "file": "evening-sentiment.json", "due": "20:00", "grace_minutes": 90, "blocking": False},
    {"id": "topics", "label": "专题跟踪", "file": "topics.json", "due": "15:30", "grace_minutes": 180, "blocking": False},
]


def main() -> int:
    now = datetime.now(TZ)
    current_date = current_signal_date()
    _, target_date = calendar_dates(now)
    source_health = load_json(DATA_DIR / "source-health.json")
    quality = load_json(DATA_DIR / "quality-report.json")
    rows = [check_expected(item, now, current_date, source_health, quality) for item in EXPECTED]
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



def required_evidence_at(spec: dict[str, Any], now: datetime, day: str) -> datetime:
    """Latest completed checkpoint, with five minutes for scheduled generation."""
    due = due_datetime(day, spec["due"])
    if spec["id"] != "intraday":
        return due
    checkpoints = ["09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00"]
    eligible = [due_datetime(day, point) for point in checkpoints
                if due_datetime(day, point) + timedelta(minutes=5) <= now]
    return max(eligible) if eligible else due_datetime(day, "09:30")


def evidence_issue(spec: dict[str, Any], data: dict[str, Any], now: datetime, day: str) -> str:
    required = required_evidence_at(spec, now, day)
    stamp = parse_timestamp(data.get("analysis_time") or data.get("timestamp"))
    if not stamp:
        return "分析时间缺失或无法解析"
    if stamp > now + timedelta(seconds=60):
        return "分析时间异常超前"
    if stamp.date().isoformat() != day or stamp < required:
        return f"分析未覆盖应有检查点 {required.strftime('%H:%M')}"
    if spec["id"] == "intraday":
        quote = parse_timestamp(data.get("market_data_as_of") or data.get("market_time"))
        if not quote:
            return "行情时间缺失，不能以文件生成时间替代"
        if quote > now + timedelta(seconds=60):
            return "行情时间异常超前"
        if quote.date().isoformat() != day or quote < required - timedelta(minutes=5):
            return f"行情未覆盖应有检查点 {required.strftime('%H:%M')}"
    return ""


def next_session_row(spec: dict[str, Any], now: datetime, target_date: str) -> dict[str, Any]:
    if spec["id"] == "alerts" and target_date == now.date().isoformat():
        row = monitor_health_row(spec, now, target_date)
        row["status"] = {"ok": "ready", "waiting": "pending", "late": "overdue"}[row["status"]]
        row["file_date"] = str(row["timestamp"])[:10]
        return row
    path = DATA_DIR / spec["file"]
    data = load_json(path)
    ts = data.get("timestamp") if isinstance(data, dict) else ""
    file_date = signal_date(ts)
    due_at = required_evidence_at(spec, now, target_date)
    deadline = due_at + timedelta(minutes=5 if spec["id"] == "intraday" else int(spec["grace_minutes"]))
    issue = evidence_issue(spec, data, now, target_date)
    if file_date == target_date and isinstance(data, dict) and data.get("source_status") != "invalidated" and not issue:
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
        reason = issue or f"目标交易日尚未产出：当前文件日期 {file_date or '无'}"
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


def check_expected(spec: dict[str, Any], now: datetime, current_date: str, source_health: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    if spec["id"] == "alerts":
        return monitor_health_row(spec, now, current_date)
    path = DATA_DIR / spec["file"]
    due_at = required_evidence_at(spec, now, current_date)
    deadline = due_at + timedelta(minutes=5 if spec["id"] == "intraday" else int(spec["grace_minutes"]))
    data = load_json(path)
    ts = data.get("timestamp") if isinstance(data, dict) else ""
    file_date = signal_date(ts)
    status = "ok"
    action = "正常使用"
    reason = "当日产出已到位"
    if now < due_at:
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
    issue = evidence_issue(spec, data, now, current_date)
    if status == "ok" and issue and not locals().get("weekend_evening_update", False):
        status, action, reason = "late", "等待当前检查点数据", issue
    diagnosis = diagnose(spec, status, reason, data if isinstance(data, dict) else {}, source_health, quality)
    return {
        "id": spec["id"],
        "label": spec["label"],
        "file": f"data/{spec['file']}",
        "due": spec["due"],
        "deadline": now_iso(deadline),
        "timestamp": ts or "",
        "status": status,
        "data_status": "degraded" if data.get("source_status") in {"degraded", "degraded_partial"} else ("unavailable" if status in {"late", "missing", "invalidated"} else "check_source_quality"),
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
        if source_window(source) != "current":
            continue
        if source.get("status") in {"degraded", "bad", "failed"}:
            rows.append((str(name), str(source.get("note") or source.get("detail") or source.get("usage") or source.get("status"))))
    return rows


def monitor_health_row(spec, now, day):
    from intraday_recovery import is_trading_day
    live = load_json(ROOT / "logs" / "monitor-signal-bridge-status.json")
    monitor = live.get("monitor") or {}
    stamp = parse_timestamp(live.get("checked_at"))
    heartbeat = parse_timestamp(monitor.get("heartbeat_at"))
    active = is_trading_day(ROOT, now) and ("09:30" <= now.strftime("%H:%M") < "11:30" or "13:00" <= now.strftime("%H:%M") < "15:00")
    recent = bool(stamp and heartbeat and 0 <= (now - stamp).total_seconds() <= 180 and 0 <= (now - heartbeat).total_seconds() <= 180)
    healthy = recent and monitor.get("healthy") is True
    status = "waiting" if not active else ("ok" if healthy else "late")
    reason = "当前不在连续交易时段，保留最近触发供回看" if not active else ("监控和行情检查正常；没有新异动不等于没有运行" if healthy else "监控或行情检查未通过，等待恢复；不能视为市场没有异动")
    return {"id": "alerts", "label": "盘中异动", "file": "data/alert.json", "due": "交易时段持续检查",
            "timestamp": live.get("checked_at", ""), "deadline": now_iso(now), "status": status,
            "data_status": "check_source_quality" if healthy else "unavailable", "blocking": active and not healthy,
            "action": "查看最新触发" if healthy else "查看监控状态", "reason": reason,
            "failure_type": "none" if healthy else ("not_due" if not active else "monitor_or_quote_unavailable"),
            "diagnosis": reason, "next_actions": ["继续检查最新行情与监控心跳；保留历史触发，不补造错过的信号。"], "related_sources": []}


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


def calendar_dates(now: datetime) -> tuple[str, str]:
    paths = [ROOT / "config/cn-market-calendar.json", Path("/Users/sweet_orange/Documents/投资/worktrees/stock-dashboard-v2/config/v2-market-calendar.json")]
    calendar = {}
    for path in paths:
        payload = load_json(path)
        rows = payload.get("calendars", [payload])
        calendar = next((row for row in rows if row.get("market", "CN") == "CN" and row.get("verification_state") == "verified"), {})
        if calendar:
            break
    def opened(day):
        key = day.isoformat()
        if not calendar or not calendar.get("valid_from", "") <= key <= calendar.get("valid_to", ""):
            raise ValueError("calendar_unverified_or_outside_coverage")
        return key in calendar.get("extra_open_days", []) or (day.weekday() not in calendar.get("weekend_days", [5,6]) and key not in calendar.get("holidays", []))
    previous = target = now.date()
    for _ in range(30):
        if opened(previous):
            break
        previous -= timedelta(days=1)
    for _ in range(30):
        if opened(target):
            break
        target += timedelta(days=1)
    return previous.isoformat(), target.isoformat()


def current_signal_date() -> str:
    return calendar_dates(datetime.now(TZ))[0]


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

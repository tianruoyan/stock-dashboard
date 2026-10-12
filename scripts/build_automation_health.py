#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from data_validity import source_window, topic_current
from intraday_recovery import close_quote_issue, index_quote_rows, parse_datetime


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "automation-health.json"
TZ = timezone(timedelta(hours=8))


EXPECTED = [
    {"id": "premarket", "label": "盘前简报", "file": "premarket.json", "due": "08:30", "grace_minutes": 5, "blocking": False},
    {"id": "intraday", "label": "盘中全景", "file": "intraday.json", "due": "15:05", "grace_minutes": 90, "blocking": False},
    {"id": "alerts", "label": "盘中异动", "file": "alert.json", "due": "15:00", "grace_minutes": 5, "blocking": True},
    {"id": "midday", "label": "午盘分析", "file": "midday.json", "due": "11:30", "grace_minutes": 30, "blocking": False},
    {"id": "postmarket", "label": "盘后复盘", "file": "postmarket.json", "due": "15:10", "grace_minutes": 10, "blocking": False},
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
            "ok：实际分析与所需行情分别覆盖检查点，不能以文件或采集时间代替。",
            "waiting：当前时间尚未到该自动化应产出窗口。",
            "late/missing：到点后仍未产出或时间戳非当日。",
            "invalidated：文件存在但 source_status=invalidated，不得作为交易依据。",
            "failure_type/diagnosis/next_actions 用于区分数据源污染、产出缺失、时间戳异常和等待窗口。",
            "next_session_readiness 用于跨日/开盘前提示下一交易日必须产出的文件，不替代当前信号日期状态。",
            "专题15:30要求真实研究；18:30只是宽限截止，不是第二个研究生产任务。代表股事实补采不刷新研究时间。",
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


def timestamp_coverage(value: Any, required: datetime, now: datetime, label: str) -> dict[str, Any]:
    stamp = parse_datetime(value)
    result = {"status": "ready", "timestamp": now_iso(stamp) if stamp else "",
              "required_at": now_iso(required), "reason": ""}
    if not stamp:
        result.update(status="missing", reason=f"{label}时间缺失或无法解析")
    elif stamp > now + timedelta(seconds=60):
        result.update(status="future", reason=f"{label}时间异常超前")
    elif stamp.date() != required.date() or stamp < required:
        result.update(status="stale", reason=f"{label}未覆盖应有检查点 {required.strftime('%H:%M')}")
    return result


def topic_coverage(data: dict[str, Any], now: datetime, required: datetime) -> dict[str, Any]:
    """Check individual research, independently of file and quote refreshes."""
    research, representatives = [], []
    for item in data.get("topics") or []:
        if not isinstance(item, dict):
            continue
        stamp = item.get("analysis_time") or item.get("research_updated_at") or item.get("updated_at") or item.get("timestamp")
        row = timestamp_coverage(stamp, required, now, "专题研究")
        row["name"] = item.get("name") or "未命名专题"
        if item.get("update_scope") == "closing_representatives_only":
            row.update(status="missing", timestamp="", reason="仅更新代表股事实，未产出专题研究")
        elif not item.get("conclusion") or item.get("source_status") == "invalidated":
            row.update(status="missing", reason="专题研究结论缺失或已撤下")
        elif row["status"] == "ready" and not topic_current(item, required.date().isoformat(), now=now):
            row.update(status="missing", reason="专题研究或来源时间无效、超前、非当日或已过有效期")
        research.append(row)
        facts = item.get("representative_facts")
        # Read old producer output truthfully without rewriting its history.
        if not isinstance(facts, dict) and item.get("update_scope") == "closing_representatives_only":
            facts = item
        if isinstance(facts, dict):
            rep_required = required.replace(hour=15, minute=0)
            rep = timestamp_coverage(facts.get("source_as_of"), rep_required, now, "代表股行情")
            quotes = facts.get("representatives") or []
            issue = close_quote_issue({"indices": quotes}, now, required.date().isoformat()) if quotes else "代表股明细缺失"
            if issue:
                rep.update(status="missing", reason=issue)
            rep["name"] = row["name"]
            representatives.append(rep)
    ready = sum(row["status"] == "ready" for row in research)
    status = "ready" if research and ready == len(research) else ("partial" if ready else "missing")
    reason = "" if status == "ready" else f"专题研究未覆盖15:30检查点（{ready}/{len(research)}项）；代表股事实更新不替代研究"
    rep_ready = sum(row["status"] == "ready" for row in representatives)
    return {
        "research_coverage": {"status": status, "ready_count": ready, "total_count": len(research),
                              "required_at": now_iso(required), "reason": reason, "items": research},
        "representative_coverage": {"status": "available" if rep_ready else "missing", "ready_count": rep_ready,
                                    "total_count": len(research), "scope": "representatives_only", "items": representatives},
        "producer_scope": "representative_facts_only_in_repo",
        "research_producer": "external_codex_schedule_requires_mac_verification",
        "research_due": "15:30", "grace_deadline": "18:30", "grace_is_producer": False,
    }


def evidence_coverage(spec: dict[str, Any], data: dict[str, Any], now: datetime, day: str) -> dict[str, Any]:
    required = required_evidence_at(spec, now, day)
    if spec["id"] == "topics":
        return topic_coverage(data, now, required)
    analysis = timestamp_coverage(data.get("analysis_time") or data.get("timestamp"), required, now, "分析")
    if "intraday_factual_snapshot" in str(data.get("status") or ""):
        analysis.update(status="missing", reason="仅有行情事实快照，尚无本检查点分析")
    result = {"analysis_coverage": analysis}
    if spec["id"] == "intraday":
        result["recovery_scope"] = "quotes_only"
        result["analysis_producer"] = "external_codex_schedule_requires_mac_verification"
        close = required.hour == 15
        quote_required = required if close else required - timedelta(minutes=5)
        rows = index_quote_rows(data)
        stamps = [parse_datetime(row.get("quote_time")) for row in rows]
        valid = [stamp for stamp in stamps if stamp]
        value = min(valid) if valid else (data.get("market_data_as_of") or data.get("market_time"))
        quote = timestamp_coverage(value, quote_required, now, "行情")
        if close:
            issue = close_quote_issue(data, now, day)
            if issue:
                state = "future" if "超前" in issue else ("missing" if "缺少" in issue else "stale")
                quote.update(status=state, reason=issue)
        elif rows and (len(valid) != len(rows) or any(stamp > now + timedelta(seconds=60) for stamp in valid)):
            quote.update(status="missing", reason="部分指数行情时间缺失或异常超前")
        result["quote_coverage"] = quote
    return result


def evidence_issue(spec: dict[str, Any], data: dict[str, Any], now: datetime, day: str) -> str:
    coverage = evidence_coverage(spec, data, now, day)
    keys = ("research_coverage",) if spec["id"] == "topics" else ("analysis_coverage", "quote_coverage")
    return "；".join(coverage[key]["reason"] for key in keys if key in coverage and coverage[key].get("reason"))


def next_session_row(spec: dict[str, Any], now: datetime, target_date: str) -> dict[str, Any]:
    if spec["id"] == "alerts" and target_date == now.date().isoformat():
        row = monitor_health_row(spec, now, target_date)
        row["status"] = {"ok": "ready", "waiting": "pending", "late": "overdue"}[row["status"]]
        row["file_date"] = str(row["timestamp"])[:10]
        return row
    path = DATA_DIR / spec["file"]
    data = load_json(path)
    data = data if isinstance(data, dict) else {}
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
        **evidence_coverage(spec, data, now, target_date),
    }


def check_expected(spec: dict[str, Any], now: datetime, current_date: str, source_health: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    if spec["id"] == "alerts":
        return monitor_health_row(spec, now, current_date)
    path = DATA_DIR / spec["file"]
    due_at = required_evidence_at(spec, now, current_date)
    deadline = due_at + timedelta(minutes=5 if spec["id"] == "intraday" else int(spec["grace_minutes"]))
    data = load_json(path)
    data = data if isinstance(data, dict) else {}
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
    if status == "ok" and issue:
        status = "waiting" if now < deadline else "late"
        action, reason = "等待当前检查点数据", issue
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
        **evidence_coverage(spec, data, now, current_date),
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
    if spec["id"] == "topics" and status != "invalidated":
        return {
            "failure_type": "research_checkpoint_pending" if status == "waiting" else "missing_topic_research",
            "diagnosis": reason,
            "next_actions": [
                "15:30是专题研究检查点；18:30仅为宽限截止，不是第二次生产任务。",
                "build_topics.py只补代表股事实；重跑不能补齐缺失研究，不能改写原研究时间。",
                "需在Mac核验仓库外的实际研究任务、Codex调度和运行日志；此处未验证或修改该调度。",
            ],
            "related_sources": [],
        }
    if spec["id"] == "intraday" and status in {"late", "missing"}:
        return {
            "failure_type": "missing_intraday_checkpoint",
            "diagnosis": reason,
            "next_actions": [
                "分别检查行情与分析覆盖；收盘行情必须来自当日15:00及之后的真实报价。",
                "行情恢复只补事实，保留原分析时间，不补造错过的15:00分析。",
                "缺失分析需在Mac核验仓库外的研究任务与Codex调度；不能由补采成功视为恢复。",
            ],
            "related_sources": [name for name, _ in source_flags[:3]],
        }
    if status == "waiting":
        return {
            "failure_type": "not_due",
            "diagnosis": reason,
            "next_actions": [f"计划 {spec['due']} 产出；宽限内继续检查实际证据。"],
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

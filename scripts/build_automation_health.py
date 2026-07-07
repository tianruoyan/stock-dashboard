#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
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
    rows = [check_expected(item, now, current_date) for item in EXPECTED]
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
        "overall_status": overall_status(rows),
        "summary": summarize(rows),
        "counts": counts,
        "processes": rows,
        "rules": [
            "ok：当日文件已产出且未撤下。",
            "waiting：当前时间尚未到该自动化应产出窗口。",
            "late/missing：到点后仍未产出或时间戳非当日。",
            "invalidated：文件存在但 source_status=invalidated，不得作为交易依据。",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"automation-health: {report['overall_status']} - {report['summary']}")
    return 0


def check_expected(spec: dict[str, Any], now: datetime, current_date: str) -> dict[str, Any]:
    path = DATA_DIR / spec["file"]
    due_at = due_datetime(current_date, spec["due"])
    deadline = due_at + timedelta(minutes=int(spec["grace_minutes"]))
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
    }


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

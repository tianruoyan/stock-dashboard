#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
INVESTMENT_ROOT = ROOT.parent / "Documents" / "投资"
DEFAULT_SIGNAL_LOG = INVESTMENT_ROOT / "data" / "signals.jsonl"
DEFAULT_MONITOR_STATUS = INVESTMENT_ROOT / "monitor.status.json"
DEFAULT_MONITOR_LOG = INVESTMENT_ROOT / "monitor.log"
DEFAULT_MONITOR_START = INVESTMENT_ROOT / "run_monitor_guard.sh"
DEFAULT_ALERT_PATH = ROOT / "data" / "alert.json"
DEFAULT_STATUS_PATH = ROOT / "logs" / "monitor-signal-bridge-status.json"
LOCK_PATH = ROOT / ".monitor-signal-bridge.lock"
PUBLISH_LOCK_PATH = ROOT / ".publish-lock"
ACTIVE_DIR = ROOT / ".monitor-signal-write-active"
PENDING_PATH = ROOT / ".publish-pending"
MAX_ALERTS = 20
HEARTBEAT_MINUTES = 4
MONITOR_STALE_SECONDS = 210
VALID_MARKER = "当前小登题材强度"
ERROR_MARKER = "行情源异常"


def main() -> int:
    parser = argparse.ArgumentParser(description="将老登/小登实时监控信号接入 V1 盘中异动")
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNAL_LOG)
    parser.add_argument("--monitor-status", type=Path, default=DEFAULT_MONITOR_STATUS)
    parser.add_argument("--monitor-log", type=Path, default=DEFAULT_MONITOR_LOG)
    parser.add_argument("--monitor-start", type=Path, default=DEFAULT_MONITOR_START)
    parser.add_argument("--output", type=Path, default=DEFAULT_ALERT_PATH)
    parser.add_argument("--status-output", type=Path, default=DEFAULT_STATUS_PATH)
    parser.add_argument("--calendar", type=Path, default=ROOT / "config" / "cn-market-calendar.json")
    parser.add_argument("--now", help="测试用当前时间，ISO 8601")
    parser.add_argument("--ensure-monitor", action="store_true", help="交易时段监控未运行时尝试拉起现有守护器")
    parser.add_argument("--force", action="store_true", help="测试用：跳过交易时段和日历限制")
    args = parser.parse_args()
    now = parse_datetime(args.now) if args.now else datetime.now(TZ)
    if now is None:
        raise SystemExit("--now 必须是 ISO 8601 时间")
    now = now.astimezone(TZ)

    mode = "active" if args.force else market_mode(args.calendar, now)
    if mode == "inactive":
        result = {"state": "无需运行", "changed": False, "detail": "当前不是已验证交易时段"}
        write_json(args.status_output, status_payload(now, result))
        print(json.dumps(result, ensure_ascii=False))
        return 0

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"state": "已有接线任务运行", "changed": False}, ensure_ascii=False))
            return 0
        if PUBLISH_LOCK_PATH.exists():
            result = {"state": "等待发布任务完成", "changed": False, "detail": "避免数据审计期间切换异动快照"}
            write_json(args.status_output, status_payload(now, result))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        try:
            ACTIVE_DIR.mkdir()
        except FileExistsError:
            print(json.dumps({"state": "已有接线任务运行", "changed": False}, ensure_ascii=False))
            return 0
        try:
            result = finalize_session(args, now) if mode == "closed" else run_bridge(args, now)
        finally:
            try:
                ACTIVE_DIR.rmdir()
            except OSError:
                pass
    print(json.dumps(result, ensure_ascii=False))
    return 0


def run_bridge(args: argparse.Namespace, now: datetime) -> dict[str, Any]:
    health = monitor_health(args.monitor_status, args.monitor_log, now)
    recovery_attempted = False
    if not health["healthy"] and args.ensure_monitor:
        recovery_attempted = start_monitor(args.monitor_start)
        if recovery_attempted:
            time.sleep(2)
            health = monitor_health(args.monitor_status, args.monitor_log, now)

    previous = read_json(args.output)
    if not health["healthy"]:
        payload = unavailable_payload(now, health["reason"], previous)
        changed = write_if_changed(args.output, payload, previous)
        if changed:
            PENDING_PATH.touch()
        result = {
            "state": "监控待恢复",
            "changed": changed,
            "alert_count": 0,
            "detail": health["reason"],
            "recovery_attempted": recovery_attempted,
        }
        write_json(args.status_output, status_payload(now, result, health))
        return result

    records = read_signal_records(args.signals, now)
    alerts = [converted for record in records if (converted := convert_record(record))]
    alerts = dedupe_alerts(alerts)[-MAX_ALERTS:]
    alerts = preserve_quote_verifications(alerts, previous)
    payload = live_payload(alerts, now)

    if not should_refresh(previous, payload, now):
        result = {
            "state": "监控正常" if alerts else "监控正常，暂无触发",
            "changed": False,
            "alert_count": len(alerts),
            "detail": "监控信号与页面数据一致",
            "recovery_attempted": recovery_attempted,
        }
        write_json(args.status_output, status_payload(now, result, health))
        return result

    changed = write_if_changed(args.output, payload, previous)
    if changed:
        PENDING_PATH.touch()
    result = {
        "state": "已接入盘中异动" if alerts else "监控正常，暂无触发",
        "changed": changed,
        "alert_count": len(alerts),
        "detail": "短周期信号已转换为V1异动卡" if alerts else "监控有有效行情，但当前没有达到规则门槛的异动",
        "recovery_attempted": recovery_attempted,
    }
    write_json(args.status_output, status_payload(now, result, health))
    return result


def should_run(calendar_path: Path, now: datetime) -> bool:
    return market_mode(calendar_path, now) == "active"


def market_mode(calendar_path: Path, now: datetime) -> str:
    calendar = read_json(calendar_path)
    if calendar.get("verification_state") != "verified":
        return "inactive"
    day = now.date().isoformat()
    if not (str(calendar.get("valid_from") or "") <= day <= str(calendar.get("valid_to") or "")):
        return "inactive"
    weekends = set(calendar.get("weekend_days") or [5, 6])
    if now.weekday() in weekends:
        trading_day = day in set(calendar.get("extra_open_days") or [])
    else:
        trading_day = day not in set(calendar.get("holidays") or [])
    if not trading_day:
        return "inactive"
    hhmm = now.hour * 100 + now.minute
    if 925 <= hhmm <= 1135 or 1255 <= hhmm <= 1501:
        return "active"
    if hhmm >= 1505:
        return "closed"
    return "inactive"


def finalize_session(args: argparse.Namespace, now: datetime) -> dict[str, Any]:
    previous = read_json(args.output)
    previous_time = parse_datetime(previous.get("timestamp"))
    if previous_time and previous_time.astimezone(TZ).date() == now.date() and previous.get("source_status") != "invalidated":
        alerts = [item for item in previous.get("alerts") or [] if isinstance(item, dict)]
        payload = dict(previous)
    else:
        records = read_signal_records(args.signals, now)
        alerts = dedupe_alerts([converted for record in records if (converted := convert_record(record))])[-MAX_ALERTS:]
        payload = live_payload(alerts, now)
    payload["timestamp"] = now.replace(microsecond=0).isoformat()
    payload["source_status"] = "monitor_session_closed"
    payload["alerts"] = alerts
    payload["note"] = (
        f"盘中监控已按计划结束，今日保留{len(alerts)}条短周期触发供收盘复盘；已过交易时效，不作为当前触发。"
        if alerts
        else "盘中监控已按计划结束，今日没有达到短周期价格、成交和扩散规则门槛的有效异动。"
    )
    changed = should_refresh(previous, payload, now) and write_if_changed(args.output, payload, previous)
    if changed:
        PENDING_PATH.touch()
    result = {
        "state": "今日监控已收盘",
        "changed": changed,
        "alert_count": len(alerts),
        "detail": payload["note"],
    }
    write_json(args.status_output, status_payload(now, result))
    return result


def monitor_health(status_path: Path, log_path: Path, now: datetime) -> dict[str, Any]:
    status = read_json(status_path)
    updated = parse_datetime(status.get("updated_at"))
    age = (now - updated.astimezone(TZ)).total_seconds() if updated else None
    pid = as_int(status.get("child_pid"))
    running = status.get("state") == "running" and pid is not None and process_exists(pid)
    recent = age is not None and -120 <= age <= MONITOR_STALE_SECONDS
    log_state = recent_log_state(log_path, now)
    healthy = running and recent and log_state == "valid"
    if not running:
        reason = "盘中监控进程未运行，等待自动拉起。"
    elif not recent:
        reason = "盘中监控心跳超时，等待自动恢复。"
    elif log_state == "error":
        reason = "行情源最近一次刷新失败，程序会在网络恢复后自动重试。"
    elif log_state == "stale":
        reason = "盘中监控尚未产出近期有效行情，等待下一轮。"
    else:
        reason = "盘中监控运行正常。"
    return {
        "healthy": healthy,
        "reason": reason,
        "monitor_state": status.get("state") or "unknown",
        "child_pid": pid,
        "heartbeat_at": updated.astimezone(TZ).isoformat(timespec="seconds") if updated else None,
        "log_state": log_state,
    }


def recent_log_state(path: Path, now: datetime) -> str:
    try:
        stat = path.stat()
        age = now.timestamp() - stat.st_mtime
        with path.open("rb") as handle:
            handle.seek(max(0, stat.st_size - 2 * 1024 * 1024))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return "stale"
    if age > MONITOR_STALE_SECONDS:
        return "stale"
    valid_pos = text.rfind(VALID_MARKER)
    error_pos = text.rfind(ERROR_MARKER)
    if valid_pos >= 0 and valid_pos > error_pos:
        return "valid"
    return "error" if error_pos >= 0 else "stale"


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def start_monitor(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        completed = subprocess.run([str(path)], cwd=path.parent, capture_output=True, text=True, timeout=20, check=False)
    except Exception:
        return False
    return completed.returncode == 0


def read_signal_records(path: Path, now: datetime) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines[-3000:]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict) or value.get("kind") == "system":
            continue
        timestamp = parse_datetime(value.get("timestamp"))
        if timestamp is None or timestamp.astimezone(TZ).date() != now.date():
            continue
        if timestamp.astimezone(TZ) > now + timedelta(minutes=2):
            continue
        records.append(value)
    records.sort(key=lambda item: str(item.get("timestamp") or ""))
    return records


def convert_record(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    kind = str(record.get("kind") or "")
    if kind not in {"small_deng", "small_deng_down", "old_deng", "old_deng_down", "style_move", "volume_watch"}:
        return None
    timestamp = parse_datetime(record.get("timestamp"))
    if timestamp is None:
        return None
    timestamp = timestamp.astimezone(TZ)
    details = record.get("details") if isinstance(record.get("details"), dict) else {}
    side = str(record.get("side") or details.get("side") or ("down" if kind.endswith("down") else "up"))
    sector = sector_name(record, details)
    leaders = representative_leaders(kind, details, side)
    if not sector or not leaders:
        return None
    alert_class, signal_type, confirmation = classify_record(kind, details, side)
    board = board_metrics(kind, details, side)
    rules = details.get("trigger_rules") if isinstance(details.get("trigger_rules"), list) else []
    reason = normalize_reason(record.get("body") or record.get("title") or "")
    audit = item_quote_audit(timestamp, leaders, board, alert_class)
    key = str(record.get("key") or f"{kind}:{sector}:{side}")
    digest = hashlib.sha1(f"{key}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()[:12]
    alert: dict[str, Any] = {
        "id": f"monitor-{timestamp:%Y%m%d-%H%M%S}-{digest}",
        "time": timestamp.replace(microsecond=0).isoformat(),
        "sector": sector,
        "type": display_type(kind, record, side),
        "reason": reason,
        "leaders": leaders,
        "signal_type": signal_type,
        "is_old_economy": kind.startswith("old_deng"),
        "source_watch_id": sector,
        "quote_audit": audit,
        "source_status": "degraded_partial" if confirmation == "candidate" else "monitor_live_unverified",
        "valid_until": (timestamp + timedelta(minutes=5)).replace(microsecond=0).isoformat(),
        "trigger_rule": "；".join(str(item) for item in rules if item),
    }
    if alert_class:
        alert["alert_class"] = alert_class
    if confirmation:
        alert["confirmation_level"] = confirmation
    if kind.startswith("small_deng"):
        theme = details.get("theme") if isinstance(details.get("theme"), dict) else {}
        alert["limit_up_count"] = limit_count(theme, up=True)
        alert["limit_down_count"] = limit_count(theme, up=False)
        sanity = alert.setdefault("quote_audit", {}).setdefault("sanity_checks", {})
        if alert["limit_up_count"] >= 2:
            sanity["limit_up_count_valid"] = True
        if alert["limit_down_count"] >= 2:
            sanity["limit_down_count_valid"] = True
    return alert


def sector_name(record: dict[str, Any], details: dict[str, Any]) -> str:
    if record.get("theme"):
        return str(record["theme"])
    if details.get("style"):
        return str(details["style"])
    theme = details.get("theme")
    if isinstance(theme, dict) and theme.get("name"):
        return str(theme["name"])
    volume = details.get("volume")
    if isinstance(volume, dict) and volume.get("name"):
        return str(volume["name"])
    directions = details.get("directions")
    if isinstance(directions, list) and directions:
        return "传统权重风格"
    return ""


def representative_leaders(kind: str, details: dict[str, Any], side: str) -> list[dict[str, Any]]:
    rows: list[Any] = []
    if kind.startswith("small_deng"):
        theme = details.get("theme") if isinstance(details.get("theme"), dict) else {}
        rows = theme.get("laggards" if side == "down" else "leaders") or []
    elif kind.startswith("old_deng"):
        directions = details.get("directions") if isinstance(details.get("directions"), list) else []
        ordered = sorted(directions, key=lambda item: as_float(item.get("speed_pct")) or 0, reverse=side != "down")
        for direction in ordered[:3]:
            rows.extend(direction.get("bottom_stocks" if side == "down" else "top_stocks") or [])
    elif kind == "style_move":
        themes = details.get("themes") if isinstance(details.get("themes"), list) else []
        for theme in themes[:3]:
            rows.extend(theme.get("laggards" if side == "down" else "leaders") or [])
    elif kind == "volume_watch":
        volume = details.get("volume") if isinstance(details.get("volume"), dict) else {}
        rows = volume.get("top_stocks") or []

    leaders: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else row
        tick = metrics.get("tick") if isinstance(metrics.get("tick"), dict) else {}
        name = str(tick.get("name") or "").strip()
        if not name or name in seen:
            continue
        speed = as_float(metrics.get("speed_pct"))
        amount_ratio = as_float(metrics.get("amount_ratio"))
        day_change = as_float(tick.get("change_pct"))
        score = as_float(row.get("score"))
        factors = []
        if speed is not None:
            factors.append(f"3分钟{speed:+.2f}%")
        if amount_ratio is not None:
            factors.append(f"成交放大{amount_ratio:.2f}x")
        if day_change is not None:
            factors.append(f"日内{day_change:+.2f}%")
        leaders.append({
            "name": name,
            "code": str(tick.get("symbol") or ""),
            "change_pct": round(speed or 0.0, 4),
            "quote_time": tick.get("timestamp"),
            "score": round(score, 2) if score is not None else None,
            "factors": factors,
        })
        seen.add(name)
        if len(leaders) >= 3:
            break
    return leaders


def classify_record(kind: str, details: dict[str, Any], side: str) -> tuple[str, str, str]:
    if kind in {"old_deng", "old_deng_down", "style_move"}:
        return "style", "风格观察", "candidate"
    if kind == "small_deng_down":
        return "risk", "风险提示", "candidate"
    if kind == "small_deng":
        theme = details.get("theme") if isinstance(details.get("theme"), dict) else {}
        hard = details.get("move_context") == "attack" or limit_count(theme, up=True) >= 2 or theme_threshold(theme, "up")
        return ("opportunity", "机会观察", "candidate") if hard else ("", "题材观察", "")
    return "", "放量观察", ""


def board_metrics(kind: str, details: dict[str, Any], side: str) -> dict[str, Any]:
    if kind.startswith("small_deng"):
        theme = details.get("theme") if isinstance(details.get("theme"), dict) else {}
        return {
            "move": as_float(theme.get("speed_pct")),
            "volume": as_float(theme.get("amount_ratio")),
            "direction_ratio": as_float(theme.get("falling_ratio" if side == "down" else "rising_ratio")),
            "relative_volume": as_float(theme.get("amount_vs_prev_day_ratio")),
        }
    if kind.startswith("old_deng"):
        directions = details.get("directions") if isinstance(details.get("directions"), list) else []
        return {
            "move": as_float(details.get("weighted_speed_pct")),
            "volume": max([as_float(item.get("amount_ratio")) or 0 for item in directions] or [0]),
            "direction_ratio": max([as_float(item.get("falling_ratio" if side == "down" else "rising_ratio")) or 0 for item in directions] or [0]),
            "relative_volume": None,
        }
    if kind == "style_move":
        themes = details.get("themes") if isinstance(details.get("themes"), list) else []
        return {
            "move": max(([as_float(item.get("speed_pct")) or 0 for item in themes]), key=abs, default=0),
            "volume": max([as_float(item.get("amount_ratio")) or 0 for item in themes] or [0]),
            "direction_ratio": max([as_float(item.get("falling_ratio" if side == "down" else "rising_ratio")) or 0 for item in themes] or [0]),
            "relative_volume": None,
        }
    volume = details.get("volume") if isinstance(details.get("volume"), dict) else {}
    return {
        "move": None,
        "volume": as_float(volume.get("amount_vs_prev_day_ratio")),
        "direction_ratio": max(as_float(volume.get("rising_ratio")) or 0, as_float(volume.get("falling_ratio")) or 0),
        "relative_volume": as_float(volume.get("amount_vs_prev_day_ratio")),
    }


def item_quote_audit(timestamp: datetime, leaders: list[dict[str, Any]], board: dict[str, Any], alert_class: str) -> dict[str, Any]:
    move = board.get("move")
    volume = board.get("volume")
    direction_ratio = board.get("direction_ratio")
    price_valid = move is not None and (abs(move) >= 1.0 if alert_class in {"opportunity", "risk"} else True)
    volume_valid = volume is not None and volume >= 5
    direction_valid = direction_ratio is not None and direction_ratio >= 0.6
    max_move = max([abs(as_float(item.get("change_pct")) or 0) for item in leaders] or [0])
    return {
        "provider": "本地盘中监控",
        "quote_time": timestamp.replace(microsecond=0).isoformat(),
        "pct_field": "3分钟涨跌幅",
        "sample_count": len(leaders),
        "max_abs_leader_change_pct": round(max_move, 4),
        "sanity_checks": {
            "cross_source_verified": False,
            "price_move_valid": price_valid,
            "volume_valid": volume_valid,
            "direction_ratio_valid": direction_valid,
            "limit_down_count_valid": False,
        },
        "board_3m_change_pct": round(move, 4) if move is not None else None,
        "direction_ratio": round(direction_ratio, 4) if direction_ratio is not None else None,
        "volume_ratio": round(volume, 4) if volume is not None else None,
        "relative_volume_vs_yesterday": round(board["relative_volume"], 4) if board.get("relative_volume") is not None else None,
        "missing_confirmation": "等待富途行情按触发时点交叉核验；通过前只作候选或观察，不作为确认交易信号。",
    }


def preserve_quote_verifications(
    alerts: list[dict[str, Any]],
    previous_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    previous_by_id = {
        str(item.get("id") or ""): item
        for item in previous_payload.get("alerts") or []
        if isinstance(item, dict) and item.get("id")
    }
    for alert in alerts:
        previous = previous_by_id.get(str(alert.get("id") or ""))
        if not isinstance(previous, dict):
            continue
        old_audit = previous.get("quote_audit") if isinstance(previous.get("quote_audit"), dict) else {}
        verification = old_audit.get("secondary_verification")
        if not isinstance(verification, dict) or not verification.get("state"):
            continue
        alert["quote_audit"] = copy.deepcopy(old_audit)
        if isinstance(previous.get("reason"), str):
            alert["reason"] = previous["reason"]
    return alerts


def live_payload(alerts: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    if not alerts:
        return {
            "timestamp": now.replace(microsecond=0).isoformat(),
            "source_status": "monitor_live_no_trigger",
            "alerts": [],
            "note": "盘中监控运行正常，当前没有达到短周期价格、成交和扩散规则门槛的新异动。",
        }
    verifications = [
        ((item.get("quote_audit") or {}).get("sanity_checks") or {}).get("cross_source_verified") is True
        for item in alerts
    ]
    uses_futu = any(
        ((item.get("quote_audit") or {}).get("secondary_verification") or {}).get("source") == "富途行情"
        for item in alerts
    )
    max_move = max([abs(as_float(leader.get("change_pct")) or 0) for item in alerts for leader in item.get("leaders") or []] or [0])
    return {
        "timestamp": now.replace(microsecond=0).isoformat(),
        "source_status": "monitor_live",
        "alerts": alerts,
        "quote_audit": {
            "provider": "本地盘中监控、富途行情（腾讯备用）" if uses_futu else "本地盘中监控",
            "quote_time": max(str(item.get("time") or "") for item in alerts),
            "pct_field": "各异动卡标注的3分钟涨跌幅",
            "sanity_checks": {
                "sample_count": len(alerts),
                "max_abs_leader_change_pct": round(max_move, 4),
                "cross_source_verified": bool(verifications) and all(verifications),
                "verified_alert_count": sum(verifications),
            },
        },
        "note": "异动来自本地短周期监控；候选卡须经富途行情按触发时点复核后才能升级。",
    }


def unavailable_payload(now: datetime, reason: str, previous: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    previous = previous if isinstance(previous, dict) else {}
    previous_time = parse_datetime(previous.get("timestamp"))
    previous_alerts = [item for item in previous.get("alerts") or [] if isinstance(item, dict)]
    same_trade_date = bool(previous_time and previous_time.astimezone(TZ).date() == now.date())
    can_preserve = (
        same_trade_date
        and bool(previous_alerts)
        and previous.get("source_status") != "invalidated"
    )
    if can_preserve:
        payload = copy.deepcopy(previous)
        payload["source_status"] = "monitor_waiting_update"
        payload["monitor_checked_at"] = now.replace(microsecond=0).isoformat()
        payload["note"] = (
            "行情暂时中断，已保留今天最近一次有效异动；卡片仍显示实际触发时间，"
            "恢复后会自动更新。"
        )
        return payload
    return {
        "timestamp": now.replace(microsecond=0).isoformat(),
        "source_status": "invalidated",
        "alerts": [],
        "note": reason,
    }


def should_refresh(previous: dict[str, Any], current: dict[str, Any], now: datetime) -> bool:
    if previous.get("source_status") != current.get("source_status"):
        return True
    previous_ids = [item.get("id") for item in previous.get("alerts") or [] if isinstance(item, dict)]
    current_ids = [item.get("id") for item in current.get("alerts") or [] if isinstance(item, dict)]
    if previous_ids != current_ids:
        return True
    if current.get("source_status") == "monitor_session_closed":
        return False
    if current.get("source_status") == "monitor_waiting_update":
        checked_at = parse_datetime(previous.get("monitor_checked_at"))
        return checked_at is None or now - checked_at.astimezone(TZ) >= timedelta(minutes=HEARTBEAT_MINUTES)
    timestamp = parse_datetime(previous.get("timestamp"))
    return timestamp is None or now - timestamp.astimezone(TZ) >= timedelta(minutes=HEARTBEAT_MINUTES)


def dedupe_alerts(alerts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for alert in alerts:
        by_id[str(alert.get("id") or "")] = alert
    return sorted(by_id.values(), key=lambda item: str(item.get("time") or ""))


def display_type(kind: str, record: dict[str, Any], side: str) -> str:
    if kind == "small_deng":
        return "小登题材短周期拉动"
    if kind == "small_deng_down":
        return "小登题材快速回落"
    if kind.startswith("old_deng"):
        return "老登权重风格拉动" if side == "up" else "老登权重风格回落"
    if kind == "style_move":
        return "风格共振回暖" if side == "up" else "风格共振转弱"
    if kind == "volume_watch":
        return "板块成交明显放大"
    return str(record.get("title") or "盘中异动")


def normalize_reason(value: Any) -> str:
    return str(value or "").replace("\r", "").strip()


def limit_count(theme: dict[str, Any], up: bool) -> int:
    rows = theme.get("leaders" if up else "laggards") if isinstance(theme, dict) else []
    count = 0
    for row in rows or []:
        metrics = row.get("metrics") if isinstance(row, dict) and isinstance(row.get("metrics"), dict) else {}
        tick = metrics.get("tick") if isinstance(metrics.get("tick"), dict) else {}
        day_change = as_float(tick.get("change_pct"))
        if day_change is not None and (day_change >= 9.5 if up else day_change <= -9.5):
            count += 1
    return count


def theme_threshold(theme: dict[str, Any], side: str) -> bool:
    move = as_float(theme.get("speed_pct")) or 0
    volume = as_float(theme.get("amount_ratio")) or 0
    ratio = as_float(theme.get("falling_ratio" if side == "down" else "rising_ratio")) or 0
    return (move <= -1 and ratio >= 0.6 and volume >= 5) if side == "down" else (move >= 1 and ratio >= 0.6 and volume >= 5)


def status_payload(now: datetime, result: dict[str, Any], health: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    payload = {
        "checked_at": now.replace(microsecond=0).isoformat(),
        **result,
        "policy": "只转译监控当时已产生的结构化信号；不补造错过时点，不把盘中全景冒充短周期异动。",
    }
    if health:
        payload["monitor"] = health
    return payload


def write_if_changed(path: Path, payload: dict[str, Any], previous: dict[str, Any]) -> bool:
    if canonical_json(previous) == canonical_json(payload):
        return False
    write_json(path, payload)
    return True


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_datetime(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)


def as_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())

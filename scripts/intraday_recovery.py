#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent.parent
INTRADAY_PATH = ROOT / "data" / "intraday.json"
STATUS_PATH = ROOT / "logs" / "intraday-recovery-status.json"
STALE_AFTER = timedelta(minutes=20)


@dataclass(frozen=True)
class FreshnessDecision:
    active: bool
    fresh: bool
    phase: str
    reason: str
    quote_time: Optional[datetime]


def parse_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y%m%d%H%M%S", "%Y%m%d%H%M"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=TZ)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)


def latest_index_quote(payload: Dict[str, Any]) -> Optional[datetime]:
    rows = payload.get("indices") or payload.get("index", {}).get("a_share_indices") or []
    values = [parse_datetime(item.get("quote_time")) for item in rows if isinstance(item, dict)]
    valid = [value for value in values if value is not None]
    return max(valid) if valid else parse_datetime(payload.get("market_data_as_of"))


def is_trading_day(root: Path, now: datetime) -> bool:
    calendar = read_json(root / "config" / "cn-market-calendar.json")
    if calendar.get("verification_state") != "verified":
        return False
    day = now.date().isoformat()
    if not (str(calendar.get("valid_from") or "") <= day <= str(calendar.get("valid_to") or "")):
        return False
    if now.weekday() in set(calendar.get("weekend_days") or [5, 6]):
        return day in set(calendar.get("extra_open_days") or [])
    return day not in set(calendar.get("holidays") or [])


def market_phase(now: datetime, trading_day: bool = True) -> str:
    if not trading_day:
        return "休市"
    current = now.time()
    if time(9, 25) <= current < time(11, 30):
        return "上午交易"
    if time(11, 30) <= current < time(13, 0):
        return "午间补偿"
    if time(13, 0) <= current < time(15, 0):
        return "下午交易"
    if time(15, 0) <= current <= time(16, 30):
        return "收盘补偿"
    return "非运行窗口"


def assess_freshness(payload: Dict[str, Any], now: datetime, trading_day: bool = True) -> FreshnessDecision:
    now = now.astimezone(TZ)
    phase = market_phase(now, trading_day)
    quote_time = latest_index_quote(payload)
    if phase in {"休市", "非运行窗口"}:
        return FreshnessDecision(False, True, phase, "当前无需盘中行情更新", quote_time)
    if quote_time is None:
        return FreshnessDecision(True, False, phase, "缺少可验证的指数行情时间", None)
    if quote_time.date() != now.date():
        return FreshnessDecision(True, False, phase, "尚无当日可验证行情", quote_time)

    if phase == "午间补偿":
        fresh = quote_time.time() >= time(11, 25)
        reason = "午间最新行情已保存" if fresh else "上午收盘行情未补齐"
    elif phase == "收盘补偿":
        fresh = quote_time.time() >= time(14, 55)
        reason = "收盘行情已保存" if fresh else "收盘行情未补齐"
    elif phase == "下午交易" and now.time() < time(13, 5):
        fresh = quote_time.time() >= time(11, 25)
        reason = "午后开盘容忍窗口内" if fresh else "午前行情未补齐"
    else:
        age = now - quote_time
        fresh = timedelta(0) <= age <= STALE_AFTER
        reason = "盘中行情在允许时差内" if fresh else f"盘中行情已超时{max(0, int(age.total_seconds() // 60))}分钟"
    return FreshnessDecision(True, fresh, phase, reason, quote_time)


def read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def retry_delay_seconds(failure_count: int) -> int:
    return (60, 120, 300, 600)[min(max(failure_count - 1, 0), 3)]


def run_command(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def status_payload(
    now: datetime,
    state: str,
    decision: FreshnessDecision,
    failure_count: int = 0,
    detail: str = "",
    next_retry_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    return {
        "checked_at": now.isoformat(timespec="seconds"),
        "state": state,
        "phase": decision.phase,
        "detail": detail or decision.reason,
        "quote_time": decision.quote_time.isoformat(timespec="seconds") if decision.quote_time else None,
        "failure_count": failure_count,
        "next_retry_at": next_retry_at.isoformat(timespec="seconds") if next_retry_at else None,
        "historical_gap_policy": "只补网络恢复后可核验的最新行情，不伪造已经错过的盘中时点",
    }


def recover(root: Path, now: datetime, publish: bool = True) -> Dict[str, Any]:
    intraday_path = root / "data" / "intraday.json"
    status_path = root / "logs" / "intraday-recovery-status.json"
    current = read_json(intraday_path)
    trading_day = is_trading_day(root, now)
    decision = assess_freshness(current, now, trading_day)
    previous = read_json(status_path)

    if not decision.active:
        result = status_payload(now, "无需运行", decision)
        write_json(status_path, result)
        return result
    if decision.fresh:
        if publish and previous.get("state") == "行情已恢复，等待发布":
            publish_result = run_command([str(root / "scripts" / "publish_dashboard.sh")], root)
            if publish_result.returncode != 0:
                failures = int(previous.get("failure_count") or 0) + 1
                retry_at = now + timedelta(seconds=retry_delay_seconds(failures))
                detail = (publish_result.stderr or publish_result.stdout or "发布失败").strip()
                result = status_payload(now, "行情已恢复，等待发布", decision, failures, detail, retry_at)
                write_json(status_path, result)
                return result
            result = status_payload(now, "已自动补充最新行情", decision, detail="最新行情已补充并发布")
            write_json(status_path, result)
            return result
        result = status_payload(now, "数据正常", decision)
        write_json(status_path, result)
        return result

    next_retry = parse_datetime(previous.get("next_retry_at"))
    if next_retry and now < next_retry:
        result = status_payload(
            now,
            "等待重试",
            decision,
            int(previous.get("failure_count") or 0),
            str(previous.get("detail") or decision.reason),
            next_retry,
        )
        write_json(status_path, result)
        return result

    update_result = run_command(
        [str(root / "scripts" / "update_intraday_market.py"), "--path", str(intraday_path)],
        root,
    )
    refreshed = read_json(intraday_path)
    refreshed_decision = assess_freshness(refreshed, now, trading_day)
    if update_result.returncode != 0 or not refreshed_decision.fresh:
        failures = int(previous.get("failure_count") or 0) + 1
        retry_at = now + timedelta(seconds=retry_delay_seconds(failures))
        detail = (update_result.stderr or update_result.stdout or refreshed_decision.reason).strip()
        if update_result.returncode == 0 and not refreshed_decision.fresh:
            detail = f"行情源已响应，但{refreshed_decision.reason}"
        result = status_payload(now, "网络或行情源待恢复", refreshed_decision, failures, detail, retry_at)
        write_json(status_path, result)
        return result

    if publish:
        publish_result = run_command([str(root / "scripts" / "publish_dashboard.sh")], root)
        if publish_result.returncode != 0:
            failures = int(previous.get("failure_count") or 0) + 1
            retry_at = now + timedelta(seconds=retry_delay_seconds(failures))
            detail = (publish_result.stderr or publish_result.stdout or "发布失败").strip()
            result = status_payload(now, "行情已恢复，等待发布", refreshed_decision, failures, detail, retry_at)
            write_json(status_path, result)
            return result

    result = status_payload(now, "已自动补充最新行情", refreshed_decision, detail="网络恢复后已补充可核验的最新行情")
    write_json(status_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="V1盘中行情超时检测与网络恢复补跑")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--now", help="测试用检查时间，ISO 8601")
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--trading-day-check", action="store_true", help="仅检查当日是否为已验证交易日")
    args = parser.parse_args()
    now = parse_datetime(args.now) if args.now else datetime.now(TZ)
    if now is None:
        raise SystemExit("--now 必须是有效ISO时间")
    if args.trading_day_check:
        open_today = is_trading_day(args.root.resolve(), now)
        print(json.dumps({"trading_day": open_today, "date": now.date().isoformat()}, ensure_ascii=False))
        return 0 if open_today else 3
    result = recover(args.root.resolve(), now, publish=not args.no_publish)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["state"] not in {"网络或行情源待恢复", "行情已恢复，等待发布"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

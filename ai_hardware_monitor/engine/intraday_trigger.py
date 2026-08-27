from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from v2_platform.learning import TradingCalendar

from .collector import CHINA_TZ, LiveSnapshotCollector
from .io import load_json, write_json_atomic
from .notifier import DesktopNotifier
from .score import evaluate_snapshot


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":", 1))
    return hour * 60 + minute


def active_window(now: datetime, config: dict[str, Any]) -> dict[str, Any] | None:
    current = now.hour * 60 + now.minute
    for item in config.get("windows", []) if isinstance(config.get("windows"), list) else []:
        if _minutes(str(item.get("start"))) <= current <= _minutes(str(item.get("end"))):
            return dict(item)
    return None


def evaluate_intraday_trigger(
    snapshot: dict[str, Any],
    evaluation: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    thresholds = config.get("conditions") if isinstance(config.get("conditions"), dict) else {}
    sector = snapshot.get("sector") if isinstance(snapshot.get("sector"), dict) else {}
    leaders = snapshot.get("leaders") if isinstance(snapshot.get("leaders"), dict) else {}
    checks = [
        ("score", "综合评分达到60", _number(evaluation.get("score")), float(thresholds.get("minimum_score") or 60), "minimum"),
        ("coverage", "证据覆盖率达到65%", _number(evaluation.get("coverage_ratio")), float(thresholds.get("minimum_coverage_ratio") or 0.65), "minimum"),
        ("sector_rank", "代理篮子进入可比行业前三", _number(sector.get("market_rank")), float(thresholds.get("maximum_sector_rank") or 3), "maximum"),
        ("relative_strength", "相对沪深300超额达到1%", _number(sector.get("relative_outperformance_pct")), float(thresholds.get("minimum_relative_outperformance_pct") or 1), "minimum"),
        ("breadth", "股票池上涨宽度达到70%", _number(sector.get("advance_ratio_pct")), float(thresholds.get("minimum_advance_ratio_pct") or 70), "minimum"),
        ("leader", "至少一只核心龙头领先", _number(leaders.get("outperform_count")), float(thresholds.get("minimum_leading_core_count") or 1), "minimum"),
        ("turnover", "龙头成交速度达到1.2倍", _number(leaders.get("median_turnover_pace")), float(thresholds.get("minimum_leader_turnover_pace") or 1.2), "minimum"),
    ]
    conditions = []
    for condition_id, label, actual, threshold, direction in checks:
        passed = actual is not None and (actual >= threshold if direction == "minimum" else actual <= threshold)
        conditions.append({
            "id": condition_id,
            "label": label,
            "actual": round(actual, 4) if actual is not None else None,
            "threshold": threshold,
            "passed": passed,
        })

    trade_date = str(snapshot.get("trade_date") or "")
    stocks = snapshot.get("stocks") if isinstance(snapshot.get("stocks"), list) else []
    valid_stocks = []
    for item in stocks:
        if not isinstance(item, dict) or not item.get("name") or not item.get("quote_as_of"):
            continue
        if str(item.get("quote_as_of")).startswith(trade_date):
            valid_stocks.append(item)
    valid_stocks.sort(key=lambda item: float(item.get("change_pct") or -999), reverse=True)
    representative = valid_stocks[0] if valid_stocks else None
    quote_check = {
        "id": "representative_quote",
        "label": "至少一只代表股具有当日实时报价",
        "actual": representative.get("name") if representative else None,
        "threshold": "当日实时报价",
        "passed": representative is not None,
    }
    conditions.append(quote_check)
    active = all(bool(item["passed"]) for item in conditions)
    confirmed = active and (evaluation.get("state") or {}).get("code") == "launch"
    return {
        "active": active,
        "level": "confirmed" if confirmed else "candidate" if active else "waiting",
        "label": "🟢启动确认" if confirmed else "🟠盘中候选" if active else "⚪未触发",
        "conditions": conditions,
        "failed_conditions": [item["label"] for item in conditions if not item["passed"]],
        "representative_stock": representative,
    }


class IntradayTriggerRunner:
    def __init__(self, root: Path, *, notifier: DesktopNotifier | None = None) -> None:
        self.root = root.resolve()
        self.module_root = self.root / "ai_hardware_monitor"
        self.config_dir = self.module_root / "config"
        self.data_dir = self.module_root / "data"
        self.notifier = notifier or DesktopNotifier()

    def run(
        self,
        *,
        now: datetime | None = None,
        snapshot: dict[str, Any] | None = None,
        evaluation: dict[str, Any] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        now = (now or datetime.now(timezone.utc)).astimezone(CHINA_TZ)
        config = load_json(self.config_dir / "intraday-trigger.json")
        if config.get("enabled") is not True:
            return {"state": "disabled", "reason": "盘中触发提醒未启用"}
        calendar = TradingCalendar(load_json(self.root / "config" / "v2-market-calendar.json"), "CN")
        if calendar.is_open(now.date()) is not True:
            return {"state": "waiting", "reason": "当前不是已验证A股交易日"}
        window = active_window(now, config)
        if not window and not force:
            return {"state": "waiting", "reason": "当前不在盘中触发巡检窗口"}

        runtime_path = self.data_dir / "intraday-trigger-runtime.json"
        runtime = load_json(runtime_path)
        last_poll = self._parse_time(runtime.get("last_polled_at"))
        poll_interval = int(config.get("poll_interval_seconds") or 180)
        if not force and last_poll and (now - last_poll).total_seconds() < poll_interval:
            return {"state": "throttled", "reason": "等待下一轮盘中巡检", "last_polled_at": runtime.get("last_polled_at")}

        if snapshot is None:
            snapshot = LiveSnapshotCollector(self.root).collect(now=now)
        if evaluation is None:
            evaluation = evaluate_snapshot(
                snapshot,
                load_json(self.config_dir / "weights.json"),
                load_json(self.config_dir / "rules.json"),
                now=now,
            )
        trigger = evaluate_intraday_trigger(snapshot, evaluation, config)
        previous_active = runtime.get("active") is True
        previous_level = str(runtime.get("level") or "waiting")
        last_notification = self._parse_time(runtime.get("last_notification_at"))
        cooldown = int(config.get("notification_cooldown_minutes") or 30)
        cooldown_ready = not last_notification or now - last_notification >= timedelta(minutes=cooldown)
        upgraded = trigger["level"] == "confirmed" and previous_level != "confirmed"
        should_notify = trigger["active"] and cooldown_ready and (not previous_active or upgraded)

        notification_result = {"state": "not_sent", "channel": "macos_notification_center"}
        alert = None
        if should_notify:
            alert = self._build_alert(snapshot, evaluation, trigger, now, window or {"id": "forced", "label": "强制验收"})
            notification = config.get("notification") if isinstance(config.get("notification"), dict) else {}
            if notification.get("desktop_enabled") is True:
                notification_result = self.notifier.send(
                    title=str(notification.get("title") or "AI硬件盘中触发提醒"),
                    message=alert["message"],
                    sound=str(notification.get("sound") or "default"),
                )
            alert["notification"] = notification_result
            self._append_signal(alert)

        status = {
            "schema_version": 1,
            "version": "1.0.0",
            "generated_at": now.isoformat(timespec="seconds"),
            "trade_date": snapshot.get("trade_date"),
            "as_of": snapshot.get("as_of"),
            "window": window or {"id": "forced", "label": "强制验收"},
            "trigger": trigger,
            "score": evaluation.get("score"),
            "coverage_ratio": evaluation.get("coverage_ratio"),
            "notification": notification_result,
            "next_poll_seconds": poll_interval,
            "guardrails": config.get("guardrails", {}),
            "disclaimer": "盘中候选提醒不等于买入指令，最终决策由用户作出。",
        }
        write_json_atomic(self.data_dir / "intraday-trigger-status.json", status)
        runtime.update({
            "schema_version": 1,
            "last_polled_at": now.isoformat(timespec="seconds"),
            "active": trigger["active"],
            "level": trigger["level"],
        })
        if should_notify:
            runtime["last_notification_at"] = now.isoformat(timespec="seconds")
            runtime["last_alert_id"] = alert.get("alert_id") if alert else None
        write_json_atomic(runtime_path, runtime)
        return {
            "state": "completed",
            "trigger": {key: trigger[key] for key in ("active", "level", "label", "failed_conditions")},
            "score": evaluation.get("score"),
            "coverage_ratio": evaluation.get("coverage_ratio"),
            "notification": notification_result,
        }

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value))
            return parsed if parsed.tzinfo else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _build_alert(
        snapshot: dict[str, Any],
        evaluation: dict[str, Any],
        trigger: dict[str, Any],
        now: datetime,
        window: dict[str, Any],
    ) -> dict[str, Any]:
        sector = snapshot.get("sector") if isinstance(snapshot.get("sector"), dict) else {}
        representative = trigger.get("representative_stock") if isinstance(trigger.get("representative_stock"), dict) else {}
        basis = {
            "trade_date": snapshot.get("trade_date"),
            "window": window.get("id"),
            "level": trigger.get("level"),
            "score": evaluation.get("score"),
            "representative": representative.get("code"),
            "minute": now.strftime("%H:%M"),
        }
        digest = hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        name = str(representative.get("name") or "代表股")
        change = _number(representative.get("change_pct"))
        change_copy = f"{change:+.2f}%" if change is not None else "行情已更新"
        rank = sector.get("market_rank")
        message = f"{trigger['label']}｜{evaluation.get('score')}分｜行业排名{rank or '--'}｜{name}{change_copy}。等待固定检查点确认。"
        return {
            "alert_id": f"aihw_intraday_{digest}",
            "emitted_at": now.isoformat(timespec="seconds"),
            "trade_date": snapshot.get("trade_date"),
            "as_of": snapshot.get("as_of"),
            "level": trigger.get("level"),
            "label": trigger.get("label"),
            "message": message,
            "score": evaluation.get("score"),
            "coverage_ratio": evaluation.get("coverage_ratio"),
            "representative_stock": representative,
            "conditions": trigger.get("conditions", []),
            "disclaimer": "仅为盘中研究候选提醒，不构成买卖指令。",
        }

    def _append_signal(self, alert: dict[str, Any]) -> None:
        path = self.data_dir / "intraday-trigger-signals.json"
        payload = load_json(path, {"schema_version": 1, "alerts": []})
        rows = payload.get("alerts") if isinstance(payload.get("alerts"), list) else []
        if not any(item.get("alert_id") == alert.get("alert_id") for item in rows if isinstance(item, dict)):
            rows.append(alert)
        payload.update({"schema_version": 1, "updated_at": alert.get("emitted_at"), "latest": alert, "alerts": rows[-100:]})
        write_json_atomic(path, payload)


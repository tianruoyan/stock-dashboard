from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from v2_platform.learning import TradingCalendar

from .alert import build_alert, should_emit
from .checkpoints import next_checkpoint, resolve_checkpoint
from .collector import CHINA_TZ, LiveSnapshotCollector
from .io import load_json, write_json_atomic
from .score import evaluate_snapshot


class MonitorRunner:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.module_root = self.root / "ai_hardware_monitor"
        self.config = self.module_root / "config"
        self.data = self.module_root / "data"

    def run(
        self,
        *,
        now: datetime | None = None,
        input_path: Path | None = None,
        force_checkpoint: bool = False,
        refresh_checkpoint: bool = False,
    ) -> dict[str, Any]:
        now = (now or datetime.now(timezone.utc)).astimezone(CHINA_TZ)
        calendar = TradingCalendar(load_json(self.root / "config" / "v2-market-calendar.json"), "CN")
        if calendar.is_open(now.date()) is not True:
            return {
                "state": "waiting",
                "reason": "当前日期不是已验证A股交易日",
                "observed_at": now.isoformat(timespec="seconds"),
            }
        checkpoints = load_json(self.config / "checkpoints.json")
        checkpoint = resolve_checkpoint(now, checkpoints, force=force_checkpoint)
        if not checkpoint:
            upcoming = next_checkpoint(now, checkpoints)
            return {
                "state": "waiting",
                "reason": "当前不在09:35、10:30或14:30检查窗口",
                "next_checkpoint": upcoming,
                "observed_at": now.isoformat(timespec="seconds"),
            }

        previous = load_json(self.data / "status.json")
        previous_checkpoint = previous.get("checkpoint") if isinstance(previous.get("checkpoint"), dict) else {}
        if (
            not refresh_checkpoint
            and previous.get("trade_date") == now.date().isoformat()
            and previous_checkpoint.get("id") == checkpoint.get("id")
        ):
            return {
                "state": "already_completed",
                "trade_date": previous.get("trade_date"),
                "checkpoint": checkpoint,
                "score": previous.get("score"),
                "status": previous.get("state"),
            }

        if input_path:
            snapshot = load_json(input_path)
            if not isinstance(snapshot, dict) or not snapshot:
                raise ValueError("input_snapshot_missing_or_invalid")
        else:
            snapshot = LiveSnapshotCollector(self.root).collect(now=now)
        snapshot["checkpoint_id"] = checkpoint.get("id")
        write_json_atomic(self.data / "input-snapshot.json", snapshot)

        result = evaluate_snapshot(
            snapshot,
            load_json(self.config / "weights.json"),
            load_json(self.config / "rules.json"),
            now=now,
        )
        next_item = next_checkpoint(now, checkpoints)
        payload_basis = {
            "trade_date": snapshot.get("trade_date"),
            "as_of": snapshot.get("as_of"),
            "checkpoint": checkpoint.get("id"),
            "score": result.get("score"),
            "state": result.get("state"),
        }
        run_id = hashlib.sha256(json.dumps(payload_basis, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:20]
        status = {
            "schema_version": 1,
            "model": "AI硬件二次启动雷达",
            "model_version": "1.0.0",
            "mode": "research_observation_only",
            "run_id": f"aihw_run_{run_id}",
            "generated_at": now.isoformat(timespec="seconds"),
            "trade_date": snapshot.get("trade_date"),
            "as_of": snapshot.get("as_of"),
            "checkpoint": checkpoint,
            "next_checkpoint": next_item,
            "proxy_notice": "AI硬件强度使用8股等权代理篮子，不是官方板块指数。",
            **result,
            "sector": snapshot.get("sector", {}),
            "leaders": snapshot.get("leaders", {}),
            "funds": snapshot.get("funds", {}),
            "market_environment": snapshot.get("market_environment", {}),
            "stocks": snapshot.get("stocks", []),
            "sources": (snapshot.get("source_quality") or {}).get("sources", []),
            "guardrails": {
                "automatic_trading": False,
                "user_assets_modified": False,
                "model_promoted": False,
                "missing_facts_ai_filled": False,
            },
            "disclaimer": "仅作研究观察，不构成投资建议或买卖指令。",
        }
        write_json_atomic(self.data / "status.json", status)
        self._append_history(status)
        if should_emit(previous, status):
            self._append_alert(build_alert(status, emitted_at=now))
        return {
            "state": "completed",
            "trade_date": status["trade_date"],
            "checkpoint": checkpoint,
            "score": status["score"],
            "status": status["state"],
            "coverage_ratio": status["coverage_ratio"],
            "data_quality": status["data_quality"],
        }

    def _append_history(self, status: dict[str, Any]) -> None:
        history = load_json(self.data / "history.json", {"schema_version": 1, "runs": []})
        rows = history.get("runs") if isinstance(history.get("runs"), list) else []
        if not any(item.get("run_id") == status.get("run_id") for item in rows if isinstance(item, dict)):
            rows.append(status)
        history["schema_version"] = 1
        history["runs"] = rows[-500:]
        history["updated_at"] = status.get("generated_at")
        write_json_atomic(self.data / "history.json", history)

    def _append_alert(self, alert: dict[str, Any]) -> None:
        signals = load_json(self.data / "signals.json", {"schema_version": 1, "alerts": []})
        rows = signals.get("alerts") if isinstance(signals.get("alerts"), list) else []
        if not any(item.get("alert_id") == alert.get("alert_id") for item in rows if isinstance(item, dict)):
            rows.append(alert)
        signals.update({"schema_version": 1, "updated_at": alert.get("emitted_at"), "latest": alert, "alerts": rows[-200:]})
        write_json_atomic(self.data / "signals.json", signals)

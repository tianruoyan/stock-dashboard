from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


def build_alert(status: dict[str, Any], *, emitted_at: datetime) -> dict[str, Any]:
    state = status.get("state") if isinstance(status.get("state"), dict) else {}
    checkpoint = status.get("checkpoint") if isinstance(status.get("checkpoint"), dict) else {}
    payload = {
        "trade_date": status.get("trade_date"),
        "checkpoint_id": checkpoint.get("id"),
        "state": state.get("code"),
        "score": status.get("score"),
        "as_of": status.get("as_of"),
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    failed = status.get("failed_launch_gates") if isinstance(status.get("failed_launch_gates"), list) else []
    return {
        "alert_id": f"aihw_{digest}",
        "emitted_at": emitted_at.isoformat(timespec="seconds"),
        "trade_date": status.get("trade_date"),
        "checkpoint": checkpoint,
        "state": state,
        "score": status.get("score"),
        "coverage_ratio": status.get("coverage_ratio"),
        "headline": f"AI硬件二次启动雷达：{state.get('label', '🟡观察')} / {status.get('score', 0)}分",
        "reason": "；".join(failed[:3]) if failed else "绿色硬门槛已同时满足",
        "disclaimer": "仅为研究观察提醒，不构成买卖指令，不自动交易。",
    }


def should_emit(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if not previous:
        return True
    previous_checkpoint = previous.get("checkpoint") if isinstance(previous.get("checkpoint"), dict) else {}
    current_checkpoint = current.get("checkpoint") if isinstance(current.get("checkpoint"), dict) else {}
    previous_state = previous.get("state") if isinstance(previous.get("state"), dict) else {}
    current_state = current.get("state") if isinstance(current.get("state"), dict) else {}
    return (
        previous.get("trade_date") != current.get("trade_date")
        or previous_checkpoint.get("id") != current_checkpoint.get("id")
        or previous_state.get("code") != current_state.get("code")
    )


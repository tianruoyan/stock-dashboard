#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "alert-recovery-readiness.json"
TZ = timezone(timedelta(hours=8))


TRUSTED_INTRADAY_SOURCES = ("tencent_http", "eastmoney_push2_akshare", "tencent_minute")
FORBIDDEN_WHEN_DEGRADED = ("ths_sina_or_akshare_quote_decode",)


def main() -> int:
    source_health = load_json(DATA_DIR / "source-health.json")
    alert = load_json(DATA_DIR / "alert.json")
    quality = load_json(DATA_DIR / "quality-report.json")
    current_date = signal_date(alert.get("timestamp")) or quality.get("current_signal_date") or now_iso()[:10]
    source_rows = source_health.get("sources") if isinstance(source_health, dict) else {}
    source_rows = source_rows if isinstance(source_rows, dict) else {}
    trusted = trusted_source_rows(source_rows)
    forbidden = forbidden_source_rows(source_rows)
    active_alerts = alert.get("alerts") if isinstance(alert.get("alerts"), list) else []
    invalidated = alert.get("source_status") == "invalidated"
    quote_audit = alert.get("quote_audit") if isinstance(alert.get("quote_audit"), dict) else {}

    if active_alerts:
      status, summary = active_alert_status(quote_audit, forbidden)
    elif invalidated and trusted:
      status = "ready_to_recover"
      summary = "旧盘中异动批次已撤下；可信行情源可用于重产，但必须带交叉验证审计。"
    elif invalidated:
      status = "blocked"
      summary = "旧盘中异动批次已撤下，但可信行情源不足，暂不能恢复盘中异动触发。"
    else:
      status = "waiting"
      summary = "盘中异动暂无 active alerts，等待下一次盘中扫描。"

    report = {
        "timestamp": now_iso(),
        "current_signal_date": current_date,
        "status": status,
        "summary": summary,
        "alert_state": {
            "source_status": alert.get("source_status") or "active",
            "active_count": len(active_alerts),
            "note": alert.get("note") or "",
        },
        "trusted_sources": trusted,
        "forbidden_sources": forbidden,
        "recovery_policy": {
            "primary_quote_source": "tencent_http",
            "structure_source": "eastmoney_push2_akshare",
            "minute_source": "tencent_minute",
            "forbidden_until_trusted": list(FORBIDDEN_WHEN_DEGRADED),
            "required_quote_audit": [
                "source",
                "quote_time",
                "field_mapping",
                "sanity_checks.sample_count",
                "sanity_checks.max_abs_leader_change_pct",
                "sanity_checks.cross_source_verified",
            ],
            "hard_gates": [
                "active alerts 必须带 quote_audit，且 cross_source_verified=true。",
                "leaders.change_pct 不得超过 A股常规单日边界；异常值直接撤下。",
                "污染源仍 degraded 时，禁止只用该源恢复 alert。",
                "重产后必须执行 build_dashboard_reports.py，runtime-smoke 通过后再推送。",
            ],
        },
        "next_actions": next_actions(status, trusted, forbidden, invalidated, active_alerts),
        "rules": [
            "该文件供自动化进程和构建门禁使用，不进入交易主页面。",
            "盘中异动恢复必须优先使用腾讯 A股批量报价和分钟线，东财只用于涨跌停/炸板结构数据。",
            "同花顺/新浪/akshare 解码异常期间不得作为 active alert 的唯一报价依据。",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"alert-recovery-readiness: {status} - {summary}")
    return 0


def active_alert_status(quote_audit: dict[str, Any], forbidden: list[dict[str, Any]]) -> tuple[str, str]:
    sanity = quote_audit.get("sanity_checks") if isinstance(quote_audit, dict) else {}
    sanity = sanity if isinstance(sanity, dict) else {}
    cross_verified = sanity.get("cross_source_verified") is True
    source_text = json.dumps(quote_audit, ensure_ascii=False)
    forbidden_used = any(row["id"] in source_text for row in forbidden)
    if cross_verified and not forbidden_used:
        return "active_verified", "盘中异动已带交叉验证审计，可作为提示但仍需看盘面承接。"
    return "active_needs_review", "盘中异动已有 active alerts，但 quote_audit 不完整或仍引用异常源，需复核后使用。"


def trusted_source_rows(sources: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for source_id in TRUSTED_INTRADAY_SOURCES:
        source = sources.get(source_id)
        if not isinstance(source, dict):
            continue
        if source.get("status") in {"ok", "ok_empty"}:
            rows.append(source_view(source_id, source))
    return rows


def forbidden_source_rows(sources: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for source_id in FORBIDDEN_WHEN_DEGRADED:
        source = sources.get(source_id)
        if not isinstance(source, dict):
            continue
        if source.get("status") in {"degraded", "bad", "failed"}:
            rows.append(source_view(source_id, source))
    return rows


def source_view(source_id: str, source: dict[str, Any]) -> dict[str, str]:
    return {
        "id": source_id,
        "status": str(source.get("status") or ""),
        "checked_at": str(source.get("checked_at") or source.get("last_check") or ""),
        "usage": str(source.get("usage") or source.get("detail") or source.get("note") or ""),
    }


def next_actions(status: str, trusted: list[dict[str, Any]], forbidden: list[dict[str, Any]], invalidated: bool, active_alerts: list[Any]) -> list[str]:
    if status == "ready_to_recover":
        return [
            "用 tencent_http 作为 A股涨跌幅主源，重新生成 data/alert.json。",
            "用 eastmoney_push2_akshare 只补涨停池/跌停池/炸板池结构，不做全市场高频轮询。",
            "写入 quote_audit 并确认 cross_source_verified=true 后再触发推送。",
        ]
    if status == "blocked":
        return [
            "先恢复至少一个可信 A股批量报价源。",
            "恢复前盘中异动继续为空，页面只显示替代观察。",
        ]
    if status == "active_needs_review":
        return [
            "补齐 quote_audit 或撤下 active alerts。",
            "确认未使用 degraded 的同花顺/新浪/akshare 链路作为唯一报价源。",
        ]
    if active_alerts:
        return ["继续按当前 quote_audit 监控异常涨跌幅和源状态。"]
    if invalidated and not trusted:
        return ["等待可信行情源恢复。"]
    return ["等待盘中扫描进程产出新 alert。"]


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def signal_date(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


def now_iso() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

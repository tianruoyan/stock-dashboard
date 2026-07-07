#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"
OUT = DATA_DIR / "quality-report.json"
TZ = timezone(timedelta(hours=8))
FUTURE_TIMESTAMP_TOLERANCE_SECONDS = 120
BAD_LITERALS = ("[object Object]", "undefined", "None%", "NaN", "Infinity")
MOJIBAKE_PATTERN = re.compile(r"[�ÃÂ]|(?:æ|å|ç|è|é)[A-Za-z0-9_\- ]{0,8}")
REQUIRED_JSON = (
    "alert.json",
    "intraday.json",
    "premarket.json",
    "midday.json",
    "postmarket.json",
    "topics.json",
    "source-health.json",
)


def main() -> int:
    files = load_json_files()
    issues: list[dict[str, Any]] = []
    watch_names = load_watchlist_names()
    current_date = latest_signal_date(files)
    now = datetime.now(TZ)

    for name in REQUIRED_JSON:
        if name not in files:
            issues.append(issue("critical", name, "missing_file", "必需数据文件缺失"))

    for name, data in files.items():
        text = (DATA_DIR / name).read_text(encoding="utf-8")
        for literal in BAD_LITERALS:
            if literal in text:
                issues.append(issue("critical", name, "bad_literal", f"发现异常文本：{bad_literal_label(literal)}"))
        if MOJIBAKE_PATTERN.search(text):
            issues.append(issue("critical", name, "mojibake_text", "发现疑似乱码文本，需先清理数据源编码"))
        ts = data.get("timestamp") if isinstance(data, dict) else None
        if name in REQUIRED_JSON:
            if not ts:
                issues.append(issue("warning", name, "missing_timestamp", "缺少 timestamp"))
            elif signal_date(ts) != current_date:
                severity = "info" if name in {"evening-sentiment.json", "requirements.json"} else "warning"
                issues.append(issue(severity, name, "stale_timestamp", f"时间戳不是当前交易日：{ts}"))
            else:
                validate_timestamp_value(name, "timestamp", ts, issues, now)

        if isinstance(data, dict) and data.get("source_status") == "invalidated":
            issues.append(issue("warning", name, "invalidated_source", data.get("note", "数据批次已撤下")))

        scan_change_pct(name, data, watch_names, issues)
        scan_timestamp_fields(name, data, issues, now)

    validate_postmarket(files.get("postmarket.json"), issues)
    validate_core_file_contracts(files, issues)
    validate_alert(files.get("alert.json"), files.get("source-health.json"), issues)
    validate_evening(files.get("evening-sentiment.json"), issues, current_date)
    validate_source_health(files.get("source-health.json"), issues)
    validate_automation_health(files.get("automation-health.json"), issues, current_date)
    validate_theme_shifts(files.get("theme-shifts.json"), issues, current_date)
    validate_decision_feed(files.get("decision-feed.json"), issues, current_date)
    validate_data_trust(files.get("data-trust.json"), issues, current_date)
    validate_monitoring_coverage(files.get("monitoring-coverage.json"), issues, current_date)
    validate_cross_file_stock_consistency(files, watch_names, issues, current_date)

    status = overall_status(issues)
    report = {
        "timestamp": now_iso(),
        "current_signal_date": current_date,
        "status": status,
        "summary": summarize(status, issues),
        "issues": issues,
        "counts": {
            "critical": sum(1 for item in issues if item["severity"] == "critical"),
            "warning": sum(1 for item in issues if item["severity"] == "warning"),
            "info": sum(1 for item in issues if item["severity"] == "info"),
            "blocking": sum(1 for item in issues if item.get("impact_level") == "blocking"),
            "price_review": sum(1 for item in issues if item.get("impact_level") == "price_review"),
            "signal_review": sum(1 for item in issues if item.get("impact_level") == "signal_review"),
            "background_review": sum(1 for item in issues if item.get("impact_level") == "background_review"),
        },
        "rules": [
            "异常文本、JSON解析失败、必需文件缺失为 critical。",
            "当日核心文件时间戳不一致、数据源降级、alert污染撤下为 warning。",
            "晚间舆情过期只标 info；前端不得把非当日晚间舆情用于今日总控。",
            "观察池个股出现异常涨跌幅时进入 warning，必须回查行情源。",
            "盘中异动非空时必须带可信行情源证明；污染源仍降级时，无可信源证明的 active alert 为 critical。",
            "涨停/跌停/强势/弱势等标签必须与 change_pct 方向一致，冲突时进入 warning。",
            "decision-feed 如存在，机会/风险/验证项必须带标题、结论、置信度和来源文件。",
            "每个 issue 必须带 impact_level/decision_action，区分交易阻断、价格复核、信号复核和背景复核。",
            "timestamp/updated_at/quote_time 超过当前时间容忍阈值时进入 warning，禁止被当作最新实时依据。",
            "观察池个股跨文件出现涨跌幅大幅冲突、强弱标签互斥或涨跌停互斥时进入 warning。",
            "核心 JSON 必须满足页面渲染依赖的轻量字段契约，关键字段漏写或类型错误进入 signal_review。",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{status}: {report['summary']}")
    return 1 if status == "critical" else 0


def load_json_files() -> dict[str, Any]:
    files: dict[str, Any] = {}
    for path in sorted(DATA_DIR.glob("*.json")):
        try:
            files[path.name] = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            files[path.name] = {}
            # Parse errors are reported in a second pass using a synthetic issue.
            print(f"PARSE_ERROR {path.name}: {exc}")
    return files


def load_watchlist_names() -> set[str]:
    try:
        data = json.loads((CONFIG_DIR / "watchlist.json").read_text(encoding="utf-8"))
    except Exception:
        return set()
    names: set[str] = set()
    for group in ("watch_only", "small_deng", "old_deng"):
        for stock in data.get(group, {}).get("stocks", []):
            name = str(stock.get("name", "")).replace("XD", "").strip()
            if name:
                names.add(name)
    return names


def latest_signal_date(files: dict[str, Any]) -> str:
    dates = []
    for name in ("alert.json", "intraday.json", "midday.json", "postmarket.json", "topics.json"):
        ts = files.get(name, {}).get("timestamp") if isinstance(files.get(name), dict) else None
        date = signal_date(ts)
        if date:
            dates.append(date)
    return sorted(dates)[-1] if dates else now_iso()[:10]


def signal_date(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


def parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?", text)
        if not match:
            return None
        try:
            parsed = datetime.fromisoformat(match.group(0))
        except Exception:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def scan_timestamp_fields(name: str, obj: Any, issues: list[dict[str, Any]], now: datetime, path: str = "") -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{path}.{key}" if path else key
            if key in {"timestamp", "updated_at", "quote_time", "event_time", "generated_at"}:
                validate_timestamp_value(name, child_path, value, issues, now)
            scan_timestamp_fields(name, value, issues, now, child_path)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            scan_timestamp_fields(name, value, issues, now, f"{path}[{index}]")


def validate_timestamp_value(name: str, path: str, value: Any, issues: list[dict[str, Any]], now: datetime) -> None:
    parsed = parse_timestamp(value)
    if not parsed:
        return
    delta = (parsed - now).total_seconds()
    if delta > FUTURE_TIMESTAMP_TOLERANCE_SECONDS:
        minutes = int(delta // 60)
        issues.append(issue("warning", name, "future_timestamp", f"{path} 超前当前时间约 {minutes} 分钟：{value}", path))


def scan_change_pct(name: str, obj: Any, watch_names: set[str], issues: list[dict[str, Any]], path: str = "") -> None:
    if isinstance(obj, dict):
        item_name = str(obj.get("name") or obj.get("sector") or obj.get("title") or "").replace("XD", "")
        local_text = directional_label_text(obj)
        if "change_pct" in obj:
            try:
                pct = float(obj["change_pct"])
                if not math.isfinite(pct):
                    raise ValueError("not finite")
                if item_name in watch_names and abs(pct) > 20.5:
                    issues.append(issue("warning", name, "watchlist_extreme_change", f"{item_name} 涨跌幅 {pct}，需回查源", path))
                if item_name in watch_names and -10.9 <= pct <= -9.8:
                    issues.append(issue("warning", name, "watchlist_limit_down_like", f"{item_name} 接近跌停 {pct}，需确认是否真实", path))
                if re.search(r"跌停|接近跌停|封死跌停", local_text) and pct > -8:
                    issues.append(issue("warning", name, "label_pct_conflict", f"{item_name or path} 文本含跌停/接近跌停，但 change_pct={pct}，标签需复核", path))
                if re.search(r"涨停|封板|20cm|20CM", local_text) and pct < 8:
                    issues.append(issue("warning", name, "label_pct_conflict", f"{item_name or path} 文本含涨停/封板，但 change_pct={pct}，标签需复核", path))
                if re.search(r"强势|领涨|大涨|放量上涨|放量走强", local_text) and not re.search(r"前日|昨日|此前|兑现|转弱|回落|负反馈", local_text) and pct < -2:
                    issues.append(issue("warning", name, "strength_pct_conflict", f"{item_name or path} 标为强势但 change_pct={pct}，需复核方向", path))
                if re.search(r"弱势|大跌|放量下跌|负反馈|风险核心", local_text) and pct > 2:
                    issues.append(issue("warning", name, "weakness_pct_conflict", f"{item_name or path} 标为弱势/风险但 change_pct={pct}，需复核方向", path))
            except Exception:
                issues.append(issue("critical", name, "bad_change_pct", f"{item_name or path} change_pct 非数字：{obj['change_pct']}", path))
        for key, value in obj.items():
            scan_change_pct(name, value, watch_names, issues, f"{path}.{key}" if path else key)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            scan_change_pct(name, value, watch_names, issues, f"{path}[{index}]")


def validate_cross_file_stock_consistency(files: dict[str, Any], watch_names: set[str], issues: list[dict[str, Any]], current_date: str) -> None:
    records: dict[str, list[dict[str, Any]]] = {}
    comparable_files = stock_consistency_files(files, current_date)
    for file_name, data in files.items():
        if not isinstance(data, dict):
            continue
        if file_name not in comparable_files:
            continue
        if signal_date(data.get("timestamp")) not in {"", current_date}:
            continue
        collect_stock_signal_records(file_name, data, watch_names, records)
    for stock, rows in records.items():
        if len(rows) < 2:
            continue
        numeric = [row for row in rows if isinstance(row.get("pct"), (int, float))]
        if len(numeric) >= 2:
            high = max(numeric, key=lambda row: row["pct"])
            low = min(numeric, key=lambda row: row["pct"])
            if high["pct"] - low["pct"] >= 8:
                issues.append(issue(
                    "warning",
                    "cross-file",
                    "stock_pct_cross_file_conflict",
                    f"{stock} 跨文件涨跌幅差异过大：{low['file']} {low['pct']}% vs {high['file']} {high['pct']}%",
                    stock,
                ))
        strong = [row for row in rows if row.get("direction") == "strong"]
        weak = [row for row in rows if row.get("direction") == "weak"]
        if strong and weak:
            issues.append(issue(
                "warning",
                "cross-file",
                "stock_direction_cross_file_conflict",
                f"{stock} 跨文件强弱标签冲突：{strong[0]['file']} 强势 vs {weak[0]['file']} 弱势",
                stock,
            ))
        limit_up = [row for row in rows if row.get("limit") == "up"]
        limit_down = [row for row in rows if row.get("limit") == "down"]
        if limit_up and limit_down:
            issues.append(issue(
                "warning",
                "cross-file",
                "stock_limit_cross_file_conflict",
                f"{stock} 跨文件涨跌停标签冲突：{limit_up[0]['file']} 涨停 vs {limit_down[0]['file']} 跌停",
                stock,
                ))


def stock_consistency_files(files: dict[str, Any], current_date: str) -> set[str]:
    current = {
        name
        for name, data in files.items()
        if isinstance(data, dict) and signal_date(data.get("timestamp")) == current_date
    }
    if "postmarket.json" in current:
        return current & {"postmarket.json", "evening-sentiment.json", "topics.json", "decision-feed.json", "theme-shifts.json"}
    if "intraday.json" in current:
        return current & {"alert.json", "intraday.json", "midday.json", "topics.json", "decision-feed.json", "theme-shifts.json"}
    if "midday.json" in current:
        return current & {"midday.json", "intraday.json", "topics.json", "decision-feed.json", "theme-shifts.json"}
    return current & {"premarket.json", "topics.json", "decision-feed.json", "theme-shifts.json"}


def collect_stock_signal_records(file_name: str, obj: Any, watch_names: set[str], records: dict[str, list[dict[str, Any]]], path: str = "") -> None:
    if isinstance(obj, dict):
        raw_name = str(obj.get("name") or obj.get("stock") or obj.get("leader") or "").replace("XD", "").strip()
        if raw_name in watch_names:
            record = stock_signal_record(file_name, path, raw_name, obj)
            if record:
                records.setdefault(raw_name, []).append(record)
        for key, value in obj.items():
            collect_stock_signal_records(file_name, value, watch_names, records, f"{path}.{key}" if path else key)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            collect_stock_signal_records(file_name, value, watch_names, records, f"{path}[{index}]")


def stock_signal_record(file_name: str, path: str, stock: str, obj: dict[str, Any]) -> dict[str, Any] | None:
    text = directional_label_text(obj)
    pct = None
    if "change_pct" in obj:
        try:
            pct_value = float(obj["change_pct"])
            if math.isfinite(pct_value):
                pct = pct_value
        except Exception:
            pct = None
    limit = ""
    if re.search(r"涨停|封板|20cm|20CM", text):
        limit = "up"
    elif re.search(r"跌停|接近跌停|封死跌停", text):
        limit = "down"
    direction = ""
    if pct is not None:
        if pct >= 5 or limit == "up":
            direction = "strong"
        elif pct <= -5 or limit == "down":
            direction = "weak"
    if not direction:
        if re.search(r"强势|领涨|大涨|放量上涨|放量走强|突破|加速", text) and not re.search(r"前日|昨日|此前|兑现|转弱|回落|负反馈", text):
            direction = "strong"
        elif re.search(r"弱势|大跌|放量下跌|负反馈|风险核心", text):
            direction = "weak"
    if pct is None and not direction and not limit:
        return None
    return {
        "file": file_name,
        "path": path,
        "stock": stock,
        "pct": pct,
        "direction": direction,
        "limit": limit,
    }


def compact_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(value)


def directional_label_text(obj: dict[str, Any]) -> str:
    keys = ("status", "strength", "trend", "type", "signal_type", "tag", "label", "note", "reason")
    parts = [str(obj.get(key) or "") for key in keys]
    return " ".join(parts)


def validate_postmarket(data: Any, issues: list[dict[str, Any]]) -> None:
    if not isinstance(data, dict):
        return
    patch = data.get("closing_auction_patch") or {}
    for key in ("summary", "signals", "impact", "watch_next_day"):
        if not patch.get(key):
            issues.append(issue("warning", "postmarket.json", "missing_closing_patch_field", f"closing_auction_patch.{key} 缺失"))
    if not (data.get("review") or {}).get("evidence"):
        issues.append(issue("warning", "postmarket.json", "missing_review_evidence", "review.evidence 缺失"))
    for index, item in enumerate(data.get("hotspots") or []):
        for key in ("evidence", "continuity", "risk"):
            if not item.get(key):
                issues.append(issue("warning", "postmarket.json", "missing_hotspot_field", f"hotspots[{index}].{key} 缺失"))


CORE_CONTRACTS: dict[str, dict[str, type | tuple[type, ...]]] = {
    "premarket.json": {
        "summary": str,
        "us_overnight": dict,
        "hk_auction": dict,
        "overnight_news": list,
        "market_context": dict,
    },
    "intraday.json": {
        "summary": str,
        "index": dict,
        "sentiment": dict,
        "main_trends": list,
        "themes": list,
        "actions": list,
    },
    "midday.json": {
        "morning_snapshot": dict,
        "morning_review": dict,
        "afternoon_watch": list,
        "risk": list,
    },
    "postmarket.json": {
        "index": dict,
        "market_breadth": dict,
        "review": dict,
        "closing_auction_patch": dict,
        "hotspots": list,
        "next_day_watch": list,
    },
    "evening-sentiment.json": {
        "p0_alerts": list,
        "sentiment_summary": dict,
        "news": list,
    },
    "topics.json": {
        "topics": list,
    },
}


def validate_core_file_contracts(files: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    for file_name, contract in CORE_CONTRACTS.items():
        data = files.get(file_name)
        if data in (None, {}):
            continue
        if not isinstance(data, dict):
            issues.append(issue("warning", file_name, "schema_contract_type", f"{file_name} 根节点必须是对象"))
            continue
        for path, expected in contract.items():
            validate_contract_path(file_name, data, path, expected, issues)
        validate_contract_items(file_name, data, issues)


def validate_contract_path(file_name: str, data: dict[str, Any], path: str, expected: type | tuple[type, ...], issues: list[dict[str, Any]]) -> None:
    exists, value = get_path(data, path)
    if not exists:
        issues.append(issue("warning", file_name, "schema_contract_missing", f"{path} 缺失", path))
        return
    if not isinstance(value, expected):
        issues.append(issue("warning", file_name, "schema_contract_type", f"{path} 类型错误：期望 {type_label(expected)}，实际 {type(value).__name__}", path))


def validate_contract_items(file_name: str, data: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    if file_name == "intraday.json":
        validate_named_array(file_name, data.get("main_trends"), "main_trends", issues)
        validate_text_or_object_array(file_name, data.get("actions"), "actions", issues)
    elif file_name == "midday.json":
        review = data.get("morning_review") or {}
        if isinstance(review, dict) and not isinstance(review.get("one_sentence"), str):
            issues.append(issue("warning", file_name, "schema_contract_type", "morning_review.one_sentence 必须是字符串", "morning_review.one_sentence"))
    elif file_name == "postmarket.json":
        validate_array_objects(file_name, data.get("hotspots"), "hotspots", ("name", "evidence"), issues)
    elif file_name == "evening-sentiment.json":
        validate_array_objects(file_name, data.get("p0_alerts"), "p0_alerts", ("title", "severity", "evidence"), issues)
        validate_array_objects(file_name, data.get("news"), "news", ("text",), issues)
    elif file_name == "topics.json":
        validate_array_objects(file_name, data.get("topics"), "topics", ("name", "status"), issues)


def validate_array_objects(file_name: str, value: Any, path: str, required_keys: tuple[str, ...], issues: list[dict[str, Any]]) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        issues.append(issue("warning", file_name, "schema_contract_type", f"{path} 必须是数组", path))
        return
    for index, item in enumerate(value[:12]):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            issues.append(issue("warning", file_name, "schema_contract_type", f"{item_path} 必须是对象", item_path))
            continue
        for key in required_keys:
            if item.get(key) in (None, "", []):
                issues.append(issue("warning", file_name, "schema_contract_missing", f"{item_path}.{key} 缺失", item_path))


def validate_named_array(file_name: str, value: Any, path: str, issues: list[dict[str, Any]]) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        issues.append(issue("warning", file_name, "schema_contract_type", f"{path} 必须是数组", path))
        return
    for index, item in enumerate(value[:12]):
        item_path = f"{path}[{index}]"
        if isinstance(item, str):
            continue
        if not isinstance(item, dict):
            issues.append(issue("warning", file_name, "schema_contract_type", f"{item_path} 必须是对象或字符串", item_path))
            continue
        if not first_text(item.get("sector"), item.get("name"), item.get("title"), item.get("display_name"), item.get("theme")):
            issues.append(issue("warning", file_name, "schema_contract_missing", f"{item_path} 缺少可展示名称字段", item_path))


def validate_text_or_object_array(file_name: str, value: Any, path: str, issues: list[dict[str, Any]]) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        issues.append(issue("warning", file_name, "schema_contract_type", f"{path} 必须是数组", path))
        return
    for index, item in enumerate(value[:12]):
        if not isinstance(item, (str, dict)):
            issues.append(issue("warning", file_name, "schema_contract_type", f"{path}[{index}] 必须是字符串或对象", f"{path}[{index}]"))


def get_path(data: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def type_label(expected: type | tuple[type, ...]) -> str:
    values = expected if isinstance(expected, tuple) else (expected,)
    return "/".join(value.__name__ for value in values)


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def validate_alert(data: Any, source_health: Any, issues: list[dict[str, Any]]) -> None:
    if not isinstance(data, dict):
        return
    alerts = data.get("alerts")
    if alerts is None:
        issues.append(issue("warning", "alert.json", "missing_alerts", "alerts 字段缺失"))
        return
    if not isinstance(alerts, list):
        issues.append(issue("critical", "alert.json", "bad_alerts", "alerts 必须是数组"))
        return
    if data.get("source_status") == "invalidated" and alerts:
        issues.append(issue("critical", "alert.json", "invalidated_alert_has_rows", "source_status=invalidated 时 alerts 必须为空，禁止展示已撤下污染批次"))
    polluted = has_polluted_quote_source(source_health)
    trusted_proof = alert_trusted_source_text(data)
    if alerts and polluted and not has_trusted_alert_source(trusted_proof):
        issues.append(issue(
            "critical",
            "alert.json",
            "active_alert_without_trusted_source",
            "行情污染源仍降级，但 alert.json 存在 active alerts 且缺少可信源证明；禁止发布为盘中交易依据"
        ))
    validate_alert_quote_audit(data, alerts, polluted, issues)
    for index, item in enumerate(alerts):
        if not isinstance(item, dict):
            issues.append(issue("critical", "alert.json", "bad_alert_item", f"alerts[{index}] 不是对象", f"alerts[{index}]"))
            continue
        for key in ("id", "time", "sector", "type", "leaders", "signal_type"):
            if item.get(key) in (None, "", []):
                issues.append(issue("warning", "alert.json", "missing_alert_field", f"alerts[{index}].{key} 缺失", f"alerts[{index}]"))
        leaders = item.get("leaders") or []
        if not isinstance(leaders, list):
            issues.append(issue("warning", "alert.json", "bad_alert_leaders", f"alerts[{index}].leaders 不是数组", f"alerts[{index}].leaders"))
            continue
        for leader_index, leader in enumerate(leaders):
            if not isinstance(leader, dict):
                issues.append(issue("warning", "alert.json", "bad_alert_leader", f"alerts[{index}].leaders[{leader_index}] 不是对象", f"alerts[{index}].leaders[{leader_index}]"))
                continue
            if not leader.get("name"):
                issues.append(issue("warning", "alert.json", "missing_alert_leader_name", f"alerts[{index}].leaders[{leader_index}].name 缺失", f"alerts[{index}].leaders[{leader_index}]"))
            if "change_pct" not in leader:
                issues.append(issue("warning", "alert.json", "missing_alert_leader_pct", f"alerts[{index}].leaders[{leader_index}].change_pct 缺失", f"alerts[{index}].leaders[{leader_index}]"))
                continue
            try:
                pct = float(leader["change_pct"])
                if not math.isfinite(pct):
                    raise ValueError("not finite")
                if abs(pct) > 20.5:
                    issues.append(issue("critical", "alert.json", "impossible_alert_pct", f"{leader.get('name') or 'leader'} 触发窗口涨跌幅 {pct}，超过A股常规单日涨跌幅边界，疑似污染源", f"alerts[{index}].leaders[{leader_index}]"))
                elif abs(pct) > 8:
                    issues.append(issue("warning", "alert.json", "suspicious_alert_pct", f"{leader.get('name') or 'leader'} 触发窗口涨跌幅 {pct}，3分钟窗口需回查原始行情源", f"alerts[{index}].leaders[{leader_index}]"))
            except Exception:
                issues.append(issue("critical", "alert.json", "bad_alert_leader_pct", f"{leader.get('name') or 'leader'} change_pct 非数字：{leader.get('change_pct')}", f"alerts[{index}].leaders[{leader_index}]"))


def validate_alert_quote_audit(data: dict[str, Any], alerts: list[Any], polluted: bool, issues: list[dict[str, Any]]) -> None:
    if not alerts:
        return
    audit = data.get("quote_audit")
    if not isinstance(audit, dict):
        issues.append(issue(
            "critical",
            "alert.json",
            "missing_alert_quote_audit",
            "alert.json 存在 active alerts，但缺少 quote_audit；必须声明行情源、quote_time、涨跌幅字段和异常值检查"
        ))
        return
    required = ("provider", "quote_time", "pct_field", "sanity_checks")
    for key in required:
        if audit.get(key) in (None, "", []):
            issues.append(issue("critical", "alert.json", "missing_alert_quote_audit_field", f"quote_audit.{key} 缺失", "quote_audit"))
    sanity = audit.get("sanity_checks") or {}
    if not isinstance(sanity, dict):
        issues.append(issue("critical", "alert.json", "bad_alert_quote_audit", "quote_audit.sanity_checks 必须是对象", "quote_audit.sanity_checks"))
        return
    for key in ("sample_count", "max_abs_leader_change_pct", "cross_source_verified"):
        if sanity.get(key) in (None, "", []):
            issues.append(issue("critical", "alert.json", "missing_alert_quote_audit_field", f"quote_audit.sanity_checks.{key} 缺失", "quote_audit.sanity_checks"))
    observed = max_abs_alert_leader_pct(alerts)
    try:
        reported = float(sanity.get("max_abs_leader_change_pct"))
        if observed is not None and reported + 0.01 < observed:
            issues.append(issue("warning", "alert.json", "alert_quote_audit_mismatch", f"quote_audit 最大涨跌幅 {reported} 小于实际 leaders 最大值 {observed}", "quote_audit.sanity_checks"))
    except Exception:
        if sanity.get("max_abs_leader_change_pct") not in (None, ""):
            issues.append(issue("critical", "alert.json", "bad_alert_quote_audit", f"quote_audit.sanity_checks.max_abs_leader_change_pct 非数字：{sanity.get('max_abs_leader_change_pct')}", "quote_audit.sanity_checks"))
    try:
        if int(sanity.get("sample_count")) < len(alerts):
            issues.append(issue("warning", "alert.json", "alert_quote_audit_mismatch", "quote_audit 样本数小于 alerts 数量", "quote_audit.sanity_checks"))
    except Exception:
        if sanity.get("sample_count") not in (None, ""):
            issues.append(issue("critical", "alert.json", "bad_alert_quote_audit", f"quote_audit.sanity_checks.sample_count 非数字：{sanity.get('sample_count')}", "quote_audit.sanity_checks"))
    if polluted and sanity.get("cross_source_verified") is not True:
        issues.append(issue("critical", "alert.json", "alert_quote_not_cross_verified", "行情污染源仍降级，active alerts 必须 quote_audit.sanity_checks.cross_source_verified=true 后才能发布", "quote_audit.sanity_checks"))


def max_abs_alert_leader_pct(alerts: list[Any]) -> float | None:
    values: list[float] = []
    for item in alerts:
        if not isinstance(item, dict):
            continue
        for leader in item.get("leaders") or []:
            if not isinstance(leader, dict) or "change_pct" not in leader:
                continue
            try:
                pct = float(leader["change_pct"])
            except Exception:
                continue
            if math.isfinite(pct):
                values.append(abs(pct))
    return max(values) if values else None


def has_polluted_quote_source(source_health: Any) -> bool:
    if not isinstance(source_health, dict):
        return False
    sources = source_health.get("sources") or {}
    iterator = sources.items() if isinstance(sources, dict) else []
    for name, source in iterator:
        if not isinstance(source, dict):
            continue
        status = source.get("status")
        text = f"{name} {source.get('note') or ''} {source.get('detail') or ''} {source.get('usage') or ''}"
        if status in {"degraded", "bad", "failed"} and re.search(r"污染|decode|akshare|异常|HTML|Can not decode", text, re.I):
            return True
    return False


def alert_trusted_source_text(data: dict[str, Any]) -> str:
    keys = ("source", "data_source", "quote_source", "source_name", "source_chain", "source_status", "source_note")
    parts = [str(data.get(key) or "") for key in keys]
    for item in data.get("alerts") or []:
        if isinstance(item, dict):
            parts.extend(str(item.get(key) or "") for key in keys)
            for leader in item.get("leaders") or []:
                if isinstance(leader, dict):
                    parts.extend(str(leader.get(key) or "") for key in keys)
    return " ".join(parts)


def has_trusted_alert_source(text: str) -> bool:
    return bool(re.search(r"tencent|腾讯|mootdx|通达信|tdx|原始涨跌幅|已审计|audited|verified|trusted", text, re.I))


def validate_evening(data: Any, issues: list[dict[str, Any]], current_date: str) -> None:
    if not isinstance(data, dict):
        return
    if signal_date(data.get("timestamp")) != current_date:
        issues.append(issue("info", "evening-sentiment.json", "evening_not_current", "晚间舆情不是当前交易日，不参与今日总控"))
    for index, item in enumerate(data.get("p0_alerts") or []):
        for key in ("title", "severity", "why_p0", "evidence", "watch_next_day", "source"):
            if not item.get(key):
                issues.append(issue("warning", "evening-sentiment.json", "missing_p0_field", f"p0_alerts[{index}].{key} 缺失"))


def validate_source_health(data: Any, issues: list[dict[str, Any]]) -> None:
    if not isinstance(data, dict):
        return
    sources = data.get("sources") or {}
    if isinstance(sources, dict):
        iterator = sources.items()
    else:
        iterator = ((item.get("id") or item.get("name") or "unknown", item) for item in sources if isinstance(item, dict))
    for name, source in iterator:
        status = source.get("status")
        if status in {"degraded", "bad", "failed"}:
            code = "source_failed" if status == "failed" else "source_degraded"
            issues.append(issue("warning", "source-health.json", code, f"{name}: {source.get('note') or source.get('detail') or source.get('usage') or status}"))


def validate_decision_feed(data: Any, issues: list[dict[str, Any]], current_date: str) -> None:
    if data in (None, {}):
        return
    if not isinstance(data, dict):
        issues.append(issue("critical", "decision-feed.json", "bad_decision_feed", "decision-feed 根节点必须是对象"))
        return
    quality_status = ((data.get("quality_gate") or {}).get("status") or "").strip()
    feed_date = data.get("current_signal_date") or signal_date(data.get("timestamp"))
    if feed_date != current_date:
        issues.append(issue("warning", "decision-feed.json", "stale_decision_feed", f"decision-feed 日期不是当前交易日：{feed_date}"))
    coverage = data.get("observation_coverage")
    if not isinstance(coverage, dict):
        issues.append(issue("warning", "decision-feed.json", "missing_observation_coverage", "observation_coverage 缺失或不是对象"))
    else:
        for key in ("summary", "independent_count", "active_market_count", "topic_inherited_count", "status"):
            if coverage.get(key) in (None, "", []):
                issues.append(issue("warning", "decision-feed.json", "missing_observation_coverage_field", f"observation_coverage.{key} 缺失"))
    brief = data.get("decision_brief")
    if not isinstance(brief, dict):
        issues.append(issue("warning", "decision-feed.json", "missing_decision_brief", "decision_brief 缺失或不是对象"))
    else:
        for key in ("stance", "action", "reasons", "risk_focus", "upgrade_watch"):
            if key not in brief:
                issues.append(issue("warning", "decision-feed.json", "missing_decision_brief_field", f"decision_brief.{key} 缺失"))
    for section in ("opportunities", "risks", "verifications"):
        rows = data.get(section)
        if not isinstance(rows, list):
            issues.append(issue("warning", "decision-feed.json", "missing_decision_section", f"{section} 缺失或不是数组"))
            continue
        for index, item in enumerate(rows):
            if not isinstance(item, dict):
                issues.append(issue("critical", "decision-feed.json", "bad_decision_item", f"{section}[{index}] 不是对象", section))
                continue
            for key in ("title", "trigger_reason", "conclusion", "confidence", "source_files"):
                if not item.get(key):
                    issues.append(issue("warning", "decision-feed.json", "missing_decision_field", f"{section}[{index}].{key} 缺失", f"{section}[{index}]"))
            for key in ("signal_grade", "signal_score", "use_action", "use_reasons", "discovery_type", "evidence_score"):
                if item.get(key) in (None, "", []):
                    issues.append(issue("warning", "decision-feed.json", "missing_usability_field", f"{section}[{index}].{key} 缺失", f"{section}[{index}]"))
            for key in ("observation_source", "independent_observation"):
                if key not in item:
                    issues.append(issue("warning", "decision-feed.json", "missing_observation_field", f"{section}[{index}].{key} 缺失", f"{section}[{index}]"))
            if "missing_evidence" not in item or not isinstance(item.get("missing_evidence"), list):
                issues.append(issue("warning", "decision-feed.json", "missing_usability_field", f"{section}[{index}].missing_evidence 缺失或不是数组", f"{section}[{index}]"))
            if item.get("signal_grade") not in (None, "A", "B", "C", "D"):
                issues.append(issue("warning", "decision-feed.json", "bad_signal_grade", f"{section}[{index}].signal_grade 非 A/B/C/D", f"{section}[{index}]"))
            if isinstance(item.get("evidence_score"), (int, float)) and not 0 <= item.get("evidence_score") <= 100:
                issues.append(issue("warning", "decision-feed.json", "bad_evidence_score", f"{section}[{index}].evidence_score 不在 0-100", f"{section}[{index}]"))
            if section in {"opportunities", "risks"} and item.get("confidence") == "high" and not item.get("evidence"):
                issues.append(issue("warning", "decision-feed.json", "high_confidence_without_evidence", f"{section}[{index}] 高置信但缺少 evidence", f"{section}[{index}]"))
            if section == "opportunities" and has_stale_relative_time(json.dumps(item, ensure_ascii=False), current_date):
                issues.append(issue("warning", "decision-feed.json", "stale_relative_time", f"{section}[{index}] 含过期相对日期", f"{section}[{index}]"))
            if section == "opportunities" and quality_status in {"degraded", "critical"}:
                if not item.get("quality_flags"):
                    issues.append(issue("warning", "decision-feed.json", "missing_quality_flags", f"{section}[{index}] 数据降级但缺少 quality_flags", f"{section}[{index}]"))
                if item.get("confidence") in {"medium", "high"}:
                    issues.append(issue("warning", "decision-feed.json", "opportunity_not_downgraded", f"{section}[{index}] 数据降级但机会置信度未降权", f"{section}[{index}]"))
    validate_decision_conflicts(data, issues)


def validate_decision_conflicts(data: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    conflicts = data.get("conflicts")
    if conflicts is None:
        issues.append(issue("warning", "decision-feed.json", "missing_conflicts", "decision-feed 缺少 conflicts 冲突校验数组"))
        return
    if not isinstance(conflicts, list):
        issues.append(issue("warning", "decision-feed.json", "bad_conflicts", "conflicts 必须是数组"))
        return
    expected = expected_decision_conflicts(data)
    rendered = {str(item.get("theme") or "") for item in conflicts if isinstance(item, dict)}
    for theme in expected[:5]:
        if theme not in rendered:
            issues.append(issue("warning", "decision-feed.json", "missing_signal_conflict", f"同一主线多空信号未进入冲突校验：{theme}"))
    for index, item in enumerate(conflicts):
        if not isinstance(item, dict):
            issues.append(issue("warning", "decision-feed.json", "bad_conflict_item", f"conflicts[{index}] 不是对象", f"conflicts[{index}]"))
            continue
        for key in ("theme", "sections", "verdict", "severity", "action", "evidence"):
            if item.get(key) in (None, "", []):
                issues.append(issue("warning", "decision-feed.json", "missing_conflict_field", f"conflicts[{index}].{key} 缺失", f"conflicts[{index}]"))


def expected_decision_conflicts(data: dict[str, Any]) -> list[str]:
    buckets: dict[str, set[str]] = {}
    for section in ("opportunities", "risks", "verifications"):
        for item in data.get(section) or []:
            if not isinstance(item, dict):
                continue
            key = normalize_conflict_title(item.get("title"))
            if key:
                buckets.setdefault(key, set()).add(section)
    return [key for key, sections in buckets.items() if len(sections) >= 2]


def normalize_conflict_title(title: Any) -> str:
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    text = re.sub(r"^(主线变化：|新线观察：)", "", text[:80])
    text = re.sub(r"(候选验证|验证)$", "", text).strip()
    aliases = {
        "半导体设备": "科技硬件链",
        "半导体材料": "科技硬件链",
        "半导体零部件": "科技硬件链",
    }
    return aliases.get(text, text)


def validate_theme_shifts(data: Any, issues: list[dict[str, Any]], current_date: str) -> None:
    if data in (None, {}):
        issues.append(issue("warning", "theme-shifts.json", "missing_theme_shifts", "theme-shifts 缺失，无法识别主线边际变化"))
        return
    if not isinstance(data, dict):
        issues.append(issue("critical", "theme-shifts.json", "bad_theme_shifts", "theme-shifts 根节点必须是对象"))
        return
    shift_date = data.get("current_signal_date") or signal_date(data.get("timestamp"))
    if shift_date != current_date:
        issues.append(issue("warning", "theme-shifts.json", "stale_theme_shifts", f"theme-shifts 日期不是当前交易日：{shift_date}"))
    rows = data.get("shifts")
    if not isinstance(rows, list):
        issues.append(issue("warning", "theme-shifts.json", "missing_shifts", "shifts 缺失或不是数组"))
        return
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            issues.append(issue("warning", "theme-shifts.json", "bad_shift_item", f"shifts[{index}] 不是对象", f"shifts[{index}]"))
            continue
        for key in ("theme", "state", "score", "conclusion", "evidence", "watch_next", "source_files"):
            if item.get(key) in (None, "", []):
                issues.append(issue("warning", "theme-shifts.json", "missing_shift_field", f"shifts[{index}].{key} 缺失", f"shifts[{index}]"))
        if item.get("state") not in (None, "warming", "emerging", "crowded", "fading", "risk", "watch"):
            issues.append(issue("warning", "theme-shifts.json", "bad_shift_state", f"shifts[{index}].state 非法", f"shifts[{index}]"))


def validate_automation_health(data: Any, issues: list[dict[str, Any]], current_date: str) -> None:
    if data in (None, {}):
        issues.append(issue("warning", "automation-health.json", "missing_automation_health", "automation-health 缺失，无法确认自动化是否按时产出"))
        return
    if not isinstance(data, dict):
        issues.append(issue("critical", "automation-health.json", "bad_automation_health", "automation-health 根节点必须是对象"))
        return
    health_date = data.get("current_signal_date") or signal_date(data.get("timestamp"))
    if health_date != current_date:
        issues.append(issue("warning", "automation-health.json", "stale_automation_health", f"automation-health 日期不是当前交易日：{health_date}"))
    rows = data.get("processes")
    if not isinstance(rows, list) or not rows:
        issues.append(issue("warning", "automation-health.json", "missing_processes", "processes 缺失或为空"))
        return
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            issues.append(issue("warning", "automation-health.json", "bad_process_item", f"processes[{index}] 不是对象", f"processes[{index}]"))
            continue
        for key in ("id", "label", "file", "due", "status", "action", "reason", "failure_type", "diagnosis", "next_actions"):
            if item.get(key) in (None, "", []):
                issues.append(issue("warning", "automation-health.json", "missing_process_field", f"processes[{index}].{key} 缺失", f"processes[{index}]"))
        if "related_sources" not in item or not isinstance(item.get("related_sources"), list):
            issues.append(issue("warning", "automation-health.json", "missing_process_field", f"processes[{index}].related_sources 缺失或不是数组", f"processes[{index}]"))
        if item.get("status") not in (None, "ok", "waiting", "late", "missing", "invalidated"):
            issues.append(issue("warning", "automation-health.json", "bad_process_status", f"processes[{index}].status 非法", f"processes[{index}]"))


def validate_data_trust(data: Any, issues: list[dict[str, Any]], current_date: str) -> None:
    if data in (None, {}):
        return
    if not isinstance(data, dict):
        issues.append(issue("critical", "data-trust.json", "bad_data_trust", "data-trust 根节点必须是对象"))
        return
    trust_date = data.get("current_signal_date") or signal_date(data.get("timestamp"))
    if trust_date != current_date:
        issues.append(issue("warning", "data-trust.json", "stale_data_trust", f"data-trust 日期不是当前交易日：{trust_date}"))
    rows = data.get("files")
    if not isinstance(rows, list) or not rows:
        issues.append(issue("warning", "data-trust.json", "missing_trust_files", "files 缺失或为空"))
        return
    required = {"file", "label", "status", "trust_score", "use_action", "reason", "session_phase", "session_relevance", "session_action", "session_reason", "freshness_status", "freshness_action", "freshness_reason", "freshness_minutes"}
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            issues.append(issue("warning", "data-trust.json", "bad_trust_item", f"files[{index}] 不是对象", f"files[{index}]"))
            continue
        for key in required:
            if item.get(key) in (None, "", []):
                issues.append(issue("warning", "data-trust.json", "missing_trust_field", f"files[{index}].{key} 缺失", f"files[{index}]"))
        if item.get("status") not in (None, "trusted", "degraded", "stale", "invalidated", "missing"):
            issues.append(issue("warning", "data-trust.json", "bad_trust_status", f"files[{index}].status 非法", f"files[{index}]"))
        if item.get("session_relevance") not in (None, "current", "historical", "upcoming", "background", "blocked"):
            issues.append(issue("warning", "data-trust.json", "bad_session_relevance", f"files[{index}].session_relevance 非法", f"files[{index}]"))
        if item.get("freshness_status") not in (None, "fresh", "aging", "stale", "future", "unknown", "phase_expired", "blocked"):
            issues.append(issue("warning", "data-trust.json", "bad_freshness_status", f"files[{index}].freshness_status 非法", f"files[{index}]"))


def validate_monitoring_coverage(data: Any, issues: list[dict[str, Any]], current_date: str) -> None:
    if data in (None, {}):
        return
    if not isinstance(data, dict):
        issues.append(issue("critical", "monitoring-coverage.json", "bad_monitoring_coverage", "monitoring-coverage 根节点必须是对象"))
        return
    coverage_date = data.get("current_signal_date") or signal_date(data.get("timestamp"))
    if coverage_date != current_date:
        issues.append(issue("warning", "monitoring-coverage.json", "stale_monitoring_coverage", f"monitoring-coverage 日期不是当前交易日：{coverage_date}"))
    rows = data.get("blind_spots")
    if not isinstance(rows, list):
        issues.append(issue("warning", "monitoring-coverage.json", "missing_blind_spots", "blind_spots 缺失或不是数组"))
        return
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            issues.append(issue("warning", "monitoring-coverage.json", "bad_blind_spot", f"blind_spots[{index}] 不是对象", f"blind_spots[{index}]"))
            continue
        for key in ("id", "title", "severity", "conclusion", "impacted_decisions", "fallback_action", "source_files"):
            if item.get(key) in (None, "", []):
                issues.append(issue("warning", "monitoring-coverage.json", "missing_blind_spot_field", f"blind_spots[{index}].{key} 缺失", f"blind_spots[{index}]"))
        if item.get("severity") == "critical" and item.get("fallback_checks") in (None, "", []):
            issues.append(issue("warning", "monitoring-coverage.json", "missing_fallback_checks", f"blind_spots[{index}] 核心盲区缺少可执行 fallback_checks", f"blind_spots[{index}]"))
        if item.get("severity") not in (None, "critical", "warning", "info"):
            issues.append(issue("warning", "monitoring-coverage.json", "bad_blind_spot_severity", f"blind_spots[{index}].severity 非法", f"blind_spots[{index}]"))


def has_stale_relative_time(text: str, current_date: str) -> bool:
    try:
        weekday = datetime.fromisoformat(current_date).weekday()
    except Exception:
        return False
    weekday_words = {
        "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6, "周天": 6,
    }
    return any(word in text and weekday != day for word, day in weekday_words.items())


def issue(severity: str, file: str, code: str, message: str, path: str = "") -> dict[str, Any]:
    impact_level, decision_action = issue_impact(code, file, message)
    return {
        "severity": severity,
        "file": file,
        "path": path,
        "code": code,
        "message": message,
        "impact_level": impact_level,
        "decision_action": decision_action,
    }


def issue_impact(code: str, file: str, message: str) -> tuple[str, str]:
    text = f"{code} {file} {message}"
    if re.search(r"official_policy|政策|通用网页|官网|部委", text, re.I):
        return "background_review", "仅作政策/背景覆盖复核，不阻断盘中价格和交易触发"
    if code in {
        "missing_file",
        "bad_literal",
        "mojibake_text",
        "bad_change_pct",
        "bad_alerts",
        "invalidated_alert_has_rows",
        "active_alert_without_trusted_source",
        "missing_alert_quote_audit",
        "missing_alert_quote_audit_field",
        "bad_alert_quote_audit",
        "alert_quote_not_cross_verified",
        "impossible_alert_pct",
    }:
        return "blocking", "禁止作为交易依据，需修复后重产"
    if code == "invalidated_source" or re.search(r"污染|撤下|invalidated", text, re.I):
        return "blocking", "对应信号等待重产，页面必须显示阻断"
    if code in {
        "source_degraded",
        "source_failed",
        "future_timestamp",
        "watchlist_extreme_change",
        "watchlist_limit_down_like",
        "label_pct_conflict",
        "strength_pct_conflict",
        "weakness_pct_conflict",
        "stock_pct_cross_file_conflict",
        "stock_direction_cross_file_conflict",
        "stock_limit_cross_file_conflict",
        "suspicious_alert_pct",
        "bad_alert_leader_pct",
        "alert_quote_audit_mismatch",
    } or re.search(r"decode|行情|涨跌幅|quote|akshare|source", text, re.I):
        return "price_review", "价格/涨跌幅相关结论降权，需二次行情源复核"
    if code in {
        "missing_quality_flags",
        "opportunity_not_downgraded",
        "high_confidence_without_evidence",
        "missing_observation_coverage",
        "missing_observation_coverage_field",
        "missing_observation_field",
        "missing_decision_brief",
        "missing_decision_brief_field",
        "schema_contract_missing",
        "schema_contract_type",
    }:
        return "signal_review", "机会信号必须降权并转入验证"
    return "background_review", "仅作背景复核，不单独阻断交易判断"


def bad_literal_label(literal: str) -> str:
    return {
        "[object Object]": "对象被直接显示",
        "undefined": "未定义值被直接显示",
        "None%": "空值百分比被直接显示",
        "NaN": "非数字值被直接显示",
        "Infinity": "无限大数值被直接显示",
    }.get(literal, "异常字面量")


def overall_status(issues: list[dict[str, Any]]) -> str:
    if any(item["severity"] == "critical" for item in issues):
        return "critical"
    if any(item["severity"] == "warning" for item in issues):
        return "degraded"
    return "ok"


def summarize(status: str, issues: list[dict[str, Any]]) -> str:
    critical = sum(1 for item in issues if item["severity"] == "critical")
    warning = sum(1 for item in issues if item["severity"] == "warning")
    info = sum(1 for item in issues if item["severity"] == "info")
    blocking = sum(1 for item in issues if item.get("impact_level") == "blocking")
    price_review = sum(1 for item in issues if item.get("impact_level") == "price_review")
    signal_review = sum(1 for item in issues if item.get("impact_level") == "signal_review")
    background = sum(1 for item in issues if item.get("impact_level") == "background_review")
    if status == "critical":
        return f"发现 {critical} 个严重数据问题，信号不得直接用于交易判断。"
    if status == "degraded":
        parts = []
        if blocking:
            parts.append(f"{blocking} 个交易阻断")
        if price_review:
            parts.append(f"{price_review} 个价格/行情复核")
        if signal_review:
            parts.append(f"{signal_review} 个信号复核")
        if background:
            parts.append(f"{background} 个背景复核")
        return f"发现 {warning} 个降级/需复核项（{'，'.join(parts) or '需复核'}），核心结论可看但必须按影响分层使用。"
    return f"数据结构检查通过，仅有 {info} 个提示项。"


def now_iso() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

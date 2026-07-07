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

        if isinstance(data, dict) and data.get("source_status") == "invalidated":
            issues.append(issue("warning", name, "invalidated_source", data.get("note", "数据批次已撤下")))

        scan_change_pct(name, data, watch_names, issues)

    validate_postmarket(files.get("postmarket.json"), issues)
    validate_evening(files.get("evening-sentiment.json"), issues, current_date)
    validate_source_health(files.get("source-health.json"), issues)
    validate_automation_health(files.get("automation-health.json"), issues, current_date)
    validate_theme_shifts(files.get("theme-shifts.json"), issues, current_date)
    validate_decision_feed(files.get("decision-feed.json"), issues, current_date)
    validate_data_trust(files.get("data-trust.json"), issues, current_date)
    validate_monitoring_coverage(files.get("monitoring-coverage.json"), issues, current_date)

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
        },
        "rules": [
            "异常文本、JSON解析失败、必需文件缺失为 critical。",
            "当日核心文件时间戳不一致、数据源降级、alert污染撤下为 warning。",
            "晚间舆情过期只标 info；前端不得把非当日晚间舆情用于今日总控。",
            "观察池个股出现异常涨跌幅时进入 warning，必须回查行情源。",
            "涨停/跌停/强势/弱势等标签必须与 change_pct 方向一致，冲突时进入 warning。",
            "decision-feed 如存在，机会/风险/验证项必须带标题、结论、置信度和来源文件。",
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
        if status in {"degraded", "bad"}:
            issues.append(issue("warning", "source-health.json", "source_degraded", f"{name}: {source.get('note') or source.get('detail') or source.get('usage') or status}"))


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
    for section in ("opportunities", "risks", "verifications"):
        rows = data.get(section)
        if not isinstance(rows, list):
            issues.append(issue("warning", "decision-feed.json", "missing_decision_section", f"{section} 缺失或不是数组"))
            continue
        for index, item in enumerate(rows):
            if not isinstance(item, dict):
                issues.append(issue("critical", "decision-feed.json", "bad_decision_item", f"{section}[{index}] 不是对象", section))
                continue
            for key in ("title", "conclusion", "confidence", "source_files"):
                if not item.get(key):
                    issues.append(issue("warning", "decision-feed.json", "missing_decision_field", f"{section}[{index}].{key} 缺失", f"{section}[{index}]"))
            for key in ("signal_grade", "signal_score", "use_action", "use_reasons", "discovery_type", "evidence_score"):
                if item.get(key) in (None, "", []):
                    issues.append(issue("warning", "decision-feed.json", "missing_usability_field", f"{section}[{index}].{key} 缺失", f"{section}[{index}]"))
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
        if item.get("freshness_status") not in (None, "fresh", "aging", "stale", "unknown", "phase_expired", "blocked"):
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
    return {
        "severity": severity,
        "file": file,
        "path": path,
        "code": code,
        "message": message,
    }


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
    if status == "critical":
        return f"发现 {critical} 个严重数据问题，信号不得直接用于交易判断。"
    if status == "degraded":
        return f"发现 {warning} 个降级/需复核项，核心结论可看但必须降权。"
    return f"数据结构检查通过，仅有 {info} 个提示项。"


def now_iso() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

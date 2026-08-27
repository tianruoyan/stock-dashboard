#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "smoke-report.json"
TZ = timezone(timedelta(hours=8))
BAD_LITERALS = ("[object Object]", "undefined", "None%", "NaN", "Infinity")
MOJIBAKE_PATTERN = re.compile(r"[�ÃÂ]|(?:æ|å|ç|è|é)[A-Za-z0-9_\- ]{0,8}")
OPTIONAL_FILES = {"data/signal-review.json"}
CRITICAL_IDS = {
    "status",
    "lastUpdate",
    "dashboard-control",
    "watchlist-decision",
    "alerts",
    "intraday-analysis",
    "intraday-indices",
    "premarket",
    "midday",
    "postmarket",
    "evening",
    "topics",
}
GENERIC_OPPORTUNITY_TITLES = {"强逻辑", "观察线", "资金博弈线", "风险线"}


def main() -> int:
    issues: list[dict[str, Any]] = []
    index = read_text(ROOT / "index.html")
    app = read_text(ROOT / "app.js")

    check_node_syntax(issues)
    check_index_contract(index, issues)
    check_app_files(app, issues)
    check_bad_literals(issues)
    check_build_report(issues)
    check_quality_report(issues)
    check_automation_health(issues)
    check_theme_shifts(issues)
    check_decision_feed(issues)
    check_alert_quote_audit(issues)
    check_data_trust(issues)
    check_monitoring_coverage(issues)
    check_section_health(issues, index, app)

    status = overall_status(issues)
    report = {
        "timestamp": now_iso(),
        "status": status,
        "summary": summarize(status, issues),
        "issues": issues,
        "checks": [
            "index.html 关键容器和导航锚点存在。",
            "style.css/app.js 缓存版本一致。",
            "app.js 语法检查通过。",
            "FILES 列出的必需 JSON/配置文件存在。",
            "data/config/settings 文件不含常见坏字面量。",
            "decision-feed 不含泛化机会、旧相对日期和高置信无证据项。",
            "非空 alert.json 必须带 quote_audit，声明行情源、quote_time、涨跌幅字段和交叉验证。",
            "data-trust 文件级可信度结构完整，能标记不可用/降权数据文件。",
            "monitoring-coverage 能说明监测盲区、影响决策和替代观察动作。",
            "section-health 区块矩阵结构完整，能指出不可用/降权区块。",
            "section-health 每个区块能映射到页面面板，并由前端贴状态条。",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{status}: {report['summary']}")
    return 1 if status == "critical" else 0


def check_node_syntax(issues: list[dict[str, Any]]) -> None:
    node = ROOT.parent / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node"
    if not node.exists():
        node = Path("/Users/sweet_orange/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
    try:
        result = subprocess.run([str(node), "--check", str(ROOT / "app.js")], capture_output=True, text=True, timeout=10)
    except Exception as exc:
        issues.append(issue("warning", "app.js", "node_check_unavailable", f"无法运行 JS 语法检查：{exc}"))
        return
    if result.returncode != 0:
        issues.append(issue("critical", "app.js", "js_syntax_error", (result.stderr or result.stdout).strip()))


def check_index_contract(index: str, issues: list[dict[str, Any]]) -> None:
    ids = set(re.findall(r'id="([^"]+)"', index))
    for target in sorted(CRITICAL_IDS - ids):
        issues.append(issue("critical", "index.html", "missing_dom_target", f"关键容器缺失：#{target}"))

    hrefs = re.findall(r'href="#([^"]+)"', index)
    for target in hrefs:
        if target not in ids:
            issues.append(issue("critical", "index.html", "broken_anchor", f"导航锚点不存在：#{target}"))

    style_version = first_match(index, r'style\.css\?v=([^"]+)')
    app_version = first_match(index, r'app\.js\?v=([^"]+)')
    if not style_version or not app_version:
        issues.append(issue("warning", "index.html", "missing_cache_version", "CSS 或 JS 缺少缓存版本"))
    elif style_version != app_version:
        issues.append(issue("warning", "index.html", "cache_version_mismatch", f"CSS={style_version}, JS={app_version}"))


def check_app_files(app: str, issues: list[dict[str, Any]]) -> None:
    match = re.search(r"const FILES = \[(.*?)\];", app, re.S)
    if not match:
        issues.append(issue("critical", "app.js", "missing_files_manifest", "找不到 FILES 清单"))
        return
    paths = re.findall(r'"([^"]+)"', match.group(1))
    for rel in paths:
        path = ROOT / rel
        if not path.exists() and rel not in OPTIONAL_FILES:
            issues.append(issue("critical", "app.js", "missing_manifest_file", f"FILES 中的文件不存在：{rel}"))
    if "data/decision-feed.json" not in paths:
        issues.append(issue("warning", "app.js", "decision_feed_not_loaded", "FILES 未加载 data/decision-feed.json"))
    if "data/theme-shifts.json" not in paths:
        issues.append(issue("warning", "app.js", "theme_shifts_not_loaded", "FILES 未加载 data/theme-shifts.json"))
    if "data/opportunity-watch.json" not in paths:
        issues.append(issue("warning", "app.js", "opportunity_watch_not_loaded", "FILES 未加载 data/opportunity-watch.json"))
    if "data/automation-health.json" not in paths:
        issues.append(issue("warning", "app.js", "automation_health_not_loaded", "FILES 未加载 data/automation-health.json"))


def check_bad_literals(issues: list[dict[str, Any]]) -> None:
    for folder in ("data", "config"):
        for path in sorted((ROOT / folder).glob("*.json")):
            text = read_text(path)
            for literal in BAD_LITERALS:
                if literal in text:
                    issues.append(issue("critical", rel(path), "bad_literal", f"发现异常文本：{bad_literal_label(literal)}"))
            if MOJIBAKE_PATTERN.search(text):
                issues.append(issue("critical", rel(path), "mojibake_text", "发现疑似乱码文本，需先清理数据源编码"))
            try:
                json.loads(text)
            except Exception as exc:
                issues.append(issue("critical", rel(path), "bad_json", f"JSON 解析失败：{exc}"))
    for path in (ROOT / "settings.html", ROOT / "settings.js", ROOT / "rules.html"):
        text = read_text(path)
        for literal in BAD_LITERALS:
            if literal in text:
                issues.append(issue("critical", rel(path), "bad_literal", f"发现异常文本：{bad_literal_label(literal)}"))
        if MOJIBAKE_PATTERN.search(text):
            issues.append(issue("critical", rel(path), "mojibake_text", "发现疑似乱码文本，需先清理页面文本"))


def check_decision_feed(issues: list[dict[str, Any]]) -> None:
    path = ROOT / "data" / "decision-feed.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(issue("critical", "data/decision-feed.json", "bad_json", f"决策流不可读：{exc}"))
        return
    current_date = data.get("current_signal_date") or signal_date(data.get("timestamp"))
    quality_status = ((data.get("quality_gate") or {}).get("status") or "").strip()
    coverage = data.get("observation_coverage")
    if not isinstance(coverage, dict):
        issues.append(issue("warning", "data/decision-feed.json", "missing_observation_coverage", "decision-feed 缺少 observation_coverage"))
    else:
        for key in ("summary", "independent_count", "active_market_count", "topic_inherited_count", "status"):
            if coverage.get(key) in (None, "", []):
                issues.append(issue("warning", "data/decision-feed.json", "missing_observation_coverage_field", f"observation_coverage.{key} 缺失"))
    brief = data.get("decision_brief")
    if not isinstance(brief, dict):
        issues.append(issue("warning", "data/decision-feed.json", "missing_decision_brief", "decision-feed 缺少 decision_brief"))
    else:
        for key in ("stance", "action", "reasons", "risk_focus", "upgrade_watch"):
            if key not in brief:
                issues.append(issue("warning", "data/decision-feed.json", "missing_decision_brief_field", f"decision_brief.{key} 缺失"))
        if quality_status in {"degraded", "critical"}:
            actions = brief.get("quality_actions")
            if not isinstance(actions, list) or not actions:
                issues.append(issue("warning", "data/decision-feed.json", "missing_decision_brief_quality_actions", "数据降级时 decision_brief 必须带 quality_actions"))
            else:
                for index, action in enumerate(actions[:2]):
                    if not isinstance(action, dict):
                        issues.append(issue("warning", "data/decision-feed.json", "bad_decision_brief_quality_action", f"quality_actions[{index}] 不是对象"))
                        continue
                    for key in ("label", "file", "next_step"):
                        if not action.get(key):
                            issues.append(issue("warning", "data/decision-feed.json", "missing_decision_brief_quality_action_field", f"quality_actions[{index}].{key} 缺失"))
    queue = data.get("signal_queue")
    if not isinstance(queue, dict):
        issues.append(issue("warning", "data/decision-feed.json", "missing_signal_queue", "decision-feed 缺少 signal_queue"))
    else:
        for key in ("summary", "active_opportunities", "trackable_risks", "verification_queue", "disabled_signals"):
            if key not in queue:
                issues.append(issue("warning", "data/decision-feed.json", "missing_signal_queue_field", f"signal_queue.{key} 缺失"))
        for key in ("active_opportunities", "trackable_risks", "verification_queue", "disabled_signals"):
            if key in queue and not isinstance(queue.get(key), list):
                issues.append(issue("warning", "data/decision-feed.json", "bad_signal_queue_field", f"signal_queue.{key} 不是数组"))
    for section in ("opportunities", "risks", "verifications"):
        rows = data.get(section)
        if not isinstance(rows, list):
            issues.append(issue("critical", "data/decision-feed.json", "bad_section", f"{section} 不是数组"))
            continue
        for index, item in enumerate(rows):
            if not isinstance(item, dict):
                issues.append(issue("critical", "data/decision-feed.json", "bad_item", f"{section}[{index}] 不是对象"))
                continue
            title = str(item.get("title") or "")
            text = json.dumps(item, ensure_ascii=False)
            if section == "opportunities" and title in GENERIC_OPPORTUNITY_TITLES:
                issues.append(issue("warning", "data/decision-feed.json", "generic_opportunity", f"机会栏含泛化分类桶：{title}"))
            if section == "opportunities" and has_stale_relative_time(text, current_date):
                issues.append(issue("warning", "data/decision-feed.json", "stale_relative_time", f"机会栏含过期相对日期：{title}"))
            if section == "opportunities" and quality_status in {"degraded", "critical"}:
                if not item.get("quality_flags"):
                    issues.append(issue("warning", "data/decision-feed.json", "missing_quality_flags", f"数据降级但机会缺少降权原因：{title}"))
                if item.get("confidence") in {"medium", "high"}:
                    issues.append(issue("warning", "data/decision-feed.json", "opportunity_not_downgraded", f"数据降级但机会置信度未降权：{title}"))
            if section in {"opportunities", "risks"} and item.get("confidence") == "high" and not item.get("evidence"):
                issues.append(issue("warning", "data/decision-feed.json", "high_confidence_without_evidence", f"{title} 高置信但缺少证据"))
            if section in {"opportunities", "risks"} and not item.get("source_files"):
                issues.append(issue("warning", "data/decision-feed.json", "missing_source", f"{title} 缺少来源文件"))
            if not item.get("trigger_reason"):
                issues.append(issue("warning", "data/decision-feed.json", "missing_trigger_reason", f"{title} 缺少触发原因"))
            for key in ("signal_grade", "signal_score", "use_action", "use_reasons", "discovery_type", "evidence_score", "next_action"):
                if item.get(key) in (None, "", []):
                    issues.append(issue("warning", "data/decision-feed.json", "missing_usability_field", f"{title} 缺少 {key}"))
            for key in ("observation_source", "independent_observation"):
                if key not in item:
                    issues.append(issue("warning", "data/decision-feed.json", "missing_observation_field", f"{title} 缺少 {key}"))
            if section == "opportunities":
                for key in ("upgrade_rank", "upgrade_priority", "upgrade_condition"):
                    if item.get(key) in (None, "", []):
                        issues.append(issue("warning", "data/decision-feed.json", "missing_upgrade_field", f"{title} 缺少 {key}"))
            if "missing_evidence" not in item or not isinstance(item.get("missing_evidence"), list):
                issues.append(issue("warning", "data/decision-feed.json", "missing_usability_field", f"{title} 缺少 missing_evidence 数组"))
            if item.get("signal_grade") not in (None, "A", "B", "C", "D"):
                issues.append(issue("warning", "data/decision-feed.json", "bad_signal_grade", f"{title} signal_grade 非 A/B/C/D"))
            if isinstance(item.get("evidence_score"), (int, float)) and not 0 <= item.get("evidence_score") <= 100:
                issues.append(issue("warning", "data/decision-feed.json", "bad_evidence_score", f"{title} evidence_score 不在 0-100"))
            if section == "opportunities" and isinstance(item.get("upgrade_rank"), int) and item.get("upgrade_rank") <= 0:
                issues.append(issue("warning", "data/decision-feed.json", "bad_upgrade_rank", f"{title} upgrade_rank 必须为正整数"))
    check_decision_conflicts(data, issues)
    check_postmarket_risk_hotspots(data, issues)
    check_unplanned_theme_detection(data, issues)


def check_postmarket_risk_hotspots(feed: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    try:
        postmarket = json.loads((ROOT / "data" / "postmarket.json").read_text(encoding="utf-8"))
    except Exception:
        return
    rendered = {
        normalize_conflict_title(item.get("title"))
        for item in (feed.get("risks") or []) + (feed.get("verifications") or [])
        if isinstance(item, dict)
    }
    rendered.update(
        normalize_conflict_title(item.get("theme"))
        for item in feed.get("conflicts") or []
        if isinstance(item, dict)
    )
    for item in postmarket.get("hotspots", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        text = json.dumps(item, ensure_ascii=False)
        if not re.search(r"风险|分歧|退潮|反抽失败|弱|回落|炸板|跌停|不支持全面进攻", text):
            continue
        key = normalize_conflict_title(name)
        if key and key not in rendered:
            issues.append(issue("warning", "data/decision-feed.json", "missing_postmarket_risk_hotspot", f"盘后风险热点未进入风险/验证/冲突栏：{name}"))


def check_decision_conflicts(feed: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    conflicts = feed.get("conflicts")
    if not isinstance(conflicts, list):
        issues.append(issue("warning", "data/decision-feed.json", "missing_conflicts", "decision-feed 缺少 conflicts 数组"))
        return
    expected = expected_conflict_titles(feed)
    actual = {str(item.get("theme") or "") for item in conflicts if isinstance(item, dict)}
    for theme in expected[:5]:
        if theme not in actual:
            issues.append(issue("warning", "data/decision-feed.json", "missing_signal_conflict", f"同一主线多空信号未进入冲突校验：{theme}"))
    for index, item in enumerate(conflicts):
        if not isinstance(item, dict):
            issues.append(issue("warning", "data/decision-feed.json", "bad_conflict", f"conflicts[{index}] 不是对象"))
            continue
        for key in ("theme", "sections", "verdict", "severity", "action", "evidence"):
            if item.get(key) in (None, "", []):
                issues.append(issue("warning", "data/decision-feed.json", "missing_conflict_field", f"conflicts[{index}].{key} 缺失"))


def expected_conflict_titles(feed: dict[str, Any]) -> list[str]:
    buckets: dict[str, set[str]] = {}
    for section in ("opportunities", "risks", "verifications"):
        for item in feed.get(section) or []:
            if not isinstance(item, dict):
                continue
            key = normalize_conflict_title(item.get("title"))
            if key:
                buckets.setdefault(key, set()).add(section)
    return [key for key, sections in buckets.items() if len(sections) >= 2]


def normalize_conflict_title(title: Any) -> str:
    text = re.sub(r"^(主线变化：|新线观察：)", "", str(title or "").strip())
    text = re.sub(r"(候选验证|验证)$", "", text).strip()
    aliases = {
        "半导体设备": "科技硬件链",
        "半导体材料": "科技硬件链",
        "半导体零部件": "科技硬件链",
        "创新药/CRO": "医药修复链",
    }
    return aliases.get(text, text)


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


def trading_phase(now: datetime) -> str:
    hhmm = now.hour * 100 + now.minute
    if 830 <= hhmm < 930:
        return "premarket"
    if 930 <= hhmm < 1130:
        return "morning"
    if 1130 <= hhmm < 1300:
        return "midday"
    if 1300 <= hhmm < 1500:
        return "afternoon"
    if 1500 <= hhmm < 2000:
        return "postmarket"
    if hhmm >= 2000:
        return "evening"
    return "overnight"


def check_alert_quote_audit(issues: list[dict[str, Any]]) -> None:
    path = ROOT / "data" / "alert.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(issue("critical", "data/alert.json", "bad_json", f"盘中异动不可读：{exc}"))
        return
    alerts = data.get("alerts")
    if alerts in (None, []):
        return
    if not isinstance(alerts, list):
        issues.append(issue("critical", "data/alert.json", "bad_alerts", "alerts 必须是数组"))
        return
    trade_gate = alert_requires_trade_gate(data, alerts)
    audit = data.get("quote_audit")
    if not isinstance(audit, dict):
        issues.append(issue("critical" if trade_gate else "warning", "data/alert.json", "missing_quote_audit", "当前盘中新鲜 alerts 必须带 quote_audit；历史/过期 alerts 只降权参考"))
        return
    for key in ("provider", "quote_time", "pct_field", "sanity_checks"):
        if audit.get(key) in (None, "", []):
            issues.append(issue("critical" if trade_gate else "warning", "data/alert.json", "missing_quote_audit_field", f"quote_audit.{key} 缺失"))
    sanity = audit.get("sanity_checks") or {}
    if not isinstance(sanity, dict):
        issues.append(issue("critical" if trade_gate else "warning", "data/alert.json", "bad_quote_audit", "quote_audit.sanity_checks 必须是对象"))
        return
    group_metric = audit.get("metric_scope") in {"theme_pool", "sector"} or bool(re.search(r"底池|题材|板块", str(audit.get("pct_field") or "")))
    magnitude_key = "max_abs_trigger_change_pct" if group_metric else "max_abs_leader_change_pct"
    for key in ("sample_count", magnitude_key, "cross_source_verified"):
        if sanity.get(key) in (None, "", []):
            issues.append(issue("critical" if trade_gate else "warning", "data/alert.json", "missing_quote_audit_field", f"quote_audit.sanity_checks.{key} 缺失"))


def alert_requires_trade_gate(data: dict[str, Any], alerts: list[Any]) -> bool:
    now = datetime.now(TZ)
    phase = trading_phase(now)
    if phase not in {"morning", "afternoon"}:
        return False
    confirmed = [
        item for item in alerts
        if isinstance(item, dict)
        and item.get("confirmation_level") not in {"candidate", "invalidated"}
    ]
    if not confirmed:
        return False
    latest = latest_alert_event_time(data, confirmed, now)
    if latest is None:
        return True
    age_seconds = (now - latest).total_seconds()
    return 0 <= age_seconds <= 5 * 60


def latest_alert_event_time(data: dict[str, Any], alerts: list[Any], now: datetime) -> datetime | None:
    base = parse_timestamp(data.get("timestamp")) or now
    candidates: list[datetime] = []
    for item in alerts:
        if not isinstance(item, dict):
            continue
        raw_time = str(item.get("time") or "")
        parsed = parse_timestamp(raw_time)
        if parsed:
            candidates.append(parsed)
            continue
        match = re.match(r"^(\d{2}):(\d{2})(?::(\d{2}))?$", raw_time)
        if match:
            candidates.append(base.replace(
                hour=int(match.group(1)),
                minute=int(match.group(2)),
                second=int(match.group(3) or 0),
                microsecond=0,
            ))
    return max(candidates) if candidates else None


def check_unplanned_theme_detection(feed: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    postmarket_path = ROOT / "data" / "postmarket.json"
    topics_path = ROOT / "data" / "topics.json"
    try:
        postmarket = json.loads(postmarket_path.read_text(encoding="utf-8"))
        topics = json.loads(topics_path.read_text(encoding="utf-8"))
    except Exception:
        return
    known = {str(item.get("name") or "") for item in topics.get("topics", []) if isinstance(item, dict)}
    expected = []
    for item in postmarket.get("hotspots", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        state_text = " ".join(str(item.get(key) or "") for key in ("name", "status", "continuity", "note"))
        text = json.dumps(item, ensure_ascii=False)
        if name in known:
            continue
        if re.search(r"风险线|弱化|退潮|反抽失败|证伪", state_text):
            continue
        if re.search(r"低位|消费电子|元件|首次|轮动增强", state_text) and re.search(r"涨停池|8%以上|5%-8%|封板|涨停|轮动增强|低位轮动|强势组", text):
            expected.append(name)
    if not expected:
        return
    rendered = {
        str(item.get("title") or "")
        for item in (feed.get("opportunities") or []) + (feed.get("risks") or []) + (feed.get("verifications") or [])
        if isinstance(item, dict)
    }
    for name in expected[:3]:
        if not any(name in title for title in rendered):
            issues.append(issue("warning", "data/decision-feed.json", "missing_unplanned_theme_scan", f"非预设活跃方向未进入雷达：{name}"))


def check_build_report(issues: list[dict[str, Any]]) -> None:
    path = ROOT / "data" / "build-report.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(issue("warning", "data/build-report.json", "build_report_missing", f"统一构建报告不可读：{exc}"))
        return
    rows = data.get("steps")
    if not isinstance(rows, list) or not rows:
        issues.append(issue("warning", "data/build-report.json", "bad_build_report", "steps 缺失或为空"))
        return
    if data.get("status") == "running":
        return
    names = {item.get("name") for item in rows if isinstance(item, dict)}
    required = {"opportunity-watch:pre", "theme-shifts:pre", "decision-feed:pre", "automation-health:pre", "audit", "opportunity-watch:post-audit", "automation-health:post-audit", "data-trust", "monitoring-coverage", "section-health", "static-smoke", "runtime-smoke"}
    missing = sorted(required - names)
    if missing:
        issues.append(issue("warning", "data/build-report.json", "missing_build_steps", f"统一构建缺少步骤：{', '.join(missing)}"))
    for item in rows:
        if not isinstance(item, dict):
            continue
        if item.get("returncode") not in (0, None) or item.get("status") == "script_error":
            message = item.get("stderr_tail") or item.get("stdout_tail") or "构建步骤异常"
            severity = "critical" if item.get("gates_publish", True) else "warning"
            code = "build_step_error" if severity == "critical" else "non_blocking_build_step_error"
            issues.append(issue(severity, "data/build-report.json", code, f"{item.get('name')} 执行异常：{message}"))
    if data.get("status") == "blocked":
        issues.append(issue("warning", "data/build-report.json", "previous_build_blocked", data.get("summary") or "上一次统一构建阻断发布，本次构建以当前步骤结果为准"))


def check_quality_report(issues: list[dict[str, Any]]) -> None:
    path = ROOT / "data" / "quality-report.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(issue("warning", "data/quality-report.json", "quality_report_missing", f"数据审计报告不可读：{exc}"))
        return
    rows = data.get("issues")
    if not isinstance(rows, list):
        issues.append(issue("warning", "data/quality-report.json", "bad_quality_issues", "issues 缺失或不是数组"))
        return
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            issues.append(issue("warning", "data/quality-report.json", "bad_quality_issue", f"issues[{index}] 不是对象"))
            continue
        if item.get("impact_level") not in {"blocking", "price_review", "signal_review", "background_review"}:
            issues.append(issue("warning", "data/quality-report.json", "missing_issue_impact", f"issues[{index}] 缺少有效 impact_level"))
        if not item.get("decision_action"):
            issues.append(issue("warning", "data/quality-report.json", "missing_issue_action", f"issues[{index}] 缺少 decision_action"))
    counts = data.get("counts") or {}
    for key in ("blocking", "price_review", "signal_review", "background_review"):
        if key not in counts:
            issues.append(issue("warning", "data/quality-report.json", "missing_impact_count", f"counts.{key} 缺失"))
    plan = data.get("action_plan")
    if not isinstance(plan, list):
        issues.append(issue("warning", "data/quality-report.json", "missing_action_plan", "action_plan 缺失或不是数组"))
    else:
        for index, item in enumerate(plan[:4]):
            if not isinstance(item, dict):
                issues.append(issue("warning", "data/quality-report.json", "bad_action_plan_item", f"action_plan[{index}] 不是对象"))
                continue
            for key in ("label", "file", "next_step", "unblock_condition", "impact_level"):
                if item.get(key) in (None, "", []):
                    issues.append(issue("warning", "data/quality-report.json", "missing_action_plan_field", f"action_plan[{index}].{key} 缺失"))


def check_theme_shifts(issues: list[dict[str, Any]]) -> None:
    path = ROOT / "data" / "theme-shifts.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(issue("warning", "data/theme-shifts.json", "theme_shifts_missing", f"主线变化报告不可读：{exc}"))
        return
    rows = data.get("shifts")
    if not isinstance(rows, list):
        issues.append(issue("warning", "data/theme-shifts.json", "bad_theme_shifts", "shifts 缺失或不是数组"))
        return
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            issues.append(issue("warning", "data/theme-shifts.json", "bad_shift_item", f"shifts[{index}] 不是对象"))
            continue
        for key in ("theme", "state", "score", "conclusion", "evidence", "watch_next", "source_files"):
            if item.get(key) in (None, "", []):
                issues.append(issue("warning", "data/theme-shifts.json", "missing_shift_field", f"shifts[{index}].{key} 缺失"))
        if item.get("state") not in {"warming", "emerging", "crowded", "fading", "risk", "watch"}:
            issues.append(issue("warning", "data/theme-shifts.json", "bad_shift_state", f"shifts[{index}].state 非法"))


def check_automation_health(issues: list[dict[str, Any]]) -> None:
    path = ROOT / "data" / "automation-health.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(issue("warning", "data/automation-health.json", "automation_health_missing", f"自动化心跳报告不可读：{exc}"))
        return
    rows = data.get("processes")
    if not isinstance(rows, list) or not rows:
        issues.append(issue("warning", "data/automation-health.json", "bad_automation_health", "processes 缺失或为空"))
        return
    readiness = data.get("next_session_readiness")
    if not isinstance(readiness, dict):
        issues.append(issue("warning", "data/automation-health.json", "missing_next_session_readiness", "自动化心跳缺少 next_session_readiness"))
    else:
        for key in ("target_trade_date", "status", "summary", "items"):
            if readiness.get(key) in (None, "", []):
                issues.append(issue("warning", "data/automation-health.json", "missing_next_session_readiness_field", f"next_session_readiness.{key} 缺失"))
        if readiness.get("status") not in {"ready", "pending", "overdue"}:
            issues.append(issue("warning", "data/automation-health.json", "bad_next_session_status", "next_session_readiness.status 非法"))
        if not isinstance(readiness.get("items"), list):
            issues.append(issue("warning", "data/automation-health.json", "bad_next_session_items", "next_session_readiness.items 不是数组"))
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            issues.append(issue("warning", "data/automation-health.json", "bad_process_item", f"processes[{index}] 不是对象"))
            continue
        for key in ("id", "label", "file", "due", "status", "action", "reason", "failure_type", "diagnosis", "next_actions"):
            if item.get(key) in (None, "", []):
                issues.append(issue("warning", "data/automation-health.json", "missing_process_field", f"processes[{index}].{key} 缺失"))
        if "related_sources" not in item or not isinstance(item.get("related_sources"), list):
            issues.append(issue("warning", "data/automation-health.json", "missing_process_field", f"processes[{index}].related_sources 缺失或不是数组"))
        if item.get("status") not in {"ok", "waiting", "late", "missing", "invalidated"}:
            issues.append(issue("warning", "data/automation-health.json", "bad_process_status", f"processes[{index}].status 非法"))


def check_data_trust(issues: list[dict[str, Any]]) -> None:
    path = ROOT / "data" / "data-trust.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(issue("warning", "data/data-trust.json", "data_trust_missing", f"文件可信度报告不可读：{exc}"))
        return
    rows = data.get("files")
    if not isinstance(rows, list) or not rows:
        issues.append(issue("warning", "data/data-trust.json", "bad_data_trust", "files 缺失或为空"))
        return
    trust_date = data.get("current_signal_date")
    for rel in ("data/decision-feed.json", "data/quality-report.json"):
        try:
            other = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        except Exception:
            continue
        other_date = other.get("current_signal_date")
        if trust_date and other_date and trust_date != other_date:
            issues.append(issue("warning", "data/data-trust.json", "signal_date_mismatch", f"data-trust 交易日 {trust_date} 与 {rel} {other_date} 不一致"))
    required_files = {"data/alert.json", "data/intraday.json", "data/premarket.json", "data/midday.json", "data/postmarket.json", "data/topics.json", "data/opportunity-watch.json", "data/theme-shifts.json", "data/decision-feed.json"}
    present = {item.get("file") for item in rows if isinstance(item, dict)}
    missing = sorted(required_files - present)
    if missing:
        issues.append(issue("warning", "data/data-trust.json", "missing_trust_rows", f"缺少核心文件可信度：{', '.join(missing)}"))
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            issues.append(issue("warning", "data/data-trust.json", "bad_trust_item", f"files[{index}] 不是对象"))
            continue
        for key in ("file", "label", "status", "trust_score", "use_action", "reason", "session_phase", "session_relevance", "session_action", "session_reason", "freshness_status", "freshness_action", "freshness_reason", "freshness_minutes"):
            if item.get(key) in (None, "", []):
                issues.append(issue("warning", "data/data-trust.json", "missing_trust_field", f"files[{index}].{key} 缺失"))
        if item.get("status") not in {"trusted", "degraded", "stale", "invalidated", "missing"}:
            issues.append(issue("warning", "data/data-trust.json", "bad_trust_status", f"files[{index}].status 非法"))
        if item.get("session_relevance") not in {"current", "historical", "upcoming", "background", "blocked"}:
            issues.append(issue("warning", "data/data-trust.json", "bad_session_relevance", f"files[{index}].session_relevance 非法"))
        if item.get("freshness_status") not in {"fresh", "aging", "stale", "future", "unknown", "phase_expired", "blocked"}:
            issues.append(issue("warning", "data/data-trust.json", "bad_freshness_status", f"files[{index}].freshness_status 非法"))
        phase = item.get("session_phase")
        if item.get("file") == "data/postmarket.json" and phase in {"evening", "overnight", "premarket"}:
            if item.get("freshness_status") == "stale":
                issues.append(issue("warning", "data/data-trust.json", "postmarket_false_stale", "盘后复盘在晚间/隔夜/盘前阶段不应按 6 小时实时 SLA 误报超时"))
            if int(item.get("freshness_minutes") or 0) < 1080:
                issues.append(issue("warning", "data/data-trust.json", "postmarket_short_sla", "盘后复盘隔夜有效期应至少覆盖到次日盘前"))
        if item.get("file") == "data/decision-feed.json" and phase in {"evening", "overnight"} and item.get("session_relevance") == "historical":
            issues.append(issue("warning", "data/data-trust.json", "decision_feed_false_historical", "晚间/隔夜机会风险流应作为当前决策材料，而不是历史回看"))


def check_monitoring_coverage(issues: list[dict[str, Any]]) -> None:
    path = ROOT / "data" / "monitoring-coverage.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(issue("warning", "data/monitoring-coverage.json", "monitoring_coverage_missing", f"监测盲区报告不可读：{exc}"))
        return
    rows = data.get("blind_spots")
    if not isinstance(rows, list):
        issues.append(issue("warning", "data/monitoring-coverage.json", "bad_monitoring_coverage", "blind_spots 缺失或不是数组"))
        return
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            issues.append(issue("warning", "data/monitoring-coverage.json", "bad_blind_spot", f"blind_spots[{index}] 不是对象"))
            continue
        for key in ("id", "title", "severity", "conclusion", "impacted_decisions", "fallback_action", "source_files"):
            if item.get(key) in (None, "", []):
                issues.append(issue("warning", "data/monitoring-coverage.json", "missing_blind_spot_field", f"blind_spots[{index}].{key} 缺失"))
        if item.get("severity") == "critical" and item.get("fallback_checks") in (None, "", []):
            issues.append(issue("warning", "data/monitoring-coverage.json", "missing_fallback_checks", f"核心盲区缺少可执行 fallback_checks：{item.get('title') or index}"))
        if item.get("severity") not in {"critical", "warning", "info"}:
            issues.append(issue("warning", "data/monitoring-coverage.json", "bad_blind_spot_severity", f"blind_spots[{index}].severity 非法"))


def check_section_health(issues: list[dict[str, Any]], index: str, app: str) -> None:
    path = ROOT / "data" / "section-health.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(issue("warning", "data/section-health.json", "section_health_missing", f"区块健康矩阵不可读：{exc}"))
        return
    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        issues.append(issue("warning", "data/section-health.json", "bad_section_health", "sections 缺失或为空"))
        return
    required = {"control", "watchlist", "alerts", "intraday", "premarket", "midday", "postmarket", "evening", "topics"}
    present = {item.get("id") for item in sections if isinstance(item, dict)}
    missing = sorted(required - present)
    if missing:
        issues.append(issue("warning", "data/section-health.json", "missing_sections", f"区块健康缺少：{', '.join(missing)}"))
    dom_ids = set(re.findall(r'id="section-([^"]+)"', index))
    unmapped = sorted(section_id for section_id in present if section_id not in dom_ids)
    if unmapped:
        issues.append(issue("warning", "data/section-health.json", "unmapped_sections", f"区块健康无法映射到页面：{', '.join(unmapped)}"))
    if "renderSectionHealthBadges" not in app or "section-health-badge" not in app:
        issues.append(issue("warning", "app.js", "section_badge_not_rendered", "前端未渲染区块健康状态条"))
    for item in sections:
        if not isinstance(item, dict):
            continue
        if not item.get("status") or not item.get("label") or not isinstance(item.get("files"), list):
            issues.append(issue("warning", "data/section-health.json", "bad_section_item", f"{item.get('id') or 'unknown'} 字段不完整"))
    check_section_health_derived_dates(data, issues)


def check_section_health_derived_dates(section_health: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    current_date = section_health.get("current_signal_date") or ""
    derived = {"data/quality-report.json", "data/theme-shifts.json", "data/decision-feed.json", "data/data-trust.json"}
    if not current_date:
        return
    for section in section_health.get("sections") or []:
        if not isinstance(section, dict):
            continue
        reason = str(section.get("reason") or "")
        for row in section.get("files") or []:
            if not isinstance(row, dict) or row.get("file") not in derived:
                continue
            payload = read_json(ROOT / row["file"])
            if payload.get("current_signal_date") == current_date and row.get("status") == "stale":
                issues.append(issue(
                    "warning",
                    "data/section-health.json",
                    "derived_file_false_stale",
                    f"{section.get('label') or section.get('id')} 将派生报告 {row['file']} 误判为非当前交易日"
                ))
            if f"{row['file']} 非当前交易日" in reason and payload.get("current_signal_date") == current_date:
                issues.append(issue(
                    "warning",
                    "data/section-health.json",
                    "derived_file_timestamp_date_leak",
                    f"{section.get('label') or section.get('id')} 的原因仍使用派生报告生成日期判断交易日：{row['file']}"
                ))


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def has_stale_relative_time(text: str, current_date: str) -> bool:
    try:
        weekday = datetime.fromisoformat(str(current_date)).weekday()
    except Exception:
        return False
    weekday_words = {
        "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6, "周天": 6,
    }
    next_trading_weekday = 0 if weekday == 4 else weekday + 1
    allowed = {weekday, next_trading_weekday}
    return any(word in text and day not in allowed for word, day in weekday_words.items())


def signal_date(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


def issue(severity: str, file: str, code: str, message: str) -> dict[str, Any]:
    return {"severity": severity, "file": file, "code": code, "message": message}


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
        return "warning"
    return "ok"


def summarize(status: str, issues: list[dict[str, Any]]) -> str:
    critical = sum(1 for item in issues if item["severity"] == "critical")
    warning = sum(1 for item in issues if item["severity"] == "warning")
    if status == "critical":
        return f"发现 {critical} 个页面发布阻断问题。"
    if status == "warning":
        return f"发现 {warning} 个页面需复核项。"
    return "页面静态烟雾测试通过。"


def first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def now_iso() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

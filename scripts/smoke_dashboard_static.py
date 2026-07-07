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
    "data-quality-gate",
    "opportunity-risk-radar",
    "watchlist-decision",
    "portfolio-risk",
    "signal-review",
    "alerts",
    "intraday-decision",
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
    check_theme_shifts(issues)
    check_decision_feed(issues)
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
            for key in ("signal_grade", "signal_score", "use_action", "use_reasons", "discovery_type", "evidence_score"):
                if item.get(key) in (None, "", []):
                    issues.append(issue("warning", "data/decision-feed.json", "missing_usability_field", f"{title} 缺少 {key}"))
            if "missing_evidence" not in item or not isinstance(item.get("missing_evidence"), list):
                issues.append(issue("warning", "data/decision-feed.json", "missing_usability_field", f"{title} 缺少 missing_evidence 数组"))
            if item.get("signal_grade") not in (None, "A", "B", "C", "D"):
                issues.append(issue("warning", "data/decision-feed.json", "bad_signal_grade", f"{title} signal_grade 非 A/B/C/D"))
            if isinstance(item.get("evidence_score"), (int, float)) and not 0 <= item.get("evidence_score") <= 100:
                issues.append(issue("warning", "data/decision-feed.json", "bad_evidence_score", f"{title} evidence_score 不在 0-100"))


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
    required = {"theme-shifts:pre", "decision-feed:pre", "audit", "data-trust", "monitoring-coverage", "section-health", "static-smoke", "runtime-smoke"}
    missing = sorted(required - names)
    if missing:
        issues.append(issue("warning", "data/build-report.json", "missing_build_steps", f"统一构建缺少步骤：{', '.join(missing)}"))
    if data.get("status") == "blocked":
        issues.append(issue("critical", "data/build-report.json", "build_blocked", data.get("summary") or "统一构建阻断发布"))


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
    required_files = {"data/alert.json", "data/intraday.json", "data/premarket.json", "data/midday.json", "data/postmarket.json", "data/topics.json", "data/theme-shifts.json", "data/decision-feed.json"}
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
        if item.get("freshness_status") not in {"fresh", "aging", "stale", "unknown", "phase_expired", "blocked"}:
            issues.append(issue("warning", "data/data-trust.json", "bad_freshness_status", f"files[{index}].freshness_status 非法"))


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
    required = {"control", "radar", "watchlist", "risk", "alerts", "intraday", "premarket", "midday", "postmarket", "evening", "topics"}
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


def has_stale_relative_time(text: str, current_date: str) -> bool:
    try:
        weekday = datetime.fromisoformat(str(current_date)).weekday()
    except Exception:
        return False
    weekday_words = {
        "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6, "周天": 6,
    }
    return any(word in text and weekday != day for word, day in weekday_words.items())


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

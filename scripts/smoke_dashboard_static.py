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
    check_decision_feed(issues)
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


def check_bad_literals(issues: list[dict[str, Any]]) -> None:
    for folder in ("data", "config"):
        for path in sorted((ROOT / folder).glob("*.json")):
            text = read_text(path)
            for literal in BAD_LITERALS:
                if literal in text:
                    issues.append(issue("critical", rel(path), "bad_literal", f"发现异常文本 {literal}"))
            try:
                json.loads(text)
            except Exception as exc:
                issues.append(issue("critical", rel(path), "bad_json", f"JSON 解析失败：{exc}"))
    for path in (ROOT / "settings.html", ROOT / "settings.js", ROOT / "rules.html"):
        text = read_text(path)
        for literal in BAD_LITERALS:
            if literal in text:
                issues.append(issue("critical", rel(path), "bad_literal", f"发现异常文本 {literal}"))


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

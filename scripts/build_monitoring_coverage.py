#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "monitoring-coverage.json"
TZ = timezone(timedelta(hours=8))


def main() -> int:
    data_trust = load_json(DATA_DIR / "data-trust.json")
    source_health = load_json(DATA_DIR / "source-health.json")
    decision_feed = load_json(DATA_DIR / "decision-feed.json")
    trust_by_file = {
        row.get("file"): row
        for row in data_trust.get("files", [])
        if isinstance(row, dict)
    }
    blind_spots = build_blind_spots(trust_by_file, source_health, decision_feed)
    counts = {
        "critical": sum(1 for item in blind_spots if item["severity"] == "critical"),
        "warning": sum(1 for item in blind_spots if item["severity"] == "warning"),
        "info": sum(1 for item in blind_spots if item["severity"] == "info"),
    }
    report = {
        "timestamp": now_iso(),
        "current_signal_date": data_trust.get("current_signal_date") or signal_date(data_trust.get("timestamp")),
        "overall_status": "blind_spot" if counts["critical"] else ("degraded" if counts["warning"] else "covered"),
        "summary": summarize(blind_spots),
        "counts": counts,
        "blind_spots": blind_spots,
        "rules": [
            "critical：核心监测断点，不能依赖对应自动提醒做盘中决策。",
            "warning：信号可看但必须降权，需要等待二次验证。",
            "info：不影响当前盘中主流程，但会影响背景判断。",
            "盲区必须说明影响什么决策、暂用什么替代观察。"
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"monitoring-coverage: {report['overall_status']} - {report['summary']}")
    return 0


def build_blind_spots(trust: dict[str, dict[str, Any]], source_health: dict[str, Any], decision_feed: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    alert = trust.get("data/alert.json") or {}
    intraday = trust.get("data/intraday.json") or {}
    premarket = trust.get("data/premarket.json") or {}
    postmarket = trust.get("data/postmarket.json") or {}
    evening = trust.get("data/evening-sentiment.json") or {}
    decision = trust.get("data/decision-feed.json") or {}
    postmarket_data = load_json(DATA_DIR / "postmarket.json")
    intraday_data = load_json(DATA_DIR / "intraday.json")
    decision_data = load_json(DATA_DIR / "decision-feed.json")

    if alert.get("status") in {"invalidated", "missing"}:
        rows.append(blind_spot(
            "intraday-alert-trigger",
            "盘中异动触发盲区",
            "critical",
            "3分钟急拉/急跌、成交放大、板块同向扩散和观察池个股突破/跌破可能漏报。",
            ["盘中异动卡不能作为买卖触发依据", "观察池高频强弱切换可能滞后", "新题材第一次扩散可能需要人工从盘中全景确认"],
            [alert.get("reason") or "alert 文件不可用"],
            "不要依赖异动提醒；改看盘中全景、涨跌停池、专题/观察池静态结论，并等待修复后重产 alert。",
            ["data/alert.json", "data/data-trust.json"],
            fallback_checks=alert_fallback_checks(postmarket_data, intraday_data, decision_data)
        ))
    elif alert.get("status") == "degraded":
        rows.append(blind_spot(
            "intraday-alert-degraded",
            "盘中异动触发降权",
            "warning",
            "异动信号可参考，但触发价格/涨跌幅需要二次核验。",
            ["交易信号不能直接执行", "同题材连续触发需要看原始行情源确认"],
            [alert.get("reason") or "alert 文件降权"],
            "只把 alert 当成线索，必须结合指数、板块宽度和个股原始报价确认。",
            ["data/alert.json", "data/data-trust.json"],
            fallback_checks=alert_fallback_checks(postmarket_data, intraday_data, decision_data)
        ))

    if intraday.get("status") == "degraded":
        rows.append(blind_spot(
            "intraday-structure-degraded",
            "盘中结构降权",
            "warning",
            "盘面宽度、行业/概念强弱和午后建议可看，但实时涨跌幅需复核。",
            ["强主线不能直接外推为进攻", "机会候选只能等待确认", "风险项优先级高于机会项"],
            [intraday.get("reason") or "盘中全景降权"],
            "优先看涨跌停/炸板/尾盘承接等结构证据，不用单个涨跌幅做结论。",
            ["data/intraday.json", "data/data-trust.json"]
        ))

    if premarket.get("status") == "degraded":
        rows.append(blind_spot(
            "premarket-cross-market-degraded",
            "盘前外部映射降权",
            "warning",
            "美股/港股/日韩映射可以提供方向，但部分实时外部源非终值或需复核。",
            ["盘前提振/压制判断不能单独作为开盘动作", "科技映射链需要9:25竞价和9:30后承接确认"],
            [premarket.get("reason") or "盘前数据降权"],
            "开盘只按竞价确认后的 A 股反馈升级，不把外盘映射直接升为强主线。",
            ["data/premarket.json", "data/source-health.json"]
        ))

    if postmarket.get("status") == "degraded":
        rows.append(blind_spot(
            "postmarket-close-degraded",
            "盘后复盘降权",
            "warning",
            "收盘复盘可参考，但港股收盘窗口和部分补充行情源需要复核。",
            ["次日方向只作为预案", "需等待次日竞价验证"],
            [postmarket.get("reason") or "盘后数据降权"],
            "把盘后结论拆成次日验证条件，不直接继承为次日交易方向。",
            ["data/postmarket.json", "data/source-health.json"]
        ))

    if evening.get("status") == "stale":
        rows.append(blind_spot(
            "evening-sentiment-stale",
            "晚间舆情过期",
            "info",
            "晚间公告、P0 舆情和隔夜事件不是当前交易日，不能参与今日总控。",
            ["次日竞价风险可能缺少最新公告校验", "个股突发公告需要额外扫描"],
            [evening.get("reason") or "晚间舆情非当前交易日"],
            "只作历史背景；盘前必须重新跑 8:30 增量扫描和个股公告检查。",
            ["data/evening-sentiment.json"]
        ))

    if decision.get("status") == "degraded":
        opportunity_grades = [item.get("signal_grade") for item in decision_feed.get("opportunities", []) if isinstance(item, dict)]
        if opportunity_grades and all(grade in {"C", "D"} for grade in opportunity_grades):
            rows.append(blind_spot(
                "opportunity-radar-downgraded",
                "机会雷达仅作候选",
                "warning",
                "当前机会项全部为降权观察/仅复核，没有可直接跟踪的 A/B 级机会。",
                ["机会栏不能追高", "风险栏优先级高于机会栏"],
                [decision.get("reason") or "机会风险流降权"],
                "只跟踪验证条件；若风险项不收敛，不升级任何机会。",
                ["data/decision-feed.json", "data/data-trust.json"]
            ))

    hk_flags = hk_source_flags(source_health)
    if hk_flags:
        rows.append(blind_spot(
            "hk-cross-market-source",
            "港股映射源降权",
            "warning",
            "港股结构行情或收盘窗口存在降级，AH 映射和港股科技反馈不能按终值处理。",
            ["港股半导体/互联网/创新药映射需要二次确认", "盘前外部环境不直接升级 A 股方向"],
            hk_flags[:3],
            "港股映射只作情绪背景，以 A 股竞价和开盘30分钟承接为准。",
            ["data/source-health.json"]
        ))

    return dedupe(rows)


def blind_spot(
    item_id: str,
    title: str,
    severity: str,
    conclusion: str,
    impacted_decisions: list[str],
    evidence: list[str],
    fallback_action: str,
    source_files: list[str],
    fallback_checks: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "title": title,
        "severity": severity,
        "conclusion": trim(conclusion, 180),
        "impacted_decisions": clean_list(impacted_decisions)[:4],
        "evidence": clean_list(evidence)[:4],
        "fallback_action": trim(fallback_action, 180),
        "fallback_checks": clean_list(fallback_checks or [])[:6],
        "source_files": source_files[:4],
    }


def alert_fallback_checks(postmarket: dict[str, Any], intraday: dict[str, Any], decision_feed: dict[str, Any]) -> list[str]:
    breadth = market_breadth_text(postmarket, intraday)
    theme_rows = theme_checks(postmarket)
    main_line = next((row for row in theme_rows if row.startswith("主线替代：")), None)
    new_line = next((row for row in theme_rows if row.startswith("新线替代：")), None)

    checks = [
        breadth or "宽度替代：实时涨停、跌停和炸板数据暂不可用；恢复前不判断情绪扩散。",
        main_line or "主线替代：先看半导体设备/材料/制造/封测能否同步扩散；单点强不升级。",
        new_line or "新线替代：从行业与题材涨幅、成交和涨停新增中寻找首次扩散方向；没有宽度不升级。",
    ]
    checks.extend(row for row in theme_rows if row not in {main_line, new_line})
    checks.extend(decision_checks(decision_feed))
    return checks


def market_breadth_text(postmarket: dict[str, Any], intraday: dict[str, Any]) -> str:
    mb = ((postmarket.get("index") or {}).get("market_breadth") or {}) if isinstance(postmarket, dict) else {}
    if not isinstance(mb, dict):
        mb = {}
    sentiment = (intraday.get("sentiment") or {}) if isinstance(intraday, dict) else {}
    if not isinstance(sentiment, dict):
        sentiment = {}
    limit_up = mb.get("limit_up") or sentiment.get("limit_up_count")
    limit_down = mb.get("limit_down") or sentiment.get("limit_down_count")
    broken = mb.get("broken_board") or sentiment.get("broken_limit_count")
    down5 = mb.get("down5")
    if not any(v is not None for v in (limit_up, limit_down, broken, down5)):
        return ""
    return f"宽度替代：9:25/9:30先看涨停{limit_up or '-'}、跌停{limit_down or '-'}、炸板{broken or '-'}、跌5%以上{down5 or '-'}是否收敛；不收敛则风险优先。"


def theme_checks(postmarket: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for theme in postmarket.get("hotspots") or []:
        if not isinstance(theme, dict):
            continue
        name = str(theme.get("name") or "")
        status = str(theme.get("status") or "")
        stocks = stock_names(theme.get("stocks"))[:4]
        if not name or not stocks:
            continue
        state_text = " ".join([name, status, str(theme.get("continuity") or ""), str(theme.get("note") or "")])
        if re.search(r"风险线|弱化|退潮|反抽失败|证伪", state_text):
            rows.append(f"风险线替代：{name} 看 {'/'.join(stocks)} 是否继续低开或弱反抽；未修复前不升级。")
        elif re.search(r"低位|消费电子|元件|新线|轮动增强", name + status):
            rows.append(f"新线替代：{name} 看 {'/'.join(stocks)} 是否继续扩散；只强一日则按轮动处理。")
        elif len(rows) < 4:
            rows.append(f"主线替代：{name} 看 {'/'.join(stocks)} 是否同步高开承接，单点强不升级。")
    return rows[:4]


def decision_checks(decision_feed: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in (decision_feed.get("risks") or [])[:3]:
        if isinstance(item, dict) and item.get("watch_next"):
            rows.append(f"雷达替代：{trim(item.get('title'), 28)}：{trim((item.get('watch_next') or [''])[0], 90)}")
    return rows[:2]


def stock_names(value: Any) -> list[str]:
    rows = []
    if not isinstance(value, list):
        return rows
    for item in value:
        if isinstance(item, dict):
            rows.append(str(item.get("name") or item.get("symbol") or ""))
        else:
            rows.append(str(item or ""))
    return clean_list(rows)


def hk_source_flags(source_health: dict[str, Any]) -> list[str]:
    sources = source_health.get("sources") if isinstance(source_health, dict) else {}
    if not isinstance(sources, dict):
        return []
    rows = []
    for name, source in sources.items():
        if not isinstance(source, dict):
            continue
        if "hk" in name.lower() and source.get("status") in {"degraded", "failed", "bad"}:
            rows.append(source_flag_message(name, source))
    return clean_list(rows)


def source_flag_message(name: str, source: dict[str, Any]) -> str:
    text = f"{name}: {source.get('detail') or source.get('note') or source.get('usage') or source.get('status')}"
    if re.search(r"Can not decode value starting with|JSON decode failed|proxy disconnect|failed with|decode failed", text, re.I):
        if re.search(r"hk|港股|stock_hk|Eastmoney|push2", text, re.I):
            return "港股结构行情源连接/解码异常，港股映射和收盘窗口价格需二次复核。"
        if re.search(r"japan|korea|nikkei|kospi|日韩|日经|韩国", text, re.I):
            return "日韩早盘实时源异常，页面仅保留待复核清单，不展示未核实数值。"
        return "补充行情源解码异常，相关价格和异动信号需二次复核。"
    return text


def summarize(rows: list[dict[str, Any]]) -> str:
    critical = [item for item in rows if item["severity"] == "critical"]
    warning = [item for item in rows if item["severity"] == "warning"]
    info = [item for item in rows if item["severity"] == "info"]
    if critical:
        names = "、".join(item["title"] for item in critical[:3])
        return f"{len(critical)} 个核心监测盲区（{names}），{len(warning)} 个降权盲区。"
    if warning:
        return f"{len(warning)} 个监测维度需降权，{len(info)} 个背景维度需复核。"
    if info:
        return f"{len(info)} 个背景维度需复核。"
    return "核心监测链路无明显盲区。"


def dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    output = []
    for row in rows:
        key = row["id"]
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clean_list(values: list[Any]) -> list[str]:
    rows = []
    seen = set()
    for value in values:
        text = trim(value, 220)
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def trim(text: Any, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def signal_date(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


def now_iso() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

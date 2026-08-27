#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_platform.trading_context import resolve_cn_trading_context

DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "opportunity-watch.json"
TZ = timezone(timedelta(hours=8))

THEME_STOCKS = {
    "半导体设备": ["北方华创", "中微公司", "华海清科", "芯源微", "中科飞测"],
    "半导体材料": ["有研硅", "雅克科技", "沪硅产业", "安集科技", "江丰电子", "南大光电"],
    "半导体设备材料": ["北方华创", "中微公司", "华海清科", "安集科技", "有研硅", "雅克科技"],
    "半导体制造": ["中芯国际H", "华虹半导体", "华虹宏力", "华虹公司", "中芯国际"],
    "存储/HBM": ["兆易创新", "兆易创新H", "澜起科技", "澜起科技H", "佰维存储", "江波龙", "长电科技"],
    "先进封装": ["长电科技", "华天科技", "通富微电", "甬矽电子"],
    "AI算力": ["浪潮信息", "工业富联", "中科曙光", "寒武纪"],
    "云计算/阿里链": ["阿里巴巴", "深信服", "网宿科技", "昆仑万维"],
    "港股科网AI应用映射": ["金山办公", "同花顺", "科大讯飞", "万兴科技", "浪潮信息", "中科曙光"],
    "CPO/光模块": ["新易盛", "中际旭创", "天孚通信", "光迅科技", "华工科技"],
    "PCB/电子布": ["胜宏科技", "沪电股份", "生益科技", "中国巨石", "国际复材"],
    "机器人/工业自动化": ["绿的谐波", "埃斯顿", "步科股份", "华瑞股份", "拓斯达"],
    "医药修复链": ["恒瑞医药", "科伦药业", "普洛药业"],
    "老登风格切换": ["中信证券", "东方财富", "中国平安", "贵州茅台", "牧原股份"],
}

THEME_IDS = {
    "半导体设备": "semiconductor_equipment",
    "半导体材料": "semiconductor_materials",
    "半导体设备材料": "semiconductor_equipment_materials",
    "半导体制造": "semiconductor_manufacturing",
    "存储/HBM": "memory_hbm",
    "先进封装": "advanced_packaging",
    "AI算力": "ai_compute",
    "云计算/阿里链": "cloud_alibaba",
    "港股科网AI应用映射": "hk_internet_ai_app_mapping",
    "CPO/光模块": "cpo_optical",
    "PCB/电子布": "pcb_electronic_fabric",
    "机器人/工业自动化": "robotics_automation",
    "医药修复链": "medicine_repair",
    "老登风格切换": "old_deng_rotation",
}

GLOBAL_EVIDENCE = re.compile(r"美股三大指数|纳指|标普|道指|恒生指数|港股大盘|全市场流动性|人民币汇率|北向资金|市场风险偏好")

THEME_PATTERNS = [
    ("半导体设备材料", r"半导体制造/设备/材料|半导体设备材料|设备/材料"),
    ("半导体制造", r"半导体制造|晶圆制造|中芯国际|华虹"),
    ("半导体设备", r"半导体设备|北方华创|中微公司|华海清科|芯源微"),
    ("半导体材料", r"半导体材料|CMP|靶材|硅片|雅克|有研硅|沪硅|安集|江丰|南大光电"),
    ("存储/HBM", r"存储|HBM|美光|澜起|兆易|佰维|江波龙"),
    ("先进封装", r"先进封装|封测|长电|华天|通富|甬矽"),
    ("AI算力", r"AI算力|算力|服务器|英伟达|NVIDIA|浪潮|工业富联|中科曙光"),
    ("港股科网AI应用映射", r"港股科网|科网权重|腾讯|阿里|美团|快手"),
    ("云计算/阿里链", r"云计算|阿里链|阿里巴巴|国资云"),
    ("CPO/光模块", r"CPO|光模块|光通信|新易盛|中际旭创|天孚"),
    ("PCB/电子布", r"PCB|电子布|玻纤|覆铜板|胜宏|沪电|生益|中国巨石|国际复材"),
    ("机器人/工业自动化", r"机器人|工业自动化|通用设备|减速器|伺服|绿的谐波|埃斯顿"),
    ("医药修复链", r"医药|创新药|(?<![A-Za-z])CRO(?![A-Za-z])|化学制药|恒瑞|科伦|普洛"),
    ("老登风格切换", r"老登|券商|保险|白酒|畜牧|银行|地产|金融"),
]

RISK_WORDS = re.compile(r"风险|压制|回避|退潮|不升级|暂不|弱|高位分歧|兑现")
POSITIVE_WORDS = re.compile(r"强化|强主线|强分支|提振|共振|优先|受益|修复|偏强")


def main() -> int:
    premarket = load_json(DATA_DIR / "premarket.json")
    evening = load_json(DATA_DIR / "evening-sentiment.json")
    topics = load_json(DATA_DIR / "topics.json")
    items = dedupe_items([
        *items_from_premarket(premarket),
        *items_from_evening(evening),
        *items_from_topics(topics),
    ])
    now = datetime.now(TZ)
    context = resolve_cn_trading_context(ROOT, now, [latest_signal_date(premarket, topics)])
    report = {
        "timestamp": now.astimezone(TZ).replace(microsecond=0).isoformat(),
        "current_signal_date": context.market_date.isoformat(),
        "target_trade_date": context.target_trade_date.isoformat(),
        "calendar_version": context.calendar_version,
        "items": rank_items(items)[:12],
        "rules": [
            "盘前/晚间/专题只生成等待触发清单，不直接生成交易指令。",
            "盘中正式机会必须由 alert.json 的短周期价格、成交和扩散证据确认。",
            "候选机会可先提醒，但必须标注确认度和还差什么确认。",
            "超过5分钟未继续确认的盘中异动只能作为历史触发。",
            "休市日新增晚间信息归入下一交易日预案，不改写最近市场交易日。",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"opportunity-watch: {len(report['items'])} items")
    return 0


def items_from_premarket(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    context = data.get("market_context") or {}
    for theme in listify(context.get("benefit_themes")):
        rows.append(make_item(theme, "盘前", context.get("sentiment_judgement") or data.get("summary") or data.get("strategy"), "high"))
    for news in data.get("overnight_news") or []:
        text = compact_text([news.get("text"), news.get("impact"), news.get("mapping"), news.get("logic_chain")])
        for theme in extract_themes(text):
            rows.append(make_item(theme, "盘前", text, "medium"))
    for chain in (data.get("us_overnight") or {}).get("mapping_chain") or []:
        text = compact_text([chain.get("source_asset"), chain.get("reason"), chain.get("a_share_mapping"), chain.get("mapping_logic")])
        for theme in extract_themes(text):
            rows.append(make_item(theme, "盘前", text, "medium"))
    return rows


def items_from_evening(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for alert in data.get("p0_alerts") or []:
        text = compact_text([alert.get("title"), alert.get("why_p0"), alert.get("watch_next_day"), alert.get("evidence")])
        for theme in extract_themes(text):
            rows.append(make_item(theme, "晚间P0", text, "high"))
    for news in data.get("news") or []:
        text = compact_text([news.get("text"), news.get("impact"), news.get("takeaway"), news.get("mapping"), news.get("tag")])
        for theme in extract_themes(text):
            rows.append(make_item(theme, "晚间舆情", text, "medium"))
    return rows


def items_from_topics(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for topic in data.get("topics") or []:
        text = compact_text([topic.get("name"), topic.get("status"), topic.get("conclusion"), topic.get("action"), topic.get("note")])
        theme = normalize_theme(topic.get("name") or "") or first_theme(text)
        if theme:
            priority = "high" if POSITIVE_WORDS.search(text) else "medium"
            rows.append(make_item(theme, "专题", text, priority))
    return rows


def make_item(theme: str, source_phase: str, reason: Any, priority: str) -> dict[str, Any]:
    theme = normalize_theme(theme) or str(theme)
    reason_text = clean_text(reason)
    riskish = bool(RISK_WORDS.search(reason_text))
    evidence_refs = structured_evidence(theme, source_phase, reason_text)
    accepted_theme = [item["summary"] for item in evidence_refs if item["accepted"] and item["scope"] == "theme"]
    accepted_global = [item["summary"] for item in evidence_refs if item["accepted"] and item["scope"] == "global"]
    summary_parts = [*accepted_theme[:2], *accepted_global[:1]]
    return {
        "id": slug(theme),
        "theme_id": THEME_IDS.get(theme, slug(theme)),
        "theme": theme,
        "priority": priority,
        "source_phase": source_phase,
        "source_reason": trim(reason_text, 220) or f"{source_phase}提示需跟踪",
        "why_watch_summary": trim("；".join(summary_parts), 180) if summary_parts else "关联证据不足，等待主题专属依据。",
        "watch_stocks": THEME_STOCKS.get(theme, infer_stocks(reason_text))[:6],
        "confirm_rules": confirm_rules(theme, riskish),
        "invalidate_rules": invalidate_rules(theme, riskish),
        "status": "waiting",
        "last_checked_at": "",
        "evidence_refs": evidence_refs,
        "evidence": [item for item in evidence_refs if item["accepted"]],
    }


def structured_evidence(theme: str, source_phase: str, reason_text: str) -> list[dict[str, Any]]:
    theme_id = THEME_IDS.get(theme, slug(theme))
    rows: list[dict[str, Any]] = []
    for raw in re.split(r"[；。\n]+", reason_text):
        summary = trim(raw.strip(" \t\r\n；。[]{}\","), 140)
        if not summary:
            continue
        mapped = extract_themes(summary)
        theme_match = theme in mapped or any(stock in summary for stock in THEME_STOCKS.get(theme, []))
        global_match = bool(GLOBAL_EVIDENCE.search(summary)) and not mapped
        accepted = theme_match or global_match
        scope = "theme" if theme_match else ("global" if global_match else "theme")
        digest = hashlib.sha256(f"{source_phase}|{theme_id}|{summary}".encode("utf-8")).hexdigest()[:16]
        rows.append({
            "evidence_id": f"evidence_{digest}",
            "scope": scope,
            "mapped_theme_ids": [theme_id] if theme_match else [THEME_IDS.get(item, slug(item)) for item in mapped],
            "summary": summary,
            "source_phase": source_phase,
            "accepted": accepted,
            "rejection_reason": None if accepted else ("映射到其他主题" if mapped else "缺少当前主题映射"),
        })
    return rows


def confirm_rules(theme: str, riskish: bool) -> list[str]:
    if riskish:
        return [
            "核心股低开后放量收复开盘价或跌幅明显收敛",
            "同题材后排不再扩大负反馈，跌停/炸板数量下降",
            "板块ETF或指数不再创新低并出现承接",
        ]
    if theme == "老登风格切换":
        return [
            "券商+保险或畜牧+白酒至少两个方向同步放量走强",
            "科技主线或科创50走弱时老登板块对指数形成贡献",
            "涨停/成交额向金融、消费防御或资源权重扩散",
        ]
    if theme in {"半导体制造", "存储/HBM", "半导体设备材料", "半导体设备", "半导体材料"}:
        return [
            "早期候选：核心股从低位重新站回分时均价/开盘价，且同题材至少2只代表股同步转强",
            "A/H共振：港股半导体核心与A股半导体ETF、科创50或A股映射股至少两侧同向修复",
            "题材3分钟涨跌幅>=1.5%，方向占比>=70%，成交放大>=5x",
            "确认升级：候选后继续放量、后排扩散或核心股维持均价上方；否则只做回踩承接观察",
        ]
    if theme == "港股科网AI应用映射":
        return [
            "早期候选：港股科网权重或智谱站回分时均价，同时A股AI应用/软件至少2只同步转强",
            "题材3分钟涨跌幅>=1.5%，方向占比>=70%，成交放大>=5x",
            "板块内出现批量涨停/封板或后排扩散",
            "确认升级：AI应用后排扩散且恒生科技/核心权重没有重新跌回均价",
        ]
    return [
        "题材3分钟涨跌幅>=1.5%，方向占比>=70%，成交放大>=5x",
        "板块内出现批量涨停/封板或后排扩散",
        "核心股、ETF、后排扩散同向确认",
    ]


def invalidate_rules(theme: str, riskish: bool) -> list[str]:
    if riskish:
        return ["核心股继续放量下跌", "跌停/炸板数量扩大", "修复只停留在单股反抽"]
    if theme in {"半导体制造", "存储/HBM", "半导体设备材料", "半导体设备", "半导体材料"}:
        return ["核心股重新跌回分时均价", "A/H任一侧共振断裂", "后排不扩散且成交萎缩"]
    if theme == "港股科网AI应用映射":
        return ["智谱或科网权重跌回分时均价", "A股AI应用后排不跟", "恒生科技冲高回落"]
    return ["核心股高开低走或冲高回落", "后排不扩散且成交萎缩", "相关风险线重新扩大"]


def rank_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority_score = {"high": 3, "medium": 2, "low": 1}
    source_score = {"晚间P0": 4, "盘前": 3, "专题": 2, "晚间舆情": 1}
    return sorted(
        items,
        key=lambda item: (
            priority_score.get(item.get("priority"), 0),
            source_score.get(item.get("source_phase"), 0),
            len(item.get("watch_stocks") or []),
        ),
        reverse=True,
    )


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item["id"]
        if key not in merged:
            merged[key] = item
            continue
        target = merged[key]
        if priority_rank(item["priority"]) > priority_rank(target["priority"]):
            target["priority"] = item["priority"]
        target["source_phase"] = merge_text(target["source_phase"], item["source_phase"], " / ")
        target["source_reason"] = trim(merge_text(target["source_reason"], item["source_reason"], "；"), 220)
        refs = unique_dicts([*target.get("evidence_refs", []), *item.get("evidence_refs", [])], "evidence_id")
        target["evidence_refs"] = refs
        target["evidence"] = [ref for ref in refs if ref.get("accepted")]
        accepted_theme = [ref.get("summary") for ref in refs if ref.get("accepted") and ref.get("scope") == "theme"]
        accepted_global = [ref.get("summary") for ref in refs if ref.get("accepted") and ref.get("scope") == "global"]
        parts = [*accepted_theme[:2], *accepted_global[:1]]
        target["why_watch_summary"] = trim("；".join(str(part) for part in parts if part), 180) if parts else "关联证据不足，等待主题专属依据。"
        target["watch_stocks"] = unique([*target.get("watch_stocks", []), *item.get("watch_stocks", [])])[:6]
        target["confirm_rules"] = unique([*target.get("confirm_rules", []), *item.get("confirm_rules", [])])[:4]
        target["invalidate_rules"] = unique([*target.get("invalidate_rules", []), *item.get("invalidate_rules", [])])[:3]
    return list(merged.values())


def unique_dicts(values: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        identity = str(value.get(key) or "") if isinstance(value, dict) else ""
        if identity and identity not in seen:
            seen.add(identity)
            rows.append(value)
    return rows


def priority_rank(value: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(value, 0)


def extract_themes(text: str) -> list[str]:
    themes = []
    for name, pattern in THEME_PATTERNS:
        if re.search(pattern, text, re.I):
            themes.append(name)
    return unique(themes)


def first_theme(text: str) -> str:
    themes = extract_themes(text)
    return themes[0] if themes else ""


def normalize_theme(value: str) -> str:
    text = str(value or "")
    for name, pattern in THEME_PATTERNS:
        if text == name or re.search(pattern, text, re.I):
            return name
    return ""


def infer_stocks(text: str) -> list[str]:
    candidates = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,12}", text)
    blocked = {"盘前", "晚间", "专题", "风险", "观察", "强主线", "强分支", "半导体", "交易", "机会", "确认"}
    rows = []
    for item in candidates:
        if item in blocked or re.search(r"指数|板块|题材|涨停|跌停|成交|分钟", item):
            continue
        rows.append(item)
    return unique(rows)[:6]


def latest_signal_date(*payloads: dict[str, Any]) -> str:
    dates = []
    for data in payloads:
        if not isinstance(data, dict):
            continue
        ts = data.get("timestamp")
        match = re.search(r"\d{4}-\d{2}-\d{2}", str(ts or ""))
        if match:
            dates.append(match.group(0))
    return sorted(dates)[-1] if dates else now_iso()[:10]


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def listify(value: Any) -> list[str]:
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    text = clean_text(value)
    return [text] if text else []


def compact_text(parts: list[Any]) -> str:
    return clean_text("；".join(clean_text(part) for part in parts if clean_text(part)))


def clean_text(value: Any) -> str:
    if isinstance(value, dict):
        # Evidence objects contain governance metadata such as type/source/timestamp.
        # Only business-facing facts may participate in theme matching or summaries;
        # otherwise a source name such as "腾讯美股公开行情" can both leak onto the
        # page and be mistaken for a Hong Kong internet-theme clue.
        visible_keys = (
            "detail",
            "summary",
            "conclusion",
            "text",
            "fact",
            "impact",
            "takeaway",
            "mapping",
            "logic_chain",
            "title",
        )
        parts = [clean_text(value.get(key)) for key in visible_keys if value.get(key) not in (None, "")]
        return "；".join(unique(part for part in parts if part))
    if isinstance(value, list):
        return "；".join(unique(clean_text(item) for item in value if clean_text(item)))
    return re.sub(r"\s+", " ", str(value or "")).strip()


def merge_text(a: str, b: str, sep: str) -> str:
    if not a:
        return b
    if not b or b in a:
        return a
    return f"{a}{sep}{b}"


def unique(values: list[str]) -> list[str]:
    seen = set()
    rows = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in seen:
            seen.add(value)
            rows.append(value)
    return rows


def trim(value: str, limit: int) -> str:
    value = str(value or "")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def slug(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]+", "-", value).strip("-")
    return text or "watch"


def now_iso() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

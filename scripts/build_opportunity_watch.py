#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from data_validity import topic_current, premarket_timing
from intraday_recovery import is_trading_day


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "opportunity-watch.json"
TZ = timezone(timedelta(hours=8))

THEME_STOCKS = {
    "半导体设备": ["北方华创", "中微公司", "华海清科", "芯源微", "中科飞测"],
    "半导体材料": ["有研硅", "雅克科技", "沪硅产业", "安集科技", "江丰电子", "南大光电"],
    "半导体设备材料": ["北方华创", "中微公司", "华海清科", "安集科技", "有研硅", "雅克科技"],
    "半导体制造": ["中芯国际", "华虹公司", "华虹宏力", "中芯国际H"],
    "存储/HBM": ["澜起科技", "兆易创新", "佰维存储", "江波龙", "长电科技"],
    "先进封装": ["长电科技", "华天科技", "通富微电", "甬矽电子"],
    "交换机/高速以太网": ["紫光股份", "锐捷网络", "中兴通讯", "菲菱科思", "共进股份", "工业富联", "盛科通信-U"],
    "AI算力": ["浪潮信息", "工业富联", "中科曙光", "寒武纪"],
    "云计算/阿里链": ["阿里巴巴", "深信服", "网宿科技", "昆仑万维"],
    "CPO/光模块": ["新易盛", "中际旭创", "天孚通信", "光迅科技", "华工科技"],
    "PCB/电子布": ["胜宏科技", "沪电股份", "生益科技", "中国巨石", "国际复材"],
    "机器人/工业自动化": ["绿的谐波", "埃斯顿", "步科股份", "华瑞股份", "拓斯达"],
    "医药修复链": ["恒瑞医药", "科伦药业", "普洛药业"],
    "老登风格切换": ["中信证券", "东方财富", "中国平安", "贵州茅台", "牧原股份"],
}

THEME_PATTERNS = [
    ("半导体设备材料", r"半导体制造/设备/材料|半导体设备材料|设备/材料"),
    ("半导体制造", r"半导体制造|晶圆制造|中芯国际|华虹"),
    ("半导体设备", r"半导体设备|北方华创|中微公司|华海清科|芯源微"),
    ("半导体材料", r"半导体材料|CMP|靶材|硅片|雅克|有研硅|沪硅|安集|江丰|南大光电"),
    ("存储/HBM", r"存储|HBM|美光|澜起|兆易|佰维|江波龙"),
    ("先进封装", r"先进封装|封测|长电|华天|通富|甬矽"),
    ("交换机/高速以太网", r"交换机|高速以太网|AI以太网|白盒交换机|Spectrum-X|Arista|Cisco|紫光股份|锐捷网络|菲菱科思|共进股份|盛科通信"),
    ("AI算力", r"AI算力|算力|服务器|英伟达|NVIDIA|浪潮|工业富联|中科曙光"),
    ("云计算/阿里链", r"云计算|阿里链|阿里巴巴|国资云"),
    ("CPO/光模块", r"CPO|光模块|光通信|新易盛|中际旭创|天孚"),
    ("PCB/电子布", r"PCB|电子布|玻纤|覆铜板|胜宏|沪电|生益|中国巨石|国际复材"),
    ("机器人/工业自动化", r"机器人|工业自动化|通用设备|减速器|伺服|绿的谐波|埃斯顿"),
    ("医药修复链", r"医药|创新药|CRO|化学制药|恒瑞|科伦|普洛"),
    ("老登风格切换", r"老登|券商|保险|白酒|畜牧|银行|地产|金融"),
]

RISK_WORDS = re.compile(r"风险|压制|回避|退潮|不升级|暂不|弱|高位分歧|兑现")


def main() -> int:
    premarket = load_json(DATA_DIR / "premarket.json")
    evening = load_json(DATA_DIR / "evening-sentiment.json")
    topics = load_json(DATA_DIR / "topics.json")
    report = build_report(premarket, evening, topics, load_json(DATA_DIR / "watchlist-quotes.json"))
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=DATA_DIR, suffix=".tmp", delete=False) as tmp:
        tmp.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    Path(tmp.name).replace(OUT)
    print(f"opportunity-watch: {len(report['items'])} items")
    return 0


def stamp(value: Any) -> datetime | None:
    raw = str(value or "")
    try:
        if re.fullmatch(r"\d{14}", raw):
            return datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=TZ)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.astimezone(TZ) if parsed.tzinfo is not None else None
    except ValueError:
        return None


def research_stamp(data: dict[str, Any]) -> datetime | None:
    return stamp(next((data[k] for k in ("analysis_time", "research_updated_at", "updated_at", "timestamp") if k in data), None))


def previous_session(now: datetime) -> str:
    for days in range(1, 16):
        candidate = now - timedelta(days=days)
        if is_trading_day(ROOT, candidate):
            return candidate.date().isoformat()
    return ""


def build_report(premarket, evening, topics, quotes, now=None):
    now = (now or datetime.now(TZ)).astimezone(TZ)
    day = now.date().isoformat()
    rows = []
    if is_trading_day(ROOT, now):
        authored = research_stamp(premarket)
        if (premarket_timing(premarket, now).get("target_date") == day and authored and authored <= now
                and stamp(premarket.get("timestamp")) and stamp(premarket["timestamp"]) <= now
                and not premarket.get("historical_backfill")):
            rows.extend(items_from_premarket(premarket))
            for row in rows:
                row["source_as_of"] = authored.isoformat()
        authored = research_stamp(evening)
        previous = previous_session(now)
        # An early-morning file stamped today cannot renew an older evening report.
        if (previous and evening.get("trade_date") == previous and authored and authored <= now
                and authored >= datetime.fromisoformat(previous + "T15:00:00+08:00")
                and not evening.get("historical_backfill")):
            for row in items_from_evening(evening):
                row["source_as_of"] = authored.isoformat()
                rows.append(row)
        rows.extend(items_from_topics(topics, day=day, now=now))
        rows = dedupe_items(rows)
        # Keep current downside evidence even when the old research has expired.
        # This is representative-stock risk, not a new sector opportunity or asset.
        known = {row["theme"] for row in rows}
        for theme in THEME_STOCKS:
            if theme not in known:
                probe = assess_item(make_item(theme, "盘中行情", "", "low"), quotes, now)
                if probe["status"] == "risk_observation":
                    rows.append(probe)
        rows = [assess_item(row, quotes, now) for row in rows]
    return {
        "schema_version": 2,
        "timestamp": now.isoformat(timespec="seconds"),
        "current_signal_date": day,
        "items": rank_items(rows)[:12],
        "rules": [
            "今日研究与盘中行情分开；过期研究不得因重新构建而成为今日重点。",
            "盘前/晚间/专题只生成观察清单，条件性共振不代表已经确认。",
            "代表股走弱转为风险观察，单日上涨也不能直接成为交易机会。",
            "盘中正式机会必须由 alert.json 的短周期价格、成交和扩散证据确认。",
        ],
    }


def representative_quotes(item, quotes, now):
    minute = now.hour * 60 + now.minute
    if minute < 570 or minute >= 900:
        return []
    rows = {}
    for quote in quotes.get("stocks") or []:
        if not isinstance(quote, dict) or quote.get("name") not in item["watch_stocks"]:
            continue
        code = str(quote.get("code") or "")
        at = stamp(quote.get("quote_time"))
        if not re.fullmatch(r"(?:sh|sz|bj)\d{6}", code) or not at or not quote.get("source"):
            continue
        if at.date() != now.date() or at > now or at.hour * 60 + at.minute < 570:
            continue
        lunch = 690 <= minute < 780 and 685 <= at.hour * 60 + at.minute <= 690
        if (now - at).total_seconds() > 1200 and not lunch:
            continue
        try:
            price, opening, pct = (float(quote[k]) for k in ("price", "open", "change_pct"))
        except (KeyError, ValueError, TypeError):
            continue
        if not all(math.isfinite(v) for v in (price, opening, pct)) or min(price, opening) <= 0:
            continue
        row = {k: quote[k] for k in ("code", "name", "source")}
        row.update(price=price, open=opening, change_pct=pct, quote_time=at.isoformat())
        if code not in rows or row["quote_time"] > rows[code]["quote_time"]:
            rows[code] = row
    if not rows:
        return []
    newest = max(stamp(row["quote_time"]) for row in rows.values())
    # Do not combine different sampling windows into a majority vote.
    return [row for row in rows.values() if (newest - stamp(row["quote_time"])).total_seconds() <= 120]


def assess_item(item, quotes, now):
    item = dict(item)
    item.update(priority="medium", status="waiting", last_checked_at=now.isoformat(timespec="seconds"))
    rows = representative_quotes(item, quotes, now)
    item["representative_quotes"] = rows
    item["evidence"] = [f'{q["name"]}（{q["code"][2:]}）{q["change_pct"]:+.2f}%，'
                        f'{q["quote_time"][11:19]}，{q["source"]}' for q in rows]
    item["assessment"] = "等待代表股最新行情，暂不列为优先机会。"
    minute = now.hour * 60 + now.minute
    if minute < 570:
        item.update(status="premarket_watch", assessment="盘前关注，开盘后再看代表股与板块是否一起走强。")
    elif minute >= 900:
        item.update(status="session_closed", assessment="已收盘，盘前计划仅供回看。")
    elif len(rows) >= 2:
        weak = [q for q in rows if q["change_pct"] <= -3 and q["price"] < q["open"]]
        negative = [q for q in rows if q["change_pct"] < 0 and q["price"] < q["open"]]
        if len(weak) >= 2 and len(weak) > len(rows) / 2:
            item.update(status="risk_observation", priority="low",
                        assessment="已取得行情的代表股多数明显下跌，且低于开盘价；先看下跌风险，暂不列为优先机会。")
            item["confirm_rules"] = ["等代表股止跌、收复开盘价，再核对板块是否同步回升；单股反弹不算确认。"]
            item["invalidate_rules"] = ["代表股继续下探、板块跟随走弱时，不按修复机会看待。"]
        elif len(negative) >= 2 and len(negative) > len(rows) / 2:
            item["assessment"] = "已取得行情的代表股多数偏弱，尚未支持盘前预期；等待止跌，不作为优先机会。"
        else:
            item["assessment"] = "代表股涨跌见下方；还需板块跟涨、成交和持续性确认，目前仅作观察。"
    return item


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


def items_from_topics(data: dict[str, Any], day=None, now=None) -> list[dict[str, Any]]:
    now = now or datetime.now(TZ)
    day = day or now.astimezone(TZ).date().isoformat()
    rows: list[dict[str, Any]] = []
    for topic in data.get("topics") or []:
        if not isinstance(topic, dict) or not topic_current(topic, day, now=now):
            continue
        text = compact_text([topic.get("name"), topic.get("status"), topic.get("conclusion"), topic.get("action"), topic.get("note")])
        theme = normalize_theme(topic.get("name") or "") or first_theme(text)
        if theme:
            item = make_item(theme, "专题", text, "medium")
            item["source_as_of"] = research_stamp(topic).isoformat()
            rows.append(item)
    return rows


def make_item(theme: str, source_phase: str, reason: Any, priority: str) -> dict[str, Any]:
    theme = normalize_theme(theme) or str(theme)
    reason_text = trim(clean_text(reason), 160)
    riskish = bool(RISK_WORDS.search(reason_text))
    return {
        "id": slug(theme),
        "theme": theme,
        "priority": "medium",  # Importance of a plan is not evidence of a trade.
        "source_phase": source_phase,
        "source_reason": reason_text or f"{source_phase}提示需跟踪",
        "watch_stocks": THEME_STOCKS.get(theme, infer_stocks(reason_text))[:6],
        "confirm_rules": confirm_rules(theme, riskish),
        "invalidate_rules": invalidate_rules(theme, riskish),
        "status": "waiting",
        "last_checked_at": "",
        "evidence": [],
    }


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
    return [
        "先看代表股能否持续走强，再看同板块是否有更多股票跟涨。",
        "成交同步增加、板块涨势持续后，再看正式异动提示；短线急拉不算确认。",
    ]


def invalidate_rules(theme: str, riskish: bool) -> list[str]:
    if riskish:
        return ["核心股继续放量下跌", "跌停/炸板数量扩大", "修复只停留在单股反抽"]
    return ["核心股高开低走或冲高回落", "后排不扩散且成交萎缩", "相关风险线重新扩大"]


def rank_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority_score = {"high": 3, "medium": 2, "low": 1}
    source_score = {"晚间P0": 4, "盘前": 3, "专题": 2, "晚间舆情": 1}
    return sorted(
        items,
        key=lambda item: (
            item.get("status") == "risk_observation",
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
        target["watch_stocks"] = unique([*target.get("watch_stocks", []), *item.get("watch_stocks", [])])[:6]
        target["confirm_rules"] = unique([*target.get("confirm_rules", []), *item.get("confirm_rules", [])])[:4]
        target["invalidate_rules"] = unique([*target.get("invalidate_rules", []), *item.get("invalidate_rules", [])])[:3]
    return list(merged.values())


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
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
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

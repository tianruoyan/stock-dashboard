#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from update_intraday_market import fetch_indices, fetch_industries, fetch_watchlist_quotes, latest_quote_time
from premarket_external import refresh as refresh_external, HK, fetch_quotes, tencent_row
from market_sentiment import sentiment_payload
from intraday_structure import collect as collect_structure, apply_facts as apply_structure_facts


TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_V2_CALENDAR = Path(
    "/Users/sweet_orange/Documents/投资/worktrees/stock-dashboard-v2/config/v2-market-calendar.json"
)
DEFAULT_V2_ENVIRONMENT = Path(
    "/Users/sweet_orange/Documents/投资/worktrees/stock-dashboard-v2/data/v2/v22/market-environment.json"
)
STATUS_PATH = ROOT / "logs" / "stage-fallback-status.json"


def now_iso(value: datetime) -> str:
    return value.astimezone(TZ).replace(microsecond=0).isoformat()


def signal_date(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if match:
        return match.group(0)
    compact = re.search(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?:\d{4,6})?(?!\d)", text)
    return "-".join(compact.groups()[:3]) if compact else ""


def parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=TZ)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validated = json.loads(tmp.read_text(encoding="utf-8"))
    if not isinstance(validated, dict):
        raise RuntimeError(f"{path.name} 根节点不是对象")
    tmp.replace(path)


def cn_calendar(root: Path, preferred: Path | None = None) -> dict[str, Any]:
    candidates = [preferred, DEFAULT_V2_CALENDAR, root / "config" / "cn-market-calendar.json"]
    for path in candidates:
        if path is None or not path.exists():
            continue
        payload = read_json(path)
        if isinstance(payload.get("calendars"), list):
            for item in payload["calendars"]:
                if isinstance(item, dict) and item.get("market") == "CN":
                    return item
        if payload.get("verification_state") == "verified":
            return payload
    return {}


def is_trading_day(root: Path, now: datetime, preferred_calendar: Path | None = None) -> bool:
    calendar = cn_calendar(root, preferred_calendar)
    if calendar.get("verification_state") != "verified":
        return False
    day = now.astimezone(TZ).date().isoformat()
    if not (str(calendar.get("valid_from") or "") <= day <= str(calendar.get("valid_to") or "")):
        return False
    holidays = set(calendar.get("holidays") or [])
    extra_open = set(calendar.get("extra_open_days") or [])
    weekends = set(calendar.get("weekend_days") or [5, 6])
    if now.astimezone(TZ).weekday() in weekends:
        return day in extra_open
    return day not in holidays


def current_payload(payload: dict[str, Any], day: str) -> bool:
    return signal_date(payload.get("timestamp")) == day and str(payload.get("trade_date") or day) == day


def stage_rank(payload: dict[str, Any]) -> int:
    ranks = {"08:30": 1, "09:00": 2}
    rank = 0
    for item in payload.get("stage_updates") or []:
        if isinstance(item, dict):
            rank = max(rank, ranks.get(str(item.get("stage") or ""), 0))
    phase = str(payload.get("phase") or "")
    if "09:00" in phase:
        rank = max(rank, 2)
    elif "08:30" in phase:
        rank = max(rank, 1)
    return rank


def has_same_day_quote(value: Any, day: str) -> bool:
    if isinstance(value, dict):
        if signal_date(value.get("quote_time") or value.get("timestamp") or value.get("as_of")) == day:
            return True
        return any(has_same_day_quote(item, day) for item in value.values())
    if isinstance(value, list):
        return any(has_same_day_quote(item, day) for item in value)
    return False


def premarket_skeleton(now: datetime, stage: str) -> dict[str, Any]:
    day = now.date().isoformat()
    stage_text = "08:30竞价前强制落盘" if stage == "08:30" else "09:00盘前增量更新"
    hk_status = "港股竞价尚未取得可核验报价，等待验证"
    a_status = "A股集合竞价尚未开始，等待09:15后验证"
    return {
        "date": day,
        "trade_date": day,
        "timestamp": now_iso(now),
        "analysis_time": now_iso(now),
        "market_time": now_iso(now),
        "phase": stage_text,
        "status": "waiting_preopen_validation",
        "data_status": "waiting_validation_0830" if stage == "08:30" else "waiting_validation_0900",
        "summary": f"{stage}盘前版本已按时写入；{hk_status}；{a_status}。未沿用上一交易日行情或结论。",
        "strategy": [
            "事实：当前仅确认当日为A股交易日，港股与A股竞价事实等待实时行情验证。",
            "推断：竞价数据到位前不预设进攻、分化或防御风格。",
            "行动：09:00增量复核港股盘前状态，09:15后再核验A股集合竞价。",
        ],
        "market_context": {
            "as_of": now_iso(now),
            "status": "waiting_preopen_validation",
            "facts": [f"{day}已由已验证交易所日历确认是A股交易日。"],
            "inference": "没有竞价事实时不使用旧日价格推导当日方向。",
            "action": "等待港股和A股竞价报价后再更新。",
        },
        "us_overnight": {
            "status": "等待外部市场事实核验",
            "indices": [],
            "tech_stocks": [],
            "japan_korea": {
                "status": "等待实时行情验证",
                "indices": [],
                "stocks": [],
                "note": "未取得本轮可核验报价，不沿用旧值。",
            },
            "hot_sectors": [],
            "weak_sectors": [],
            "conclusion": "外部市场映射等待验证。",
        },
        "hk_auction": {
            "window": stage,
            "status": "等待验证",
            "indices": [],
            "sectors": [],
            "stocks": [],
            "sentiment": hk_status,
        },
        "overnight_news": [],
        "a_share_mapping": [],
        "strong_lines": [],
        "watch_lines": ["港股竞价、A股集合竞价、指数与观察池代表股的同向性。"],
        "risk_lines": ["竞价事实到位前禁止沿用旧值或把外盘叙事直接映射为A股结论。"],
        "opening_plan": ["09:00增量更新；09:15后按实际竞价验证；数据缺失时继续明确等待。"],
        "action_conditions": ["只有当日行情时间、来源和代表股涨跌幅完整后，才形成方向性判断。"],
        "invalidation_conditions": ["任一行情日期不是当日，或报价仍停留在未开市状态。"],
        "sources": ["V2已验证A股交易日历"],
        "source_notes": ["本地阶段守卫只负责当日文件与等待边界，不生成未经核验的市场事实。"],
        "stage_updates": [],
        "generation_mode": "automatic_stage_guard",
        "data_boundary": "不交易、不修改用户资产、不改变V2生产状态；未开始或未取得报价的市场明确写等待验证。",
    }


def ensure_premarket(root: Path, now: datetime, stage: str) -> bool:
    path = root / "data" / "premarket.json"
    day = now.date().isoformat()
    wanted_rank = 1 if stage == "08:30" else 2
    existing = read_json(path)
    if current_payload(existing, day) and stage_rank(existing) >= wanted_rank:
        return False

    if current_payload(existing, day):
        payload = dict(existing)
        defaults = premarket_skeleton(now, stage)
        for key, value in defaults.items():
            payload.setdefault(key, value)
    else:
        payload = premarket_skeleton(now, stage)

    updates = [
        item
        for item in payload.get("stage_updates") or []
        if isinstance(item, dict) and item.get("stage") not in {stage}
    ]
    updates.append(
        {
            "stage": stage,
            "timestamp": now_iso(now),
            "status": "waiting_validation",
            "note": "当日文件已落盘；没有可核验竞价事实的字段保持等待验证。",
        }
    )
    payload.update(
        {
            "date": day,
            "trade_date": day,
            "timestamp": now_iso(now),
            "analysis_time": now_iso(now),
            "market_time": now_iso(now),
            "phase": "08:30竞价前强制落盘" if stage == "08:30" else "09:00盘前增量更新",
            "data_status": "waiting_validation_0830" if stage == "08:30" else "waiting_validation_0900",
            "stage_updates": updates,
            "generation_mode": "automatic_stage_guard",
        }
    )
    if stage == "09:00":
        hk = payload.get("hk_auction") if isinstance(payload.get("hk_auction"), dict) else {}
        if has_same_day_quote(hk, day):
            hk["window"] = "09:00"
            hk["status"] = "当日行情已验证"
            payload.setdefault("source_notes", []).append("09:00阶段保留已存在的当日可核验港股报价。")
        else:
            payload["summary"] = (
                "09:00已在08:30版本上完成增量更新时间；港股竞价与A股集合竞价仍须以当日实时报价验证，"
                "未取得事实的字段继续等待，不沿用旧值。"
            )
            hk.update(
                {
                    "window": "09:00",
                    "status": "等待验证",
                    "indices": [],
                    "sectors": [],
                    "stocks": [],
                    "sentiment": "09:00港股盘前窗口已到，尚无本轮可核验竞价报价；等待验证。",
                }
            )
        payload["hk_auction"] = hk
    write_json_atomic(path, payload)
    return True


def validate_close_indices(indices: list[dict[str, Any]], now: datetime) -> None:
    day = now.date()
    if len(indices) < 4:
        raise RuntimeError(f"收盘指数不完整：{len(indices)}/5")
    for item in indices:
        quote_at = parse_datetime(item.get("quote_time"))
        if quote_at is None or quote_at.date() != day or quote_at.time() < time(15, 0):
            raise RuntimeError(f"{item.get('name') or item.get('code')}不是当日收盘行情")
        if item.get("value") is None or item.get("change_pct") is None:
            raise RuntimeError(f"{item.get('name') or item.get('code')}缺少收盘值或涨跌幅")


def current_watchlist_rows(payload: dict[str, Any], day: str) -> list[dict[str, Any]]:
    rows = []
    for item in payload.get("stocks") or []:
        if not isinstance(item, dict):
            continue
        if signal_date(item.get("quote_time")) != day:
            continue
        if item.get("price") is None or item.get("change_pct") is None:
            continue
        if not item.get("code") or not item.get("name") or not item.get("source"):
            continue
        rows.append(item)
    return rows


def v2_same_day_facts(path: Path, day: str) -> dict[str, Any]:
    payload = read_json(path)
    if str(payload.get("trade_date") or "") != day or signal_date(payload.get("as_of")) != day:
        return {"status": "unavailable", "facts": [], "breadth": {}}
    facts = []
    breadth: dict[str, int] = {}
    patterns = {
        "advance_count": r"上涨\s*(\d+)\s*家",
        "decline_count": r"下跌\s*(\d+)\s*家",
        "flat_count": r"平盘\s*(\d+)\s*家",
        "limit_up_count": r"涨停\s*(\d+)\s*只",
        "limit_down_count": r"跌停\s*(\d+)\s*只",
        "highest_limit_streak": r"最高连板\s*(\d+)\s*板",
    }
    for dimension in payload.get("dimensions") or []:
        if not isinstance(dimension, dict) or signal_date(dimension.get("as_of")) != day:
            continue
        dimension_time = parse_datetime(dimension.get("as_of"))
        if dimension_time is None or dimension_time.time() < time(15):
            continue
        fact_rows = [str(item) for item in dimension.get("fact_summary") or [] if str(item).strip()]
        if fact_rows:
            facts.append(
                {
                    "dimension_code": dimension.get("dimension_code"),
                    "label": dimension.get("label"),
                    "conclusion": dimension.get("conclusion"),
                    "facts": fact_rows,
                    "quality_state": dimension.get("quality_state"),
                    "as_of": dimension.get("as_of"),
                    "source": "V2 shadow同日市场环境事实",
                }
            )
        joined = " ".join(fact_rows)
        for key, pattern in patterns.items():
            match = re.search(pattern, joined)
            if match:
                breadth[key] = int(match.group(1))
    return {"status": "current" if facts else "unavailable", "facts": facts, "breadth": breadth}


def index_summary(indices: list[dict[str, Any]], turnover: float) -> str:
    parts = [f"{item['name']}{float(item['change_pct']):+.2f}%" for item in indices]
    return "、".join(parts) + f"；两市成交额按上证与深证成指口径估算约{turnover:.2f}亿元。"


def representative_evidence(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "representative_stock",
        "name": row["name"],
        "code": row["code"],
        "metric": "pct",
        "value": row["change_pct"],
        "price": row["price"],
        "source": row["source"],
        "timestamp": row["quote_time"],
        "detail": f"{row['name']} {row['code']} {float(row['change_pct']):+.2f}%，价格{row['price']}。",
    }


def postmarket_complete(payload: dict[str, Any], day: str) -> bool:
    if not current_payload(payload, day):
        return False
    required = ("index", "market_breadth", "sentiment_indicator", "review", "closing_auction_patch")
    if any(not isinstance(payload.get(key), dict) for key in required):
        return False
    if not isinstance(payload.get("hotspots"), list) or not isinstance(payload.get("next_day_watch"), list):
        return False
    patch = payload.get("closing_auction_patch") or {}
    if any(not patch.get(key) for key in ("summary", "signals", "impact", "watch_next_day")):
        return False
    if not (payload.get("review") or {}).get("evidence"):
        return False
    indices = (payload.get("index") or {}).get("a_share_indices") or []
    if len(indices) < 4:
        return False
    for item in indices:
        if not isinstance(item, dict):
            return False
        quote_at = parse_datetime(item.get("quote_time"))
        if quote_at is None or quote_at.date().isoformat() != day or quote_at.time() < time(15, 0):
            return False
        if item.get("value") is None or item.get("change_pct") is None or not item.get("source"):
            return False
    return True


def build_postmarket_payload(
    root: Path,
    now: datetime,
    v2_environment: Path = DEFAULT_V2_ENVIRONMENT,
) -> dict[str, Any]:
    day = now.date().isoformat()
    indices = fetch_indices()
    validate_close_indices(indices, now)
    industries = fetch_industries()
    industries = [item for item in industries if signal_date(item.get("quote_time")) == day]
    watchlist = fetch_watchlist_quotes(root / "config" / "watchlist.json")
    watch_rows = current_watchlist_rows(watchlist, day)
    write_json_atomic(root / "data" / "watchlist-quotes.json", watchlist)

    ranked = sorted(industries, key=lambda item: float(item.get("change_pct") or 0), reverse=True)
    top5 = ranked[:5]
    bottom5 = sorted(industries, key=lambda item: float(item.get("change_pct") or 0))[:5]
    turnover = round(
        sum(float(item.get("amount_yi") or 0) for item in indices if item.get("code") in {"sh000001", "sz399001"}),
        2,
    )
    quote_as_of = latest_quote_time(indices).isoformat(timespec="seconds")
    v2 = v2_same_day_facts(v2_environment, day)
    breadth = dict(v2.get("breadth") or {})
    breadth.update(
        {
            "status": "current_v2_shadow_facts" if v2.get("status") == "current" else "same_day_width_unavailable",
            "turnover_yi_estimate": turnover,
            "source": "V2 shadow同日市场环境事实与V1腾讯收盘行情",
            "as_of": quote_as_of,
            "note": (
                "仅使用V2 shadow同日事实补充宽度；缺失字段保持未知。"
                if v2.get("status") == "current"
                else "V2 shadow没有当日市场环境事实，宽度与涨跌停结构不补造。"
            ),
            "policy": "V2只作同日事实补证，不改变V1生产地位。",
        }
    )
    structure = collect_structure(now=now)
    current_breadth = structure.get("breadth")
    if current_breadth and parse_datetime(current_breadth.get("as_of")).time() >= time(15):
        for key in ("advance_count", "decline_count", "flat_count", "total_count", "missing_quote_count"):
            breadth[key] = current_breadth[key]
        breadth["breadth_as_of"] = current_breadth["as_of"]
        breadth["breadth_source"] = current_breadth["source_name"]
    for pool_name, target in (("limit_up", "limit_up_count"), ("limit_down", "limit_down_count"), ("broken_board", "broken_board_count")):
        pool = structure.get("pools", {}).get(pool_name)
        if pool:
            breadth[target] = pool["count"]
    if "limit_up_count" in breadth:
        breadth["effective_limit_up_count"] = breadth["limit_up_count"]
    breadth["as_of"] = None
    breadth["source"] = "各项统计按各自来源及时间记录"
    positive = sorted(watch_rows, key=lambda item: float(item["change_pct"]), reverse=True)[:3]
    negative = sorted(watch_rows, key=lambda item: float(item["change_pct"]))[:3]
    evidence = [
        {
            "type": "price_action",
            "metric": "pct",
            "value": item["change_pct"],
            "source": item["source"],
            "timestamp": item["quote_time"],
            "detail": f"{item['name']}收盘{float(item['change_pct']):+.2f}%，报{item['value']}。",
        }
        for item in indices
    ]
    evidence.extend(representative_evidence(item) for item in positive + negative)
    top_names = "、".join(item["name"] for item in top5[:3]) or "行业前排待补"
    bottom_names = "、".join(item["name"] for item in bottom5[:3]) or "行业后排待补"
    hotspots = [
        {
            "name": f"行业相对强势：{top_names}",
            "type": "watch_line",
            "status": "今天相对强，下一交易日再看能否继续上涨",
            "evidence": [
                {
                    "type": "price_action",
                    "metric": "sector_pct",
                    "value": item["change_pct"],
                    "source": item["source"],
                    "timestamp": item["quote_time"],
                    "detail": f"行业{item['name']} {float(item['change_pct']):+.2f}%。",
                }
                for item in top5
            ],
            "continuity": "只有当日收盘行业排名，不用单日排名替代连续性证据。",
            "risk": "还需核实是否有共同的消息或订单带动；少数股票上涨，不代表整个方向都值得追。",
            "action": "次日先看行业宽度和代表股承接，不追高。",
            "confirm": "行业继续前排且至少两类代表股同向扩散。",
            "invalidate": "行业排名快速回落或仅少数高标维持。",
            "stocks": [],
        },
        {
            "name": f"行业相对弱势：{bottom_names}",
            "type": "risk_line",
            "status": "当日收盘行业排名居后",
            "evidence": [
                {
                    "type": "price_action",
                    "metric": "sector_pct",
                    "value": item["change_pct"],
                    "source": item["source"],
                    "timestamp": item["quote_time"],
                    "detail": f"行业{item['name']} {float(item['change_pct']):+.2f}%。",
                }
                for item in bottom5
            ],
            "continuity": "只有当日收盘行业排名，次日需重新确认是否延续。",
            "risk": "弱势行业若继续低开且无核心修复，风险可能扩散。",
            "action": "次日等待行业和代表股同步止跌。",
            "confirm": "行业跌幅收窄并出现有成交支持的代表股修复。",
            "invalidate": "继续位于行业跌幅前排。",
            "stocks": [],
        },
    ]
    close_map = {
        item["name"]: {
            "price": item["value"],
            "pct": item["change_pct"],
            "quote_time": item["quote_time"],
            "source": item["source"],
            "status": item["status"],
        }
        for item in indices
    }
    summary = index_summary(indices, turnover)
    status = "usable_postmarket_fallback" if v2.get("status") == "current" else "degraded_postmarket_fallback_width_unavailable"
    return {
        "date": day,
        "trade_date": day,
        "timestamp": now_iso(now),
        "updated_at": now_iso(now),
        "generated_at": now_iso(now),
        "analysis_time": now_iso(now),
        "analysis_as_of": quote_as_of,
        "phase": "A股收盘复盘" if now.time() < time(16, 30) else "收盘复盘",
        "status": status,
        "quality_state": "usable" if v2.get("status") == "current" else "degraded",
        "quality_summary": "收盘指数、行业与观察池行情为当日可核验事实；V2同日宽度缺失时保持降级。",
        "source_mode": "automatic_1630_close_fallback",
        "summary": summary,
        "index": {
            "summary": summary,
            "a_share_indices": indices,
            "snapshot_time": quote_as_of,
            "a_share_turnover_yi_estimate": turnover,
            "industry_top5": top5,
            "industry_bottom5": bottom5,
        },
        "market_breadth": breadth,
        "market_structure_facts": structure,
        "review": {
            "one_sentence": summary,
            "summary": summary,
            "evidence": evidence,
            "facts": [summary, f"行业相对前排为{top_names}；相对后排为{bottom_names}。"],
            "inference": "行业排名只说明当日相对强弱，不自动等于可持续主线。",
            "action": "次日以行业宽度、代表股承接和成交延续共同验证。",
        },
        "hotspots": hotspots,
        "next_day_watch": [
            f"强势行业：{top_names}的宽度、成交和代表股承接。",
            f"弱势行业：{bottom_names}能否止跌。",
            "观察池强弱代表是否与行业结构同向，不用个股替代板块结论。",
        ],
        "next_day_watch_details": [
            {
                "theme": "收盘结构延续",
                "action": "只观察，不自动交易。",
                "confirm": "行业与至少两类代表股同向，成交保持。",
                "invalidate": "高开低走、后排不扩散或行情源日期异常。",
            }
        ],
        "primary_action": "下一交易日先看强势方向能否延续，条件不足不追高。",
        "closing_auction_patch": {
            "summary": "已保存A股收盘行情；尚未取得完整尾盘走势，不能判断是否尾盘抢筹或集中卖出。",
            "snapshot_1500": {"timestamp": quote_as_of, "indices": close_map, "note": "当日可核验收盘快照。"},
            "signals": ["主要指数收盘事实已保存。", "缺少的14:30历史快照未补造。"],
            "impact": "下一交易日先看多数股票是否止跌，再看强势股能否继续上涨。",
            "watch_next_day": ["开盘后能否稳住、同板块是否有更多股票上涨、自选股是否跟上。"],
            "snapshot_1432": None,
            "deviation": None,
            "tail_28min": {"direction": "unknown", "note": "缺少当日连续尾盘快照，不计算。"},
            "representative_changes": [],
            "auction_reversal_stocks": [],
        },
        "sentiment_indicator": sentiment_payload(indices, breadth),
        "risk": [
            "如果多数股票仍在下跌，少数个股上涨不能视为全市场回暖。",
            "缺少完整尾盘走势时，不能仅凭收盘价格判断是否有资金抢筹。",
        ],
        "sources": [
            "腾讯财经HTTP：当日指数、行业及观察池收盘行情。",
            "V2 shadow：仅在trade_date与as_of均为当日时补充市场环境事实。",
        ],
        "automation_fallback_notes": [
            "15:10起检查A股收盘复盘，16:30起独立补充港股收盘；网络恢复后重试。",
            "统一发布器负责构建、审计、提交和推送。",
        ],
        "v2_shadow_facts": v2.get("facts") or [],
        "data_boundary": "只使用当日可核验收盘事实和V2同日事实；不补造错过的盘前、午盘或尾盘历史；V2保持shadow。",
        "disclaimer": "仅用于市场事实归档与次日验证，不构成投资建议。",
    }


def ensure_postmarket(root: Path, now: datetime, v2_environment: Path = DEFAULT_V2_ENVIRONMENT) -> bool:
    path = root / "data" / "postmarket.json"
    day = now.date().isoformat()
    if postmarket_complete(read_json(path), day):
        return False
    payload = build_postmarket_payload(root, now, v2_environment)
    write_json_atomic(path, payload)
    return True


def refresh_close_structure(root: Path, now: datetime, *, force: bool = False) -> bool:
    path = root / "data/postmarket.json"
    original = read_json(path)
    if not postmarket_complete(original, now.date().isoformat()):
        return False
    checked = parse_datetime((original.get("market_structure_facts") or {}).get("collected_at"))
    if not force and checked and timedelta(0) <= now - checked < timedelta(minutes=15):
        return False
    facts = collect_structure(now=now)
    # Network requests may overlap an authored review. Merge facts into the latest version.
    payload = read_json(path)
    if not postmarket_complete(payload, now.date().isoformat()):
        return False
    breadth = payload.setdefault("market_breadth", {})
    row = facts.get("breadth")
    if row and parse_datetime(row.get("as_of")).time() >= time(15):
        for key in ("advance_count", "decline_count", "flat_count", "total_count", "missing_quote_count"):
            breadth[key] = row[key]
        breadth["breadth_as_of"] = row["as_of"]
        breadth["breadth_source"] = row["source_name"]
    for pool_name, target in (("limit_up", "limit_up_count"), ("limit_down", "limit_down_count"), ("broken_board", "broken_board_count")):
        pool = facts.get("pools", {}).get(pool_name)
        if pool:
            breadth[target] = pool["count"]
            breadth[target + "_as_of"] = pool["as_of"]
    if "limit_up_count" in breadth:
        breadth["effective_limit_up_count"] = breadth["limit_up_count"]
    breadth["as_of"] = None
    payload["market_structure_facts"] = facts
    payload["sentiment_indicator"] = sentiment_payload(payload["index"]["a_share_indices"], breadth)
    payload["sentiment_indicator_as_of"] = now_iso(now)
    breadth["status"] = "收盘统计已更新" if not facts.get("errors") else "部分收盘统计等待更新"
    breadth["note"] = (f"{breadth['missing_quote_count']}只暂无有效报价，未计入涨跌家数。"
                       if breadth.get("missing_quote_count") else "各项按已取得的收盘统计展示。")
    breadth["source"] = "各项统计按各自来源及时间记录"
    if payload.get("source_mode") == "automatic_1630_close_fallback":
        payload["risk"] = ["如果多数股票仍在下跌，少数个股上涨不能视为全市场回暖。", "缺少完整尾盘走势时，不能仅凭收盘价格判断是否有资金抢筹。"]
        payload["closing_auction_patch"]["impact"] = "下一交易日先看多数股票是否止跌，再看强势股能否继续上涨。"
    write_json_atomic(path, payload)
    intraday_path = root / "data/intraday.json"
    intraday = read_json(intraday_path)
    quote_at = parse_datetime(intraday.get("market_data_as_of"))
    if quote_at and quote_at.date() == now.date() and quote_at.time() >= time(15):
        apply_structure_facts(intraday, facts)
        write_json_atomic(intraday_path, intraday)
    return True


def refresh_hk_close(root: Path, now: datetime) -> bool:
    """Append closing facts without rewriting the original A-share judgement."""
    path = root / "data" / "postmarket.json"
    payload = read_json(path)
    if not current_payload(payload, now.date().isoformat()):
        return False
    previous = payload.get("hk_close_followup") or {}
    if previous.get("complete"):
        return False
    rows, missing = [], []
    for code in HK:
        try:
            raw = fetch_quotes([code])
            row = tencent_row(raw[0], now)
            at = parse_datetime(row["quote_time"])
            if at is None or at.time() < time(16):
                raise ValueError("收盘报价尚未返回")
            rows.append(row)
        except Exception:
            missing.append(HK[code])
    if not rows:
        return False
    followup = {"timestamp": now_iso(now), "complete": not missing, "quotes": rows,
                "summary": "；".join(f"{r['name']}{r['change_pct']:+.2f}%" for r in rows),
                "note": "港股收盘补充，不改写A股收盘时的判断。" + ("待补：" + "、".join(missing) if missing else "")}
    if previous.get("quotes") == rows:
        return False
    payload["hk_close_followup"] = followup
    write_json_atomic(path, payload)
    return True


def due_stage(now: datetime) -> str | None:
    current = now.astimezone(TZ).time()
    if current < time(8, 30):
        return None
    if current < time(9, 0):
        return "premarket-0830"
    if current < time(15, 10):
        return "premarket-0900"
    if current < time(16, 30):
        return "postmarket-1510"
    return "postmarket-1630"


def health_ok(root: Path, stage: str, day: str) -> bool:
    payload = read_json(root / "data" / "automation-health.json")
    target = "postmarket" if stage.startswith("postmarket-") else "premarket"
    if signal_date(payload.get("timestamp")) != day:
        return False
    for item in payload.get("processes") or []:
        if isinstance(item, dict) and item.get("id") == target:
            return item.get("status") == "ok" and signal_date(item.get("timestamp")) == day
    return False


def run_command(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def execute(
    root: Path,
    now: datetime,
    stage: str | None = None,
    publish: bool = True,
    calendar_path: Path | None = None,
    v2_environment: Path = DEFAULT_V2_ENVIRONMENT,
) -> dict[str, Any]:
    now = now.astimezone(TZ)
    day = now.date().isoformat()
    if not is_trading_day(root, now, calendar_path):
        return {"state": "non_trading_day", "date": day, "written": False, "published": False}
    selected = stage or due_stage(now)
    if selected is None:
        return {"state": "not_due", "date": day, "written": False, "published": False}

    if selected == "premarket-0830":
        written = ensure_premarket(root, now, "08:30")
    elif selected == "premarket-0900":
        if not current_payload(read_json(root / "data" / "premarket.json"), day):
            ensure_premarket(root, now, "08:30")
        written = ensure_premarket(root, now, "09:00")
    elif selected in {"postmarket-1510", "postmarket-1630"}:
        written = ensure_postmarket(root, now, v2_environment)
        written = refresh_close_structure(root, now) or written
        if selected == "postmarket-1630":
            written = refresh_hk_close(root, now) or written
    else:
        raise RuntimeError(f"未知阶段：{selected}")

    if selected.startswith("premarket-"):
        # A dated skeleton is not collected evidence. Retry independently of stage rank.
        written = refresh_external(root, now) or written

    should_publish = publish and (written or not health_ok(root, selected, day))
    published = False
    if should_publish:
        result = run_command([str(root / "scripts" / "publish_dashboard.sh")], root)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "统一发布器失败").strip()
            raise RuntimeError(detail)
        if not health_ok(root, selected, day):
            raise RuntimeError("统一发布器完成后 automation-health 未识别为当日状态")
        published = True
    return {
        "state": "updated" if written else "already_complete",
        "stage": selected,
        "date": day,
        "written": written,
        "published": published,
        "automation_health_current": health_ok(root, selected, day) if publish else None,
    }


def write_status(root: Path, payload: dict[str, Any], now: datetime) -> None:
    status = dict(payload)
    status["checked_at"] = now_iso(now)
    write_json_atomic(root / "logs" / "stage-fallback-status.json", status)


def main() -> int:
    parser = argparse.ArgumentParser(description="V1盘前08:30/09:00、A股收盘15:10与港股收盘16:30补充")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--now", help="测试或人工补跑时间，ISO 8601")
    parser.add_argument(
        "--stage",
        choices=("premarket-0830", "premarket-0900", "postmarket-1510", "postmarket-1630"),
        help="显式阶段；默认按北京时间自动选择",
    )
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--calendar", type=Path)
    parser.add_argument("--v2-environment", type=Path, default=DEFAULT_V2_ENVIRONMENT)
    args = parser.parse_args()
    root = args.root.resolve()
    now = parse_datetime(args.now) if args.now else datetime.now(TZ)
    if now is None:
        raise SystemExit("--now 必须是有效ISO时间")
    try:
        result = execute(
            root,
            now,
            stage=args.stage,
            publish=not args.no_publish,
            calendar_path=args.calendar,
            v2_environment=args.v2_environment,
        )
    except Exception as exc:
        result = {"state": "failed", "error": str(exc), "date": now.date().isoformat()}
        write_status(root, result, now)
        print(json.dumps(result, ensure_ascii=False))
        return 1
    write_status(root, result, now)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

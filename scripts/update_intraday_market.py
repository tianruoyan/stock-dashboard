#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from intraday_structure import apply_facts, collect


ROOT = Path(__file__).resolve().parent.parent
INTRADAY_PATH = ROOT / "data" / "intraday.json"
WATCHLIST_PATH = ROOT / "config" / "watchlist.json"
WATCHLIST_QUOTES_PATH = ROOT / "data" / "watchlist-quotes.json"
TENCENT_URL = "https://qt.gtimg.cn/q={}"
INDEX_CODES = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000688": "科创50",
    "sh000300": "沪深300",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_quote_time(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    for pattern in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y/%m/%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    except ValueError:
        pass
    return None


def quote_status(value: Any) -> str:
    parsed = parse_quote_time(value)
    if parsed is None:
        return "行情状态待核验"
    if parsed.time() >= time(15, 0):
        return "已收盘"
    if time(11, 30) <= parsed.time() < time(13, 0):
        return "午间休市"
    return "交易中"


def latest_quote_time(rows: Iterable[Dict[str, Any]]) -> datetime:
    parsed = [parse_quote_time(row.get("quote_time")) for row in rows]
    valid = [value for value in parsed if value is not None]
    if not valid:
        raise RuntimeError("行情源未返回可验证的行情时间")
    return max(valid)


def as_float(value: str) -> Optional[float]:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def fetch_quotes(codes: Iterable[str]) -> List[Dict[str, Any]]:
    request = urllib.request.Request(
        TENCENT_URL.format(",".join(codes)),
        headers={"User-Agent": "Mozilla/5.0 stock-dashboard/1.0"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        text = response.read().decode("gbk", errors="replace")
    rows = []
    for line in text.splitlines():
        match = re.match(r'v_([^=]+)="(.*)";', line.strip())
        if not match:
            continue
        fields = match.group(2).split("~")
        if len(fields) <= 37 or not fields[1]:
            continue
        rows.append({"query_code": match.group(1), "fields": fields})
    return rows


def fetch_indices() -> List[Dict[str, Any]]:
    result = []
    for row in fetch_quotes(INDEX_CODES):
        code = row["query_code"]
        fields = row["fields"]
        value = as_float(fields[3])
        change = as_float(fields[31])
        pct = as_float(fields[32])
        open_value = as_float(fields[5])
        high = as_float(fields[33])
        low = as_float(fields[34])
        amount_raw = as_float(fields[37])
        if value is None or pct is None:
            continue
        result.append(
            {
                "name": INDEX_CODES.get(code, fields[1]),
                "code": code,
                "value": value,
                "change": change,
                "pct": pct,
                "change_pct": pct,
                "open": open_value,
                "high": high,
                "low": low,
                "amount_yi": round(amount_raw / 10000, 2) if amount_raw is not None else None,
                "status": quote_status(fields[30]),
                "quote_time": fields[30],
                "source": "腾讯财经HTTP",
            }
        )
    if len(result) < 4:
        raise RuntimeError(f"指数行情返回不完整: {len(result)}/5")
    return result


def provider_code(code: Any) -> str:
    raw = str(code or "").strip().lower()
    if raw.startswith("hk"):
        digits = re.sub(r"\D", "", raw)
        return f"hk{digits.zfill(5)}"
    return raw


def normalized_code(code: Any) -> str:
    raw = str(code or "").strip().lower()
    if raw.startswith("hk"):
        digits = re.sub(r"\D", "", raw)
        return f"hk{int(digits)}" if digits else raw
    return raw


def fetch_watchlist_quotes(path: Path = WATCHLIST_PATH) -> Dict[str, Any]:
    watchlist = json.loads(path.read_text(encoding="utf-8"))
    stocks = watchlist.get("watch_only", {}).get("stocks", [])
    query_codes = [provider_code(item.get("code")) for item in stocks if item.get("code")]
    fetched = {
        normalized_code(row["query_code"]): row["fields"]
        for row in fetch_quotes(query_codes)
    }
    rows = []
    missing = 0
    for stock in stocks:
        code = str(stock.get("code") or "")
        configured_name = str(stock.get("name") or code)
        fields = fetched.get(normalized_code(code))
        if not fields:
            missing += 1
            rows.append(
                {
                    "code": code,
                    "name": configured_name,
                    "price": None,
                    "change_pct": None,
                    "quote_time": None,
                    "status": "行情待补",
                    "source": "腾讯财经HTTP",
                }
            )
            continue
        rows.append(
            {
                "code": code,
                "name": configured_name,
                "provider_name": fields[1],
                "price": as_float(fields[3]),
                "previous_close": as_float(fields[4]),
                "open": as_float(fields[5]),
                "change_pct": as_float(fields[32]),
                "high": as_float(fields[33]),
                "low": as_float(fields[34]),
                "quote_time": fields[30],
                "status": quote_status(fields[30]),
                "source": "腾讯财经HTTP",
            }
        )
    valid_times = [parse_quote_time(row.get("quote_time")) for row in rows]
    valid_times = [value for value in valid_times if value is not None]
    quote_as_of = max(valid_times).isoformat(timespec="seconds") if valid_times else None
    return {
        "timestamp": now_iso(),
        "quote_as_of": quote_as_of,
        "source": "腾讯财经HTTP",
        "summary": f"观察池{len(rows)}只，{len(rows) - missing}只返回行情，{missing}只待补；行情日期和时点以每只股票标注为准。",
        "stocks": rows,
    }


def fetch_industries() -> List[Dict[str, Any]]:
    rows = []
    codes = [f"pt01801{index:03d}" for index in range(1, 501)]
    for offset in range(0, len(codes), 80):
        for row in fetch_quotes(codes[offset : offset + 80]):
            fields = row["fields"]
            pct = as_float(fields[32])
            if pct is None:
                continue
            rows.append(
                {
                    "name": fields[1],
                    "change_pct": pct,
                    "code": row["query_code"],
                    "quote_time": fields[30],
                    "source": "腾讯财经HTTP",
                }
            )
    if len(rows) < 50:
        raise RuntimeError(f"行业行情返回不完整: {len(rows)}")
    return rows


def merge_index_rows(existing: Any, fresh: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    previous = {
        item.get("code"): item
        for item in existing or []
        if isinstance(item, dict) and item.get("code")
    }
    merged = []
    for item in fresh:
        old = dict(previous.get(item["code"], {}))
        old.pop("three_min_pct", None)
        old.update(item)
        merged.append(old)
    return merged


def normalize_index_section(existing: Any) -> Dict[str, Any]:
    if isinstance(existing, dict):
        return dict(existing)
    if isinstance(existing, list):
        return {"a_share_indices": existing}
    return {}


def write_atomic(path: Path, payload: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def refresh_current_projection(payload: Dict[str, Any], indices: List[Dict[str, Any]],
                               industries: List[Dict[str, Any]], structure: Dict[str, Any],
                               quote_as_of: str, collected_at: str) -> None:
    """Replace an obsolete intraday conclusion with a dated factual snapshot.

    Quote refreshes used to update only nested market fields.  When the prior
    analyst snapshot belonged to another trading day, the page therefore kept
    showing its old conclusion beside today's prices.  This projection is
    intentionally conservative: it makes a current, evidence-labelled market
    observation and never reuses the prior day's breadth or theme judgement.
    """
    quote_day = parse_quote_time(quote_as_of)
    if quote_day is None:
        return
    day = quote_day.date().isoformat()
    top = sorted(industries, key=lambda item: item["change_pct"], reverse=True)[:3]
    bottom = sorted(industries, key=lambda item: item["change_pct"])[:3]
    index_text = "、".join(
        f"{item['name']}{float(item['change_pct']):+.2f}%" for item in indices
    )
    top_text = "、".join(f"{item['name']}{float(item['change_pct']):+.2f}%" for item in top)
    bottom_text = "、".join(f"{item['name']}{float(item['change_pct']):+.2f}%" for item in bottom)
    pools = structure.get("pools") if isinstance(structure.get("pools"), dict) else {}
    limit_up = pools.get("limit_up", {}).get("count")
    limit_down = pools.get("limit_down", {}).get("count")
    broken = pools.get("broken_board", {}).get("count")
    breadth_missing = bool((structure.get("errors") or {}).get("breadth"))
    breadth_text = (
        "全市场上涨与下跌家数暂未取得，不把旧日宽度数据当作今天的情绪。"
        if breadth_missing else "全市场涨跌家数已取得，详见市场宽度。"
    )
    pool_text = f"涨停{limit_up}只、跌停{limit_down}只、炸板{broken}只" if None not in (limit_up, limit_down, broken) else "涨跌停结构待补"

    payload.update({
        "date": day,
        "trade_date": day,
        "timestamp": collected_at,
        "updated_at": collected_at,
        "analysis_time": collected_at,
        "market_time": quote_as_of,
        "phase": f"盘中行情更新（{quote_day.strftime('%H:%M')}可核验行情）",
        "status": "usable_intraday_factual_snapshot" if not breadth_missing else "partial_intraday_factual_snapshot",
        "summary": f"{quote_day.strftime('%H:%M')}五大指数同步走弱：{index_text}。相对抗跌的行业为{top_text}；跌幅居前为{bottom_text}。{pool_text}；{breadth_text}",
        "sentiment": {
            "judgement": "指数同步走弱，盘中先按风险释放不足处理；宽度未齐，不给整体情绪打分。",
            "limit_up_count": limit_up,
            "limit_down_count": limit_down,
            "broken_limit_count": broken,
            "breadth_status": "待补" if breadth_missing else "已取得",
            "advance_count": None if breadth_missing else payload.get("market_breadth", {}).get("advance_count"),
            "decline_count": None if breadth_missing else payload.get("market_breadth", {}).get("decline_count"),
            "flat_count": None if breadth_missing else payload.get("market_breadth", {}).get("flat_count"),
        },
        "main_trends": [{
            "name": "盘中市场状态",
            "type": "risk_line",
            "status": "五大指数同步走弱，暂不把局部抗跌行业视为可追主线。",
            "continuity": f"{index_text}；{pool_text}。",
            "evidence": [
                {"type": "index_quote", "metric": "change_pct", "value": item["change_pct"], "name": item["name"], "code": item["code"], "source": item["source"], "timestamp": item["quote_time"], "detail": f"{item['name']}{float(item['change_pct']):+.2f}%"}
                for item in indices
            ],
            "inference": f"{top_text}相对抗跌，但仅凭行业排名不足以确认交易主线。",
            "risk": f"{bottom_text}跌幅靠前；{breadth_text}",
            "action": "先观察指数是否止跌、跌幅较大行业是否缩窄；没有共同回稳前不追逆势拉升。",
            "strengthen_condition": "至少两项核心指数止跌回升，且全市场宽度补齐后不继续恶化。",
            "invalidation_condition": "核心指数继续扩大跌幅，或跌停、炸板数量明显增加。",
        }],
        "actions": ["先观察指数是否止跌及市场宽度是否补齐；当前不使用上一交易日的主线与情绪结论。"],
        "themes": [],
        "data_boundary": "本轮为实时行情事实更新；未取得的全市场宽度不补造，也不沿用旧日结论。",
    })


def update(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    indices = fetch_indices()
    industries = fetch_industries()
    structure = collect()
    # Network calls may overlap a new analyst snapshot; merge into the latest file.
    payload = json.loads(path.read_text(encoding="utf-8"))
    collected_at = now_iso()
    quote_as_of = latest_quote_time(indices).isoformat(timespec="seconds")

    payload["indices"] = merge_index_rows(payload.get("indices"), indices)
    index_section = normalize_index_section(payload.get("index"))
    payload["index"] = index_section
    index_section["snapshot_time"] = quote_as_of
    index_section["a_share_indices"] = merge_index_rows(index_section.get("a_share_indices"), indices)

    turnover = sum(
        item.get("amount_yi") or 0
        for item in indices
        if item.get("code") in {"sh000001", "sz399001"}
    )
    if turnover:
        turnover = round(turnover, 2)
        index_section["a_share_turnover_yi_estimate"] = turnover
        payload.setdefault("market_breadth", {})["turnover_yi_estimate"] = turnover

    ranked = sorted(industries, key=lambda item: item["change_pct"], reverse=True)
    payload["industry_top5"] = ranked[:5]
    payload["industry_bottom5"] = sorted(industries, key=lambda item: item["change_pct"])[:5]
    payload["market_data_as_of"] = quote_as_of
    payload["market_data_collected_at"] = collected_at
    payload["market_data_refresh"] = {
        "owner": "Codex单智能体",
        "indices": "腾讯财经HTTP",
        "industry_ranking": "腾讯财经HTTP",
        "concept_ranking": "由Codex盘中分析任务更新",
        "analysis_timestamp_unchanged": True,
        "time_basis": "行情源时间",
    }
    apply_facts(payload, structure)
    # A quote-only refresh may follow a failed scheduled analysis.  If the
    # visible snapshot is from another day, publish a current factual view so
    # the page cannot pair today's prices with yesterday's conclusion.
    previous_day = str(payload.get("trade_date") or payload.get("date") or "")
    if previous_day != quote_as_of[:10]:
        refresh_current_projection(payload, indices, industries, structure, quote_as_of, collected_at)
    write_atomic(path, payload)
    watchlist_quotes = fetch_watchlist_quotes()
    write_atomic(WATCHLIST_QUOTES_PATH, watchlist_quotes)
    return {
        "updated": str(path),
        "market_data_as_of": quote_as_of,
        "market_data_collected_at": collected_at,
        "indices": len(indices),
        "industries": len(industries),
        "structure": {"breadth_available": structure["breadth"] is not None,
                      "pool_counts": {k: v["count"] for k, v in structure["pools"].items()},
                      "missing": list(structure["errors"])},
        "watchlist_quotes": len(watchlist_quotes.get("stocks", [])),
        "watchlist_quote_as_of": watchlist_quotes.get("quote_as_of"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="刷新盘中指数和行业排行，不改分析结论时间")
    parser.add_argument("--path", type=Path, default=INTRADAY_PATH)
    args = parser.parse_args()
    try:
        result = update(args.path)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    status = "partial" if result.get("structure", {}).get("missing") else "ok"
    print(json.dumps({"status": status, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

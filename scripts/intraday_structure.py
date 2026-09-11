"""Current public market facts only; never generates an investment judgement."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

CN = ZoneInfo("Asia/Shanghai")
SHARED_BREADTH = Path.home() / "stock-dashboard-v2-local/local_inputs/market-breadth.json"
POOLS = {
    "limit_up": ("getTopicZTPool", "fbt:asc", "limit_up_count"),
    "limit_down": ("getTopicDTPool", "fund:asc", "limit_down_count"),
    "broken_board": ("getTopicZBPool", "fbt:asc", "broken_limit_count"),
}


def current_breadth(value, now):
    """Only consume the public fact projection, not V2 conclusions or assets."""
    stamp = datetime.fromisoformat(value["as_of"])
    if stamp.tzinfo is None or value.get("trade_date") != now.date().isoformat():
        raise ValueError("市场统计日期不匹配")
    age = (now - stamp).total_seconds()
    closing_fact = now.time() >= time(15) and stamp.astimezone(CN).time() >= time(15) and age >= 0
    if stamp.astimezone(CN).date() != now.date() or (not -120 <= age <= 1200 and not closing_fact):
        raise ValueError("市场统计等待更新")
    fields = ("advance_count", "decline_count", "flat_count", "total_count", "missing_quote_count")
    if any(type(value.get(k)) is not int or value[k] < 0 for k in fields):
        raise ValueError("市场统计数量不完整")
    if sum(value[k] for k in fields[:3]) != value["total_count"] or value["total_count"] < 4000:
        raise ValueError("市场统计覆盖或合计异常")
    if value.get("quality_state") not in {"ok", "healthy", "degraded", "complete"}:
        raise ValueError("市场统计未通过来源校验")
    if not all(value.get(k) for k in ("source_name", "source_url", "scope")):
        raise ValueError("市场统计缺少来源")
    result = {k: value[k] for k in (*fields, "as_of", "trade_date", "source_name", "source_url", "scope", "quality_state")}
    result["quality_note"] = value.get("quality_note", "")
    result["ingestion_note"] = "读取共享公开行情统计；不是新增的独立行情源，也不是双源验证"
    return result


def validate_pool(value, day):
    data = value.get("data") or {}
    if value.get("rc") != 0 or str(data.get("qdate")) != day.replace("-", ""):
        raise ValueError("涨跌停统计日期不匹配")
    rows, total = data.get("pool"), data.get("tc")
    if type(total) is not int or total < 0 or not isinstance(rows, list) or len(rows) != total:
        raise ValueError("涨跌停统计返回不完整")
    codes = [row.get("c") for row in rows if isinstance(row, dict)]
    if len(codes) != total or any(not c for c in codes) or len(set(codes)) != total:
        raise ValueError("涨跌停统计存在缺项或重复")
    return total


def fetch_pool(key, now):
    endpoint, sort, _ = POOLS[key]
    params = {"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt",
              "Pageindex": 0, "pagesize": 10000, "sort": sort,
              "date": now.strftime("%Y%m%d")}
    url = "https://push2ex.eastmoney.com/" + endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as response:
        count = validate_pool(json.load(response), now.date().isoformat())
    return {"count": count, "as_of": datetime.now(CN).isoformat(timespec="seconds"),
            "trade_date": now.date().isoformat(), "source_name": "东方财富涨跌停专题",
            "source_url": url, "scope": "东方财富当日专题池，不等同于沪深京全市场统计范围",
            "time_basis": "来源交易日与实际采集时间；接口不提供逐股报价时间"}


def collect(now=None, breadth_path=SHARED_BREADTH):
    now = now or datetime.now(CN)
    result = {"collected_at": now.isoformat(timespec="seconds"), "breadth": None,
              "pools": {}, "errors": {}}
    try:
        value = json.loads(breadth_path.read_text(encoding="utf-8"))
        result["breadth"] = current_breadth(value, now)
    except (OSError, ValueError, KeyError, TypeError):
        result["errors"]["breadth"] = "涨跌家数暂未取得完整、近期统计"
    # A single failed pool must not block the other market facts.
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {key: executor.submit(fetch_pool, key, now) for key in POOLS}
        for key, future in futures.items():
            try:
                result["pools"][key] = future.result()
            except Exception:
                result["errors"][key] = "本项统计暂未取得，等待下次更新"
    return result


def apply_facts(payload, facts):
    breadth = payload.setdefault("market_breadth", {})
    sentiment = payload.setdefault("sentiment", {})
    fresh = facts["breadth"]
    for key in ("advance_count", "decline_count", "flat_count", "total_count", "missing_quote_count"):
        breadth[key] = fresh[key] if fresh else None
    breadth["breadth_as_of"] = fresh["as_of"] if fresh else None
    breadth["breadth_source"] = fresh["source_name"] if fresh else None
    for key, (_, _, sentiment_key) in POOLS.items():
        pool = facts["pools"].get(key)
        breadth[key] = pool["count"] if pool else None
        sentiment[sentiment_key] = breadth[key]
    status = "涨跌家数及涨跌停、炸板统计已更新" if not facts["errors"] else "部分市场统计待更新"
    if fresh and fresh["missing_quote_count"]:
        status += f"；{fresh['missing_quote_count']}只缺少有效报价，未计入涨跌家数"
    breadth["status"] = status
    breadth["source"] = "各项统计来源与时点分别记录，不视为同一时刻的全市场快照"
    # Do not retain the old aggregate as_of as if it described these new facts.
    breadth["as_of"] = None
    sentiment["breadth_status"] = status
    payload["market_structure_facts"] = facts

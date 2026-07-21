#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from update_intraday_market import fetch_indices, fetch_industries, fetch_quotes  # noqa: E402


EXTRA_STOCKS = {
    "sh688409": "富创精密", "sz002409": "雅克科技", "sh688126": "沪硅产业",
    "sh688432": "有研硅", "sh600460": "士兰微", "sh688012": "中微公司",
    "sz002371": "北方华创", "sh688120": "华海清科", "sh688019": "安集科技",
    "sz300666": "江丰电子", "sh688037": "芯源微", "sh688596": "正帆科技",
    "sh688361": "中科飞测", "sz300346": "南大光电", "sz300260": "新莱应材",
    "sh688072": "拓荆科技", "sh688300": "联瑞新材", "sh688535": "华海诚科",
    "sh600176": "中国巨石", "sz301526": "国际复材", "sh605006": "山东玻纤",
    "sz300196": "长海股份", "sh603256": "宏和科技", "sz300530": "领湃科技",
    "sh601992": "金隅集团", "sz002080": "中材科技", "sh600876": "凯盛新能",
    "sz000012": "南玻A", "sh600545": "卓郎智能", "sh603928": "兴业股份",
    "sz000859": "国风新材", "sz300476": "胜宏科技", "sz002463": "沪电股份",
    "sh600183": "生益科技", "sz002938": "鹏鼎控股", "sz002384": "东山精密",
    "sh603228": "景旺电子", "sh603920": "世运电路", "sz300502": "新易盛",
    "sz300308": "中际旭创", "sz300394": "天孚通信", "sz002281": "光迅科技",
    "sz300620": "光库科技", "sh603083": "剑桥科技", "sh603986": "兆易创新",
    "sh688008": "澜起科技", "sh688525": "佰维存储", "sz301308": "江波龙",
    "sz300475": "香农芯创", "sz001309": "德明利", "sz000977": "浪潮信息",
    "sh603019": "中科曙光", "sh601138": "工业富联", "sh688256": "寒武纪",
    "sh600030": "中信证券", "sz300059": "东方财富", "sh601688": "华泰证券",
    "sh601881": "中国银河", "sh601318": "中国平安", "sh601628": "中国人寿",
    "sh601601": "中国太保", "sh601336": "新华保险", "sz002714": "牧原股份",
    "sz300498": "温氏股份", "sz000876": "新希望", "sh603477": "巨星农牧",
    "sz002567": "唐人神", "sh600519": "贵州茅台", "sz000858": "五粮液",
    "sz000568": "泸州老窖", "sh600809": "山西汾酒", "sz002304": "洋河股份",
}

HK_STOCKS = {
    "hk06809": "澜起科技H", "hk03986": "兆易创新H", "hk00981": "中芯国际H",
    "hk01347": "华虹半导体", "hk02513": "智谱", "hk00020": "商汤",
    "hk01024": "快手", "hk00700": "腾讯", "hk09988": "阿里巴巴",
    "hk06160": "百济神州", "hk01801": "信达生物", "hk02269": "药明生物",
    "hk09660": "地平线机器人", "hk02382": "舜宇光学",
}


def collect_config_stocks(value, output):
    if isinstance(value, dict):
        code = value.get("code")
        name = value.get("name")
        if isinstance(code, str) and code[:2] in {"sh", "sz", "bj"} and isinstance(name, str):
            output[code] = name
        for child in value.values():
            collect_config_stocks(child, output)
    elif isinstance(value, list):
        for child in value:
            collect_config_stocks(child, output)


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_quote(row, expected_name):
    fields = row["fields"]
    if len(fields) < 50:
        return None
    current = number(fields[3])
    pct = number(fields[32])
    if current is None or pct is None:
        return None
    amount = number(fields[37])
    return {
        "name": expected_name or fields[1],
        "code": row["query_code"],
        "price": current,
        "pct": pct,
        "prev_close": number(fields[4]),
        "open": number(fields[5]),
        "high": number(fields[33]),
        "low": number(fields[34]),
        "amount_yi": round(amount / 10000, 2) if amount is not None else None,
        "turnover_pct": number(fields[38]),
        "volume_ratio": number(fields[49]),
        "quote_time": fields[30],
        "source": "腾讯财经HTTP",
    }


def fetch_named(mapping):
    result = []
    codes = list(mapping)
    for offset in range(0, len(codes), 60):
        for row in fetch_quotes(codes[offset:offset + 60]):
            parsed = parse_quote(row, mapping.get(row["query_code"]))
            if parsed:
                result.append(parsed)
    return result


watchlist = json.loads((ROOT / "config" / "watchlist.json").read_text(encoding="utf-8"))
stocks = dict(EXTRA_STOCKS)
collect_config_stocks(watchlist, stocks)
indices = fetch_indices()
industries = fetch_industries()
payload = {
    "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "indices": indices,
    "industry_top15": sorted(industries, key=lambda x: x["change_pct"], reverse=True)[:15],
    "industry_bottom15": sorted(industries, key=lambda x: x["change_pct"])[:15],
    "stocks": fetch_named(stocks),
    "hk": fetch_named(HK_STOCKS),
}
print(json.dumps(payload, ensure_ascii=False, indent=2))

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parent.parent
INTRADAY_PATH = ROOT / "data" / "intraday.json"
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
    for pattern in ("%Y%m%d%H%M%S", "%Y%m%d%H%M"):
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        except ValueError:
            continue
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


def write_atomic(path: Path, payload: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def update(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    indices = fetch_indices()
    industries = fetch_industries()
    collected_at = now_iso()
    quote_as_of = latest_quote_time(indices).isoformat(timespec="seconds")

    payload["indices"] = merge_index_rows(payload.get("indices"), indices)
    index_section = payload.setdefault("index", {})
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
    write_atomic(path, payload)
    return {
        "updated": str(path),
        "market_data_as_of": quote_as_of,
        "market_data_collected_at": collected_at,
        "indices": len(indices),
        "industries": len(industries),
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
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Refresh representative facts only; the research producer is external.

The 15:30 research checkpoint is not produced by this script. 18:30 is its
health grace deadline, not another scheduled run. The actual research/Codex
schedule lives on the Mac and cannot be repaired or verified from this repo.
"""
from __future__ import annotations
import json
import math
from datetime import datetime, time
from pathlib import Path
from update_intraday_market import fetch_quotes
from intraday_recovery import TZ, parse_datetime

ROOT = Path(__file__).resolve().parents[1]
TOPICS_PATH = ROOT / "data/topics.json"
POSTMARKET_PATH = ROOT / "data/postmarket.json"
# A subset of already configured research representatives, not a full board.
CORE = {
    "机器人/工业自动化": {"sz002747": "埃斯顿", "sh688160": "步科股份", "sh688017": "绿的谐波"},
    "医药修复链": {"sz002422": "科伦药业", "sz000739": "普洛药业", "sh600276": "恒瑞医药"},
}

def load_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

def parse_timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(TZ) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None

def closing_representatives(raw, expected, now, trade_date=None):
    now = now.astimezone(TZ)
    rows = {}
    for row in raw:
        code, f = row.get("query_code"), row.get("fields") or []
        if code not in expected or len(f) <= 37 or f[1] != expected[code]:
            continue
        try:
            price, previous, high, pct = [float(f[i]) for i in (3, 4, 33, 32)]
            at = parse_datetime(f[30])
            if not all(math.isfinite(v) for v in (price, previous, high, pct)) or min(price, previous, high) <= 0:
                continue
            if at is None or at.date() != (trade_date or now.date()) or at.time() < time(15) or at > now:
                continue
            if abs((price / previous - 1) * 100 - pct) > .05:
                continue
        except (ValueError, TypeError):
            continue
        rows[code] = {"code": code, "name": f[1], "price": price, "change_pct": pct,
                      "quote_time": at.isoformat(timespec="seconds"), "source": "腾讯财经HTTP"}
    return [rows[code] for code in expected if code in rows]

def topic_update(name, quotes, now, postmarket_time):
    now = now.astimezone(TZ)
    if len(quotes) != len(CORE[name]):
        return None
    up = sum(row["change_pct"] > 0 for row in quotes)
    down = sum(row["change_pct"] < 0 for row in quotes)
    flat = len(quotes) - up - down
    state = "代表股多数走弱" if down >= 2 else "代表股多数上涨，继续观察" if up >= 2 else "代表股表现分化"
    evidence = [f"{r['name']} {r['code']} {r['change_pct']:+.2f}%，报{r['price']}；{r['quote_time']}；{r['source']}。" for r in quotes]
    return {"status": state, "summary": f"跟踪的{len(quotes)}只代表股中，{up}只上涨、{down}只下跌、{flat}只平盘。这里只反映这组股票，尚不能代表整个板块。",
            "evidence": evidence, "representatives": quotes,
            "updated_at": now.isoformat(timespec="seconds"), "last_checked_at": now.isoformat(timespec="seconds"),
            "source_as_of": max(row["quote_time"] for row in quotes), "postmarket_source_as_of": postmarket_time,
            "trade_date": quotes[0]["quote_time"][:10], "update_scope": "closing_representatives_only"}

def representatives_current(item, close_at, now):
    """Research timestamps must never suppress or validate a quote refresh."""
    facts = item.get("representative_facts") or {}
    if not isinstance(facts, dict):
        return False
    rows = facts.get("representatives") or []
    expected = CORE.get(item.get("name"), {})
    if not isinstance(rows, list) or len(rows) != len(expected) or not expected or any(not isinstance(row, dict) for row in rows):
        return False
    if {row.get("code") for row in rows} != set(expected):
        return False
    for row in rows:
        stamp = parse_timestamp(row.get("quote_time"))
        if row.get("name") != expected[row["code"]] or not stamp or stamp.date() != close_at.date() or stamp.time() < time(15) or stamp > now:
            return False
    return True

def main(now=None):
    now = (now or datetime.now(TZ)).astimezone(TZ)
    topics, postmarket = load_json(TOPICS_PATH), load_json(POSTMARKET_PATH)
    close_at = parse_timestamp(postmarket.get("timestamp"))
    if not close_at or close_at > now or close_at.time() < time(15):
        print("topics-refresh: waiting - 等待有效收盘证据，不改写旧研究")
        return 0
    updates = {}
    for item in topics.get("topics") or []:
        name = item.get("name")
        if name not in CORE:
            continue
        if representatives_current(item, close_at, now):
            continue
        try:
            quotes = closing_representatives(fetch_quotes(CORE[name]), CORE[name], now, close_at.date())
            update = topic_update(name, quotes, now, postmarket["timestamp"])
            if update:
                updates[name] = update
        except Exception:
            pass
    if not updates:
        print("topics-refresh: waiting - 已更新的记录保持不变；缺少的收盘报价待重试")
        return 0
    topics = load_json(TOPICS_PATH)  # Do not overwrite concurrently authored research.
    changed = []
    for item in topics.get("topics") or []:
        name = item.get("name")
        if name not in updates or representatives_current(item, close_at, now):
            continue
        # Keep authored conclusions, timestamps and history byte-for-byte in
        # their existing fields. New quotes are not a new research checkpoint.
        item["representative_facts"] = updates[name]
        changed.append(name)
    if changed:
        topics["representative_facts_updated_at"] = now.isoformat(timespec="seconds")
        topics["representative_facts_trade_date"] = close_at.date().isoformat()
        topics["representative_facts_status"] = "partial_representatives_refreshed"
        temp = TOPICS_PATH.with_suffix(".json.tmp")
        temp.write_text(json.dumps(topics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        json.loads(temp.read_text(encoding="utf-8"))
        temp.replace(TOPICS_PATH)
    print("topics-refresh: ok - 更新收盘代表股核对：" + "、".join(changed) + "；不替代完整产业研究")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

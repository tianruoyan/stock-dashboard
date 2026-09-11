#!/usr/bin/env python3
"""Refresh core research representatives, never the user's stock-pool membership."""
from __future__ import annotations
import json
import math
from datetime import datetime, time, timedelta
from pathlib import Path
from update_intraday_market import fetch_quotes, parse_quote_time

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
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None

def closing_representatives(raw, expected, now):
    rows = {}
    for row in raw:
        code, f = row.get("query_code"), row.get("fields") or []
        if code not in expected or len(f) <= 37 or f[1] != expected[code]:
            continue
        try:
            price, previous, high, pct = [float(f[i]) for i in (3, 4, 33, 32)]
            at = parse_quote_time(f[30])
            if not all(math.isfinite(v) for v in (price, previous, high, pct)) or min(price, previous, high) <= 0:
                continue
            if at is None or at.date() != now.date() or at.time() < time(15) or at > now + timedelta(seconds=60):
                continue
            if abs((price / previous - 1) * 100 - pct) > .05:
                continue
        except (ValueError, TypeError):
            continue
        rows[code] = {"code": code, "name": f[1], "price": price, "change_pct": pct,
                      "quote_time": at.isoformat(timespec="seconds"), "source": "腾讯财经HTTP"}
    return [rows[code] for code in expected if code in rows]

def topic_update(name, quotes, now, postmarket_time):
    if len(quotes) != len(CORE[name]):
        return None
    up = sum(row["change_pct"] > 0 for row in quotes)
    down = sum(row["change_pct"] < 0 for row in quotes)
    flat = len(quotes) - up - down
    state = "代表股多数走弱" if down >= 2 else "代表股多数上涨，继续观察" if up >= 2 else "代表股表现分化"
    evidence = [f"{r['name']} {r['code']} {r['change_pct']:+.2f}%，报{r['price']}；{r['quote_time']}；{r['source']}。" for r in quotes]
    return {"status": state, "conclusion": f"跟踪的{len(quotes)}只代表股中，{up}只上涨、{down}只下跌、{flat}只平盘。这里只反映这组股票，尚不能代表整个板块。",
            "action": "下一交易日先看这些代表股是否多数走强，再看同板块是否有更多股票跟涨；缺少扩散时不追高。",
            "risk": "样本不覆盖整个板块；没有新的公告或订单证据，不能据此认定产业逻辑改善。",
            "invalidate": "代表股多数转跌，或仅一只股票上涨而其他继续走弱。",
            "note": " ".join(evidence), "evidence": evidence, "representatives": quotes,
            "updated_at": now.isoformat(timespec="seconds"), "last_checked_at": now.isoformat(timespec="seconds"),
            "source_as_of": max(row["quote_time"] for row in quotes), "postmarket_source_as_of": postmarket_time,
            "update_scope": "closing_representatives_only"}

def main():
    now = datetime.now().astimezone()
    topics, postmarket = load_json(TOPICS_PATH), load_json(POSTMARKET_PATH)
    close_at = parse_timestamp(postmarket.get("timestamp"))
    if not close_at or close_at.date() != now.date() or close_at.time() < time(15) or now.time() < time(15):
        print("topics-refresh: waiting - 等待当日收盘，不改写旧研究")
        return 0
    updates = {}
    for item in topics.get("topics") or []:
        name = item.get("name")
        if name not in CORE:
            continue
        updated_at = parse_timestamp(item.get("updated_at"))
        if updated_at and updated_at >= close_at:
            continue
        try:
            quotes = closing_representatives(fetch_quotes(CORE[name]), CORE[name], now)
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
        updated_at = parse_timestamp(item.get("updated_at"))
        if name not in updates or (updated_at and updated_at >= close_at):
            continue
        history = item.setdefault("history", [])
        history.append({k: v for k, v in item.items() if k != "history"})
        item.update(updates[name])
        changed.append(name)
    if changed:
        topics["timestamp"] = now.isoformat(timespec="seconds")
        topics["trade_date"] = now.date().isoformat()
        topics["source_as_of"] = postmarket["timestamp"]
        topics["status"] = "partial_topics_refreshed"
        temp = TOPICS_PATH.with_suffix(".json.tmp")
        temp.write_text(json.dumps(topics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        json.loads(temp.read_text(encoding="utf-8"))
        temp.replace(TOPICS_PATH)
    print("topics-refresh: ok - 更新收盘代表股核对：" + "、".join(changed) + "；不替代完整产业研究")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

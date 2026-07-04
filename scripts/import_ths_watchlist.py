#!/usr/bin/env python3
"""Import exported TongHuaShun watchlist into config/watchlist.json.

This script only appends/updates watch_only stocks. It never removes existing
manual entries, so a bad export cannot wipe the personal watchlist.
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHLIST_PATH = ROOT / "config" / "watchlist.json"
PUSH_MARKER = ROOT / ".push-now"
DEFAULT_SOURCE = Path.home() / "Documents" / "同花顺自选股.txt"
EASTMONEY_TOKEN = "D43BF722C8E33E1B5FBF8EF4C0C8ECBE"


def normalize_code(raw):
    code = str(raw or "").strip().lower()
    code = re.sub(r"^(sh|sz|bj)[.:_-]?", r"\1", code)
    digits = re.sub(r"\D", "", code)
    if len(digits) != 6:
        return code
    if digits.startswith("6"):
        return "sh" + digits
    if digits.startswith(("0", "3")):
        return "sz" + digits
    if digits.startswith(("4", "8", "9")):
        return "bj" + digits
    return digits


def lookup_stock(query):
    q = str(query or "").strip()
    if not q:
        return {}
    params = urllib.parse.urlencode({
        "input": q,
        "type": "14",
        "token": EASTMONEY_TOKEN,
        "count": "5",
    })
    url = "https://searchapi.eastmoney.com/api/suggest/get?" + params
    with urllib.request.urlopen(url, timeout=6) as resp:
        payload = json.loads(resp.read().decode("utf-8", "ignore"))
    rows = payload.get("QuotationCodeTable", {}).get("Data", []) or []
    row = next((r for r in rows if r.get("Classify") == "AStock"), rows[0] if rows else {})
    if not row:
        return {}
    return {
        "code": normalize_code(row.get("Code")),
        "name": row.get("Name") or q,
        "tags": ["同花顺自选", "观察池"],
        "source": "同花顺自选导入",
    }


def parse_source(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p for p in re.split(r"[\s,，;；、]+", line) if p]
        if not parts:
            continue
        code = ""
        name = ""
        for part in parts:
            if re.match(r"^(sh|sz|bj)?\d{6}$", part, re.I):
                code = normalize_code(part)
            elif not name:
                name = part
        if not code and not name:
            continue
        rows.append({"code": code, "name": name})
    return rows


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def enrich(item):
    if item.get("code") and item.get("name"):
        return {
            "code": normalize_code(item["code"]),
            "name": item["name"],
            "tags": ["同花顺自选", "观察池"],
            "source": "同花顺自选导入",
        }
    return lookup_stock(item.get("code") or item.get("name")) or {
        "code": normalize_code(item.get("code")),
        "name": item.get("name") or item.get("code"),
        "tags": ["同花顺自选", "观察池"],
        "source": "同花顺自选导入",
    }


def merge_watchlist(watchlist, imported):
    pool = watchlist.setdefault("watch_only", {})
    stocks = pool.setdefault("stocks", [])
    by_code = {normalize_code(s.get("code")): s for s in stocks if s.get("code")}
    by_name = {s.get("name"): s for s in stocks if s.get("name")}
    added = 0
    updated = 0
    for raw in imported:
        stock = enrich(raw)
        code = normalize_code(stock.get("code"))
        name = stock.get("name")
        existing = (code and by_code.get(code)) or (name and by_name.get(name))
        if existing:
            if not existing.get("code") and code:
                existing["code"] = code
                updated += 1
            if not existing.get("name") and name:
                existing["name"] = name
                updated += 1
            tags = list(dict.fromkeys([*(existing.get("tags") or []), "同花顺自选", "观察池"]))
            if tags != existing.get("tags"):
                existing["tags"] = tags
                updated += 1
            continue
        stocks.append(stock)
        if code:
            by_code[code] = stock
        if name:
            by_name[name] = stock
        added += 1
    return added, updated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=os.environ.get("THS_WATCHLIST_FILE", str(DEFAULT_SOURCE)))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = Path(args.source).expanduser()
    if not source.exists():
        print(f"source not found: {source}", file=sys.stderr)
        return 2
    text = source.read_text(encoding="utf-8-sig")
    imported = parse_source(text)
    if not imported:
        print("no stocks found in source", file=sys.stderr)
        return 1
    watchlist = load_json(WATCHLIST_PATH)
    added, updated = merge_watchlist(watchlist, imported)
    if args.dry_run:
        print(json.dumps({"source": str(source), "found": len(imported), "added": added, "updated": updated}, ensure_ascii=False))
        return 0
    save_json(WATCHLIST_PATH, watchlist)
    PUSH_MARKER.touch()
    print(json.dumps({"source": str(source), "found": len(imported), "added": added, "updated": updated, "saved": str(WATCHLIST_PATH)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

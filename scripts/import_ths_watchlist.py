#!/usr/bin/env python3
"""Mirror TongHuaShun watchlist into config/watchlist.json.

Only the watch_only pool follows TongHuaShun exactly. The small_deng and
old_deng pools remain independent style-monitoring pools.
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHLIST_PATH = ROOT / "config" / "watchlist.json"
PUBLISH_SCRIPT = ROOT / "scripts" / "publish_dashboard.sh"
AUDIT_SCRIPT = ROOT / "scripts" / "audit_dashboard_data.py"
DEFAULT_SOURCE = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "同花顺自选股.txt"
THS_COOKIE_PATH = (
    Path.home()
    / "Library"
    / "Containers"
    / "cn.com.10jqka.macstockPro"
    / "Data"
    / "Library"
    / "Cookies"
    / "Cookies.binarycookies"
)
THS_SELF_STOCK_URL = "https://t.10jqka.com.cn/newcircle/group/getSelfStockWithMarket/"
EASTMONEY_TOKEN = "D43BF722C8E33E1B5FBF8EF4C0C8ECBE"
THS_USER_AGENT = (
    "Hexin_Gphone/11.28.03 (Royal Flush) hxtheme/0 innerversion/G037.09.028.1.32 "
    "followPhoneSystemTheme/0 userid/000000000 getHXAPPAccessibilityMode/0 "
    "hxNewFont/1 isVip/0 getHXAPPFontSetting/normal getHXAPPAdaptOldSetting/0 okhttp/3.14.9"
)
PROFILE_TAGS = {
    "sz300536": ["待标注方向"],
    "sh688777": ["工业自动化"],
    "sz300418": ["AI应用"],
    "sz002261": ["华为算力"],
    "sh688111": ["AI办公"],
    "sh688549": ["半导体材料"],
    "sz300346": ["光刻胶"],
    "sh603078": ["湿电子化学品"],
    "sz002409": ["半导体材料"],
    "sh688019": ["CMP抛光液"],
    "sh688120": ["CMP设备"],
    "sz002371": ["半导体设备"],
    "sh688012": ["半导体设备"],
    "sh688432": ["硅材料"],
    "sh688126": ["硅片材料"],
    "sh688795": ["国产GPU"],
    "sh603986": ["存储/MCU"],
    "sh688008": ["存储/HBM"],
    "sh588170": ["半导体ETF"],
    "sh515230": ["软件ETF"],
    "sh515120": ["创新药ETF"],
    "sz159530": ["机器人ETF"],
    "sh600276": ["创新药", "化学制药"],
    "sh688235": ["创新药", "港股联动"],
    "sz002979": ["工业自动化", "运动控制"],
    "sh688200": ["半导体设备", "测试设备"],
    "sh688362": ["先进封装", "半导体封测"],
    "sh688702": ["高速互联", "交换芯片"],
    "sh688082": ["半导体设备", "清洗设备"],
    "sh600584": ["先进封装", "半导体封测"],
    "sh688578": ["创新药", "科创医药"],
    "sz000739": ["原料药", "化学制药"],
    "sh512010": ["医药ETF"],
    "hk2513": ["AI应用"],
    "hk9880": ["机器人"],
}


def normalize_code(raw):
    code = str(raw or "").strip().lower()
    if re.match(r"^hk\d{4,5}$", code):
        return code
    prefixed = re.match(r"^(sh|sz|bj)(\d{6})$", code)
    if prefixed:
        return prefixed.group(1) + prefixed.group(2)
    code = re.sub(r"^(sh|sz|bj)[.:_-]?", r"\1", code)
    digits = re.sub(r"\D", "", code)
    if len(digits) != 6:
        return code
    if digits.startswith("6"):
        return "sh" + digits
    if digits.startswith(("0", "3")):
        return "sz" + digits
    if digits.startswith("5"):
        return "sh" + digits
    if digits.startswith("1"):
        return "sz" + digits
    if digits.startswith(("4", "8", "9")):
        return "bj" + digits
    return digits


def normalize_ths_code(code, marketid):
    raw = str(code or "").strip()
    market = str(marketid or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.upper().startswith("HK"):
        return "hk" + digits
    if len(digits) != 6:
        return raw.lower()
    if market in {"17", "20"}:
        return "sh" + digits
    if market in {"33", "36"}:
        return "sz" + digits
    return normalize_code(digits)


def lookup_stock(query):
    q = str(query or "").strip()
    if not q:
        return {}
    search_q = re.sub(r"^(sh|sz|bj|hk)", "", q, flags=re.I)
    params = urllib.parse.urlencode({
        "input": search_q or q,
        "type": "14",
        "token": EASTMONEY_TOKEN,
        "count": "5",
    })
    url = "https://searchapi.eastmoney.com/api/suggest/get?" + params
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            payload = json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception:
        return {}
    rows = payload.get("QuotationCodeTable", {}).get("Data", []) or []
    expected_hk = q.lower().startswith("hk")
    if expected_hk:
        row = next((r for r in rows if r.get("Classify") == "HK"), rows[0] if rows else {})
    else:
        row = next(
            (
                r
                for r in rows
                if r.get("Classify") in {"AStock", "Fund", "23"}
                or r.get("SecurityTypeName") in {"科创板", "基金"}
            ),
            rows[0] if rows else {},
        )
    if not row:
        return {}
    quote = str(row.get("QuoteID") or "")
    market_prefix = ""
    if row.get("Classify") == "HK":
        market_prefix = "hk"
    elif quote.startswith("1."):
        market_prefix = "sh"
    elif quote.startswith("0."):
        market_prefix = "sz"
    code = (market_prefix + row.get("Code", "").lstrip("0")) if market_prefix == "hk" else normalize_code((market_prefix + row.get("Code", "")) or row.get("Code"))
    return {
        "code": code,
        "name": row.get("Name") or q,
        "tags": [*PROFILE_TAGS.get(code, []), "同花顺自选", "观察池"],
        "source": "同花顺自选导入",
    }


def read_c_string(buf, offset):
    end = buf.find(b"\x00", offset)
    if end < 0:
        end = len(buf)
    return buf[offset:end].decode("utf-8", "replace")


def read_binary_cookies(path):
    data = path.read_bytes()
    if data[:4] != b"cook":
        raise ValueError("invalid Cookies.binarycookies header")
    page_count = struct.unpack(">I", data[4:8])[0]
    page_sizes = [
        struct.unpack(">I", data[8 + i * 4 : 12 + i * 4])[0]
        for i in range(page_count)
    ]
    cursor = 8 + page_count * 4
    cookies = []
    for page_size in page_sizes:
        page = data[cursor : cursor + page_size]
        cursor += page_size
        if len(page) < 8:
            continue
        cookie_count = struct.unpack("<I", page[4:8])[0]
        offsets = [
            struct.unpack("<I", page[8 + i * 4 : 12 + i * 4])[0]
            for i in range(cookie_count)
        ]
        for offset in offsets:
            if offset + 40 > len(page):
                continue
            size = struct.unpack("<I", page[offset : offset + 4])[0]
            if size <= 0 or offset + size > len(page):
                continue
            domain_offset = struct.unpack("<I", page[offset + 16 : offset + 20])[0]
            name_offset = struct.unpack("<I", page[offset + 20 : offset + 24])[0]
            path_offset = struct.unpack("<I", page[offset + 24 : offset + 28])[0]
            value_offset = struct.unpack("<I", page[offset + 28 : offset + 32])[0]
            cookies.append(
                {
                    "domain": read_c_string(page, offset + domain_offset),
                    "name": read_c_string(page, offset + name_offset),
                    "path": read_c_string(page, offset + path_offset),
                    "value": read_c_string(page, offset + value_offset),
                }
            )
    return cookies


def load_ths_cookies(cookie_path=THS_COOKIE_PATH):
    if not cookie_path.exists():
        raise FileNotFoundError(f"同花顺 Cookie 文件不存在: {cookie_path}")
    cookies = {}
    for cookie in read_binary_cookies(cookie_path):
        if "10jqka.com.cn" in cookie.get("domain", ""):
            cookies[cookie["name"]] = cookie["value"]
    if not cookies.get("userid") or not cookies.get("sess_tk"):
        raise RuntimeError("同花顺桌面端未登录，或 Cookie 已失效")
    return cookies


def fetch_ths_watchlist():
    cookies = load_ths_cookies()
    req = urllib.request.Request(
        THS_SELF_STOCK_URL,
        headers={
            "User-Agent": THS_USER_AGENT,
            "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8", "ignore"))
    if payload.get("errorCode") != 0:
        raise RuntimeError(payload.get("errorMsg") or "同花顺自选股接口返回异常")
    rows = payload.get("result") or []
    imported = []
    for row in rows:
        code = normalize_ths_code(row.get("code"), row.get("marketid"))
        if code:
            imported.append({"code": code})
    return imported


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


def run_quality_audit():
    if not AUDIT_SCRIPT.exists():
        return
    subprocess.run([sys.executable, str(AUDIT_SCRIPT)], cwd=str(ROOT), check=False)


def publish_dashboard():
    if not PUBLISH_SCRIPT.exists():
        raise FileNotFoundError(f"发布脚本不存在: {PUBLISH_SCRIPT}")
    return subprocess.run([str(PUBLISH_SCRIPT)], cwd=str(ROOT), check=False).returncode


def enrich(item):
    if item.get("code") and item.get("name"):
        code = normalize_code(item["code"])
        return {
            "code": code,
            "name": item["name"],
            "tags": [*PROFILE_TAGS.get(code, []), "同花顺自选", "观察池"],
            "source": "同花顺自选导入",
        }
    looked_up = lookup_stock(item.get("code") or item.get("name"))
    if looked_up:
        return looked_up
    code = normalize_code(item.get("code"))
    return {
        "code": code,
        "name": item.get("name") or item.get("code"),
        "tags": [*PROFILE_TAGS.get(code, []), "同花顺自选", "观察池"],
        "source": "同花顺自选导入",
    }


def merge_watchlist(watchlist, imported):
    pool = watchlist.setdefault("watch_only", {})
    stocks = pool.setdefault("stocks", [])
    old_count = len(stocks)
    by_code = {}
    for s in stocks:
        code = normalize_code(s.get("code"))
        if code:
            by_code[code] = s
            digits = re.sub(r"\D", "", code)
            if len(digits) == 6:
                by_code[digits] = s
    by_name = {s.get("name"): s for s in stocks if s.get("name")}
    added = 0
    updated = 0
    mirrored = []
    seen = set()
    for raw in imported:
        stock = enrich(raw)
        code = normalize_code(stock.get("code"))
        name = stock.get("name")
        digits = re.sub(r"\D", "", code or "")
        key = code or digits or name
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        existing = (code and by_code.get(code)) or (digits and by_code.get(digits)) or (name and by_name.get(name))
        if existing:
            merged = dict(existing)
            existing_code = normalize_code(existing.get("code"))
            if code and (existing_code != code or existing.get("code") != code):
                merged["code"] = code
                updated += 1
            existing_name = str(existing.get("name") or "")
            if name and (not existing_name or normalize_code(existing_name) == existing_code):
                merged["name"] = name
                updated += 1
            tags = list(dict.fromkeys([*(merged.get("tags") or []), "同花顺自选", "观察池"]))
            tags = list(dict.fromkeys([*PROFILE_TAGS.get(code, []), *tags]))
            if tags != merged.get("tags"):
                merged["tags"] = tags
                updated += 1
            merged["source"] = "同花顺自选导入"
            mirrored.append(merged)
            continue
        mirrored.append(stock)
        if code:
            by_code[code] = stock
        if name:
            by_name[name] = stock
        added += 1
    pool["stocks"] = mirrored
    pool["_说明"] = "个人观察池—与同花顺自选股保持一致；同步时有增有减。小登池/老登池不受影响。"
    removed = max(old_count - len(mirrored) + added, 0)
    return added, updated, removed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=os.environ.get("THS_WATCHLIST_FILE", str(DEFAULT_SOURCE)))
    parser.add_argument(
        "--mode",
        choices=["auto", "ths", "file"],
        default=os.environ.get("THS_WATCHLIST_MODE", "auto"),
        help="auto 优先读取桌面同花顺，失败后回退到文本文件",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import_source = ""
    imported = []
    if args.mode in {"auto", "ths"}:
        try:
            imported = fetch_ths_watchlist()
            import_source = "同花顺桌面端"
        except Exception as exc:
            if args.mode == "ths":
                print(f"ths import failed: {exc}", file=sys.stderr)
                return 2
            print(f"ths import failed, fallback to file: {exc}", file=sys.stderr)
    if not imported:
        source = Path(args.source).expanduser()
        if not source.exists():
            print(f"source not found: {source}", file=sys.stderr)
            return 2
        text = source.read_text(encoding="utf-8-sig")
        imported = parse_source(text)
        import_source = str(source)
    if not imported:
        print("no stocks found", file=sys.stderr)
        return 1
    watchlist = load_json(WATCHLIST_PATH)
    added, updated, removed = merge_watchlist(watchlist, imported)
    if args.dry_run:
        print(json.dumps({"source": import_source, "found": len(imported), "added": added, "updated": updated, "removed": removed, "mode": "mirror"}, ensure_ascii=False))
        return 0
    save_json(WATCHLIST_PATH, watchlist)
    run_quality_audit()
    publish_status = publish_dashboard()
    print(json.dumps({"source": import_source, "found": len(imported), "added": added, "updated": updated, "removed": removed, "mode": "mirror", "saved": str(WATCHLIST_PATH), "publish_status": publish_status}, ensure_ascii=False))
    return 0 if publish_status == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

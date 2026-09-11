"""Public external quotes for V1. Facts only; never reconstruct a past decision."""
from __future__ import annotations

import copy
import json
import math
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from update_intraday_market import fetch_quotes

TZ = ZoneInfo("Asia/Shanghai")
US = {"usDJI": "道琼斯", "usINX": "标普500", "usIXIC": "纳斯达克", "usNVDA": "英伟达", "usMU": "美光科技"}
HK = {"hkHSI": "恒生指数", "hkHSTECH": "恒生科技", "hk00700": "腾讯控股", "hk00981": "中芯国际"}
ASIA = {"^N225": "日经225", "^KS11": "韩国KOSPI", "005930.KS": "三星电子", "000660.KS": "SK海力士"}


def iso(value: datetime) -> str:
    return value.astimezone(TZ).isoformat(timespec="seconds")


def positive(value) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("invalid price")
    return number


def tencent_row(raw: dict, now: datetime) -> dict:
    code, fields = raw["query_code"], raw["fields"]
    zone = ZoneInfo("America/New_York") if code in US else TZ
    stamp = fields[30].replace("/", "-")
    at = datetime.fromisoformat(stamp).replace(tzinfo=zone).astimezone(TZ)
    if at > now + timedelta(minutes=2):
        raise ValueError("future quote")
    if code in US:
        expected = now.date() - timedelta(days=1)
        while expected.weekday() >= 5:
            expected -= timedelta(days=1)
        local = at.astimezone(zone)
        # Holidays without a verified US calendar remain explicitly missing.
        if local.date() != expected or local.time() < time(16):
            raise ValueError("not latest completed US session")
    elif code in HK:
        if at.date() != now.date():
            raise ValueError("previous session is not today's HK quote")
        # Last trade is not an indicative auction price, even before 09:30.
        closing_quote = now.time() >= time(16, 10) and at.time() >= time(16)
        if at.time() < time(9, 30) or (now - at > timedelta(minutes=30) and not closing_quote):
            raise ValueError("no current HK continuous-session quote")
    else:
        raise ValueError("unknown symbol")
    price, previous = positive(fields[3]), positive(fields[4])
    pct = float(fields[32])
    if not math.isfinite(pct) or abs(pct - (price / previous - 1) * 100) > 0.06:
        raise ValueError("price and percent disagree")
    source = "腾讯财经"
    note = f"{at:%m-%d %H:%M} 北京时间 · {source}"
    if code in HK and now - at > timedelta(minutes=5):
        note += " · 延时报价"
    return {"code": code, "name": (US | HK)[code], "close": price,
            "previous_close": previous, "change_pct": round(pct, 2),
            "quote_time": iso(at), "collected_at": iso(now), "available_at": iso(now),
            "source": source, "source_url": f"https://qt.gtimg.cn/q={code}",
            "note": note, "status": note}


def chart_row(symbol: str, chart: dict, now: datetime) -> dict:
    meta = chart["meta"]
    if meta.get("symbol") != symbol:
        raise ValueError("symbol mismatch")
    market_at = datetime.fromtimestamp(meta["regularMarketTime"], TZ)
    if market_at.date() != now.date() or market_at > now + timedelta(minutes=2):
        raise ValueError("not today's Asian session")
    previous = positive(meta["previousClose"])
    cutoff = min(now, now.replace(hour=9, minute=25, second=0, microsecond=0))
    points = []
    closes = chart["indicators"]["quote"][0]["close"]
    for stamp, value in zip(chart.get("timestamp", []), closes):
        start = datetime.fromtimestamp(stamp, TZ)
        end = start + timedelta(minutes=1)
        # Only completed minute bars, never the current/incomplete final point.
        if start.second != 0 or start.date() != now.date() or start.time() < time(8) or end > cutoff:
            continue
        try:
            points.append((end, start, positive(value)))
        except (TypeError, ValueError):
            continue
    if not points:
        raise ValueError("no completed pre-open minute bar")
    at, start, price = max(points)
    if cutoff - at > timedelta(minutes=30):
        raise ValueError("Asian quote too old for selected window")
    recovered = now.time() >= time(9, 30)
    note = f"{at:%m-%d %H:%M} 北京时间 · 雅虎财经"
    if recovered:
        note += f" · {now:%H:%M}补采，不作为当时已知信息"
    return {"code": symbol, "name": ASIA[symbol], "close": round(price, 4),
            "previous_close": previous, "change_pct": round((price / previous - 1) * 100, 2),
            "quote_time": iso(at), "bar_start": iso(start), "collected_at": iso(now),
            "available_at": iso(now), "historical_backfill": recovered,
            "source": "雅虎财经", "source_url": f"https://finance.yahoo.com/quote/{urllib.parse.quote(symbol, safe='')}/",
            "note": note, "status": note}


def fetch_asia(symbol: str, now: datetime) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol, safe='')}?interval=1m&range=1d"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=12) as response:
        body = json.load(response)
    return chart_row(symbol, body["chart"]["result"][0], now)


def collect(now: datetime) -> tuple[dict, dict]:
    rows, errors = {}, {}
    # Independent requests: a failed market cannot suppress another market.
    def one(code):
        if code in ASIA:
            return fetch_asia(code, now)
        raw = fetch_quotes([code])
        if len(raw) != 1:
            raise ValueError("quote absent")
        return tencent_row(raw[0], now)
    with ThreadPoolExecutor(max_workers=5) as executor:
        pending = {code: executor.submit(one, code) for code in [*US, *ASIA, *HK]}
        for code, future in pending.items():
            try:
                rows[code] = future.result()
            except Exception as exc:
                errors[code] = type(exc).__name__ + ": " + str(exc)[:180]
    return rows, errors


def merge_rows(old: list, new: list) -> list:
    merged = {row.get("code"): row for row in old if isinstance(row, dict) and row.get("code")}
    for row in new:
        previous = merged.get(row["code"])
        # Preserve first availability and do not publish unchanged quotes repeatedly.
        if previous and previous.get("quote_time") == row["quote_time"] and previous.get("close") == row["close"]:
            continue
        merged[row["code"]] = row
    return list(merged.values())


def usable_saved(row: dict, codes: list, now: datetime) -> bool:
    try:
        if row.get("code") not in codes or not row.get("source"):
            return False
        at = datetime.fromisoformat(row["quote_time"]).astimezone(TZ)
        if at > now + timedelta(minutes=2):
            return False
        positive(row["close"])
        if not math.isfinite(float(row["change_pct"])):
            return False
        if row["code"] in US:
            expected = now.date() - timedelta(days=1)
            while expected.weekday() >= 5:
                expected -= timedelta(days=1)
            return at.astimezone(ZoneInfo("America/New_York")).date() == expected
        return at.date() == now.date() and time(8) <= at.time() <= time(9, 25)
    except (TypeError, ValueError, KeyError):
        return False


def apply_facts(payload: dict, rows: dict, now: datetime, errors: dict | None = None) -> dict:
    output = copy.deepcopy(payload)
    us = output.setdefault("us_overnight", {})
    for field, codes in [("indices", list(US)[:3]), ("tech_stocks", list(US)[3:])]:
        kept = [r for r in us.get(field) or [] if isinstance(r, dict) and usable_saved(r, codes, now)]
        us[field] = merge_rows(kept, [rows[c] for c in codes if c in rows])
    jk = us.get("japan_korea")
    if not isinstance(jk, dict):
        jk = {}
    for field, codes in [("indices", list(ASIA)[:2]), ("stocks", list(ASIA)[2:])]:
        kept = [r for r in jk.get(field) or [] if isinstance(r, dict) and usable_saved(r, codes, now)]
        jk[field] = merge_rows(kept, [rows[c] for c in codes if c in rows])
    jk["status"] = "已取得早盘行情" if jk["indices"] else "日韩早盘行情暂未取到，暂不判断对A股的影响。"
    us["japan_korea"] = jk
    if output.get("generation_mode") == "automatic_stage_guard":
        us["conclusion"] = "；".join(f"{r['name']}{r['change_pct']:+.2f}%" for r in us["indices"]) or "隔夜美股行情暂未取到，暂不判断外盘方向。"
        us["reason"] = "以上为行情事实；新闻催化与A股影响需另行核实。"
        us["impact_to_a_share"] = "先对照A股相关板块及代表股的实际涨跌，不能仅凭海外上涨或下跌决定买卖。"
        auction = output.get("hk_auction") or {}
        hk_note = "港股竞价报价仍缺，开盘后的港股行情单独展示。" if not auction.get("indices") and not auction.get("stocks") else "港股盘前记录见下方。"
        output["summary"] = (us["conclusion"] + "。" if us["indices"] else "隔夜美股报价暂缺。") + "日韩早盘见下方；" + hk_note
        output["strategy"] = [{"action": "等待A股确认", "logic": ["外盘行情用于确定观察方向；是否参与，还要看A股相关板块及代表股是否同步走强。", "缺少港股竞价或A股代表股依据时，不给出买入或加仓结论。"]}]
    hk = output.setdefault("hk_auction", {})
    if not hk.get("indices") and not hk.get("stocks"):
        hk["sentiment"] = ("当前公开行情接口不提供可核验的港股竞价参考价，不能判断竞价强弱。" +
                           ("已过盘前时段；下方开盘后行情不替代早上的竞价记录。" if now.time() >= time(9, 30) else "开盘后再核对恒生科技及代表股的实际涨跌。"))
    hk_rows = [rows[c] for c in HK if c in rows]
    if hk_rows:
        followup = output.setdefault("hk_followup", {})
        followup["indices"] = merge_rows(followup.get("indices") or [], [r for r in hk_rows if r["code"] in list(HK)[:2]])
        followup["stocks"] = merge_rows(followup.get("stocks") or [], [r for r in hk_rows if r["code"] in list(HK)[2:]])
        followup["note"] = "开盘后补充，按各条报价时间阅读；不代表09:00港股盘前判断。"
    missing = [name for code, name in (US | ASIA).items()
               if not any(r.get("code") == code for r in us.get("indices", []) + us.get("tech_stocks", []) + jk["indices"] + jk["stocks"])]
    output["external_data_notice"] = "缺少：" + "、".join(missing) + "；联网后继续补采。" if missing else ""
    if errors is not None:
        failed = [(US | ASIA | HK)[code] for code in errors if code in US or code in ASIA or (code in HK and now.time() >= time(9, 45))]
        output["external_refresh_notice"] = ("本轮未更新：" + "、".join(failed) + "。保留上次取得的数据，报价时间见各条行情；稍后自动重试。") if failed else ""
    if output != payload:
        # Do NOT touch analysis_time, timestamp, phase, or any user/model decision.
        output["external_updated_at"] = iso(now)
    return output


def refresh(root: Path, now: datetime, *, force: bool = False) -> bool:
    from stage_fallback import read_json, write_json_atomic, parse_datetime, current_payload
    path = root / "data" / "premarket.json"
    payload = read_json(path)
    if not current_payload(payload, now.date().isoformat()):
        return False
    state_path = root / "logs" / "premarket-external-status.json"
    state = read_json(state_path)
    checked = parse_datetime(state.get("checked_at"))
    interval = 180 if now.time() < time(9, 30) else 900
    if not force and checked and timedelta(0) <= now - checked < timedelta(seconds=interval):
        return False
    rows, errors = collect(now)
    updated = apply_facts(payload, rows, now, errors)
    # Re-read to avoid clobbering an analysis that finished during network IO.
    latest = read_json(path)
    if latest != payload:
        payload = latest
        if not current_payload(payload, now.date().isoformat()):
            return False
        updated = apply_facts(payload, rows, now, errors)
    changed = updated != payload
    if changed:
        # Preserve each actual observation, with its real collection time.
        snapshot = root / "logs" / "premarket-external-snapshots" / now.date().isoformat() / (now.strftime("%H%M%S") + ".json")
        if not snapshot.exists():
            write_json_atomic(snapshot, {"collected_at": iso(now), "rows": rows})
        write_json_atomic(path, updated)
    write_json_atomic(state_path, {"checked_at": iso(now), "received": len(rows), "errors": errors,
                                  "changed": changed, "auction_available": False})
    return changed

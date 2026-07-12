from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from v2_platform.learning import TradingCalendar, as_dict, as_list, load_json


EASTMONEY_TOKEN = "7eea3edcaed734bea9cbfc24409ed989"
UP_URL = "https://push2ex.eastmoney.com/getTopicZTPool"
DOWN_URL = "https://push2ex.eastmoney.com/getTopicDTPool"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
TENCENT_URL = "https://qt.gtimg.cn/q="


def fetch_json(url: str, params: dict[str, str], timeout: int = 20) -> dict[str, Any]:
    request_url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(request_url, headers={"User-Agent": "Mozilla/5.0 V2Research/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as first_error:
        proc = subprocess.run(
            ["curl", "-L", "--fail", "--silent", "--show-error", "--max-time", str(timeout), request_url],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"source_fetch_failed:{type(first_error).__name__}:{proc.stderr.strip()[:160]}") from first_error
        payload = json.loads(proc.stdout)
    if not isinstance(payload, dict):
        raise ValueError("response_not_object")
    return payload


def fetch_tencent_quotes(codes: list[str], timeout: int = 20) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    url = TENCENT_URL + ",".join(codes)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 V2Research/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except Exception as first_error:
        proc = subprocess.run(
            ["curl", "-L", "--fail", "--silent", "--show-error", "--max-time", str(timeout), url],
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"tencent_quote_failed:{type(first_error).__name__}:{proc.stderr.decode(errors='ignore')[:160]}") from first_error
        raw = proc.stdout
    text_value = raw.decode("gb18030", errors="replace")
    result = {}
    for line in text_value.splitlines():
        if '="' not in line:
            continue
        variable, value = line.split('="', 1)
        code = variable.removeprefix("v_")
        parts = value.rstrip('";').split("~")
        if len(parts) < 35 or not parts[3] or not parts[4] or not parts[33] or not parts[34]:
            continue
        result[code] = {
            "name": parts[1],
            "code": parts[2],
            "close": float(parts[3]),
            "previous_close": float(parts[4]),
            "volume": float(parts[6] or 0),
            "high": float(parts[33]),
            "low": float(parts[34]),
            "as_of": parts[30],
        }
    return result


class V2SentimentCollector:
    def __init__(
        self,
        root: Path,
        *,
        fetcher: Callable[[str, dict[str, str]], dict[str, Any]] = fetch_json,
        quote_fetcher: Callable[[list[str]], dict[str, dict[str, Any]]] = fetch_tencent_quotes,
    ) -> None:
        self.root = root.resolve()
        self.fetcher = fetcher
        self.quote_fetcher = quote_fetcher
        self.calendar = TradingCalendar(load_json(self.root / "config" / "v2-market-calendar.json"), "CN")

    def collect(self, trade_date: date) -> dict[str, Any]:
        if self.calendar.is_open(trade_date) is not True:
            raise ValueError("trade_date_not_verified_open_day")
        previous = self._previous_open_day(trade_date)
        current_up_raw = self._pool(UP_URL, trade_date, "fbt:asc")
        current_down_raw = self._pool(DOWN_URL, trade_date, "fund:asc")
        previous_up_raw = self._pool(UP_URL, previous, "fbt:asc", allow_qdate_mismatch=True) if previous else {"tc": 0, "pool": [], "quality_flags": []}
        current_up, up_exclusions = self._clean(as_list(current_up_raw.get("pool")))
        current_down, down_exclusions = self._clean(as_list(current_down_raw.get("pool")))
        previous_up, _ = self._clean(as_list(previous_up_raw.get("pool")))
        promotion = self._promotion(previous_up, current_up)
        promotion["previous_trade_date"] = previous.isoformat() if previous else None
        if previous_up_raw.get("quality_flags"):
            promotion["state"] = "degraded_response_date_unverified"
            promotion["quality_flags"] = previous_up_raw["quality_flags"]
        high_level = self._high_level_loss(previous_up, trade_date)
        observed_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        source_url = f"{UP_URL} ; {DOWN_URL}"
        return {
            "schema_version": 1,
            "trade_date": trade_date.isoformat(),
            "as_of": f"{trade_date.isoformat()}T15:00:00+08:00",
            "observed_at": observed_at,
            "source_url": source_url,
            "source_type": "mainstream_market_data",
            "source_name": "东方财富涨跌停股池",
            "scope": "沪深A股；剔除名称含ST/退市及N/C前缀新股；不含北交所。",
            "limit_up_count_raw": int(current_up_raw.get("tc") or len(as_list(current_up_raw.get("pool")))),
            "limit_down_count_raw": int(current_down_raw.get("tc") or len(as_list(current_down_raw.get("pool")))),
            "limit_up_ladder": {
                "state": "usable" if current_up else "empty_or_missing",
                "items": self._ladder(current_up, "lbc"),
                "filtered_count": len(current_up),
                "excluded": up_exclusions,
            },
            "limit_down_ladder": {
                "state": "usable" if current_down else "empty_or_missing",
                "items": self._ladder(current_down, "days"),
                "filtered_count": len(current_down),
                "excluded": down_exclusions,
            },
            "promotion_rate": promotion,
            "high_level_loss_effect": high_level,
            "quality_flags": (["limit_up_raw_count_differs_from_filtered"] if int(current_up_raw.get("tc") or 0) != len(current_up) else []) + (["limit_down_raw_count_differs_from_filtered"] if int(current_down_raw.get("tc") or 0) != len(current_down) else []),
        }

    def _pool(self, url: str, day: date, sort: str, *, allow_qdate_mismatch: bool = False) -> dict[str, Any]:
        payload = self.fetcher(
            url,
            {
                "ut": EASTMONEY_TOKEN,
                "dpt": "wz.ztzt",
                "Pageindex": "0",
                "pagesize": "10000",
                "sort": sort,
                "date": day.strftime("%Y%m%d"),
            },
        )
        if payload.get("rc") != 0:
            raise ValueError(f"source_rc_{payload.get('rc')}")
        data = as_dict(payload.get("data"))
        qdate = str(data.get("qdate") or "")
        if qdate and qdate != day.strftime("%Y%m%d"):
            if not allow_qdate_mismatch:
                raise ValueError("source_trade_date_mismatch")
            flags = [f"response_qdate_{qdate}_differs_from_requested_{day.strftime('%Y%m%d')}"]
        else:
            flags = []
        return {"tc": data.get("tc"), "pool": as_list(data.get("pool")), "quality_flags": flags}

    def _previous_open_day(self, day: date) -> date | None:
        cursor = day - timedelta(days=1)
        for _ in range(15):
            state = self.calendar.is_open(cursor)
            if state is None:
                return None
            if state:
                return cursor
            cursor -= timedelta(days=1)
        return None

    def _high_level_loss(self, previous_up: list[dict[str, Any]], trade_date: date) -> dict[str, Any]:
        candidates = []
        for item in previous_up:
            try:
                height = int(item.get("lbc") or 1)
            except (TypeError, ValueError):
                height = 1
            if height >= 2:
                candidates.append(item)
        if not candidates:
            return {
                "state": "data_missing",
                "sample_count": 0,
                "median_return_pct": None,
                "max_adverse_excursion_pct": None,
                "note": "昨日涨停池没有可识别的二板及以上样本，无法判断高位亏钱效应。",
            }
        rows = []
        missing = []
        codes = [f"{'sh' if item.get('m') == 1 else 'sz'}{item.get('c')}" for item in candidates]
        try:
            quotes = self.quote_fetcher(codes)
        except Exception as exc:
            quotes = {}
            missing.append({"code": "batch", "name": "腾讯批量行情", "reason": str(exc)})
        for item in candidates:
            code = f"{'sh' if item.get('m') == 1 else 'sz'}{item.get('c')}"
            quote = quotes.get(code)
            if not quote:
                missing.append({"code": item.get("c"), "name": item.get("n"), "reason": "quote_missing"})
                continue
            quote_time = str(quote.get("as_of") or "")
            if not quote_time.startswith(trade_date.strftime("%Y%m%d")):
                missing.append({"code": item.get("c"), "name": item.get("n"), "reason": "quote_trade_date_mismatch"})
                continue
            previous_close = float(quote["previous_close"])
            close = float(quote["close"])
            low = float(quote["low"])
            if previous_close <= 0 or close <= 0 or low <= 0 or float(quote.get("volume") or 0) <= 0:
                missing.append({"code": item.get("c"), "name": item.get("n"), "reason": "quote_nonpositive_or_no_trade"})
                continue
            rows.append(
                {
                    "code": code,
                    "name": item.get("n"),
                    "previous_height": int(item.get("lbc") or 1),
                    "trade_date": trade_date.isoformat(),
                    "previous_close": previous_close,
                    "close": close,
                    "low": low,
                    "close_return_pct": round((close / previous_close - 1) * 100, 4),
                    "low_return_pct": round((low / previous_close - 1) * 100, 4),
                    "quote_as_of": quote_time,
                }
            )
        if not rows:
            return {
                "state": "data_missing",
                "sample_count": 0,
                "median_return_pct": None,
                "max_adverse_excursion_pct": None,
                "missing": missing,
                "note": "未取得昨日高位股的可审计日线，不做亏钱效应判断。",
            }
        closes = sorted(float(item["close_return_pct"]) for item in rows)
        middle = len(closes) // 2
        median = closes[middle] if len(closes) % 2 else (closes[middle - 1] + closes[middle]) / 2
        worst = min(float(item["low_return_pct"]) for item in rows)
        negative_ratio = sum(value < 0 for value in closes) / len(closes)
        if median <= -3 or (negative_ratio >= 2 / 3 and worst <= -8):
            judgement = "高位亏钱效应明显"
        elif median < 0:
            judgement = "高位股整体偏弱"
        else:
            judgement = "样本未显示整体负收益，但仍需观察盘中最大不利波动"
        return {
            "state": "usable" if not missing else "partial",
            "sample_count": len(rows),
            "candidate_count": len(candidates),
            "median_return_pct": round(median, 4),
            "negative_ratio": round(negative_ratio, 4),
            "max_adverse_excursion_pct": round(worst, 4),
            "judgement": judgement,
            "stocks": rows,
            "missing": missing,
            "source": TENCENT_URL,
        }

    @staticmethod
    def _clean(items: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        rows = []
        exclusions = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("n") or "")
            code = str(item.get("c") or "")
            market = item.get("m")
            reason = None
            if market not in {0, 1}:
                reason = "non_sh_sz_market"
            elif "ST" in name.upper() or "退" in name:
                reason = "risk_or_delisting_name"
            elif name.startswith(("N", "C")):
                reason = "recent_listing_prefix"
            if reason:
                exclusions.append({"code": code, "name": name, "reason": reason})
                continue
            rows.append(item)
        return rows, exclusions

    @staticmethod
    def _ladder(items: list[dict[str, Any]], height_field: str) -> list[dict[str, Any]]:
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            try:
                height = max(1, int(item.get(height_field) or 1))
            except (TypeError, ValueError):
                height = 1
            grouped[height].append(item)
        rows = []
        for height in sorted(grouped, reverse=True):
            stocks = [
                {
                    "code": f"{'sh' if item.get('m') == 1 else 'sz'}{item.get('c')}",
                    "name": item.get("n"),
                    "change_pct": item.get("zdp"),
                    "industry": item.get("hybk"),
                    "open_count": item.get("zbc", item.get("oc")),
                }
                for item in grouped[height]
            ]
            rows.append({"height": height, "count": len(stocks), "stocks": stocks})
        return rows

    @staticmethod
    def _promotion(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, Any]:
        current_by_code = {str(item.get("c")): item for item in current}
        by_height: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for item in previous:
            try:
                height = max(1, int(item.get("lbc") or 1))
            except (TypeError, ValueError):
                height = 1
            by_height[height].append(item)
        rows = []
        for height in sorted(by_height):
            candidates = by_height[height]
            promoted = [item for item in candidates if int(current_by_code.get(str(item.get("c")), {}).get("lbc") or 0) >= height + 1]
            rows.append(
                {
                    "from_height": height,
                    "candidate_count": len(candidates),
                    "promoted_count": len(promoted),
                    "rate": round(len(promoted) / len(candidates), 4) if candidates else None,
                    "promoted_stocks": [item.get("n") for item in promoted],
                }
            )
        return {"state": "usable" if rows else "data_missing", "previous_trade_date": None, "items": rows}

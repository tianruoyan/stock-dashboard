from __future__ import annotations

import json
import statistics
import urllib.parse
import urllib.request
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from v2_platform.sentiment_collector import fetch_tencent_quotes

from .io import load_json


CHINA_TZ = timezone(timedelta(hours=8))
SINA_KLINE = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
EASTMONEY_CURRENT_FLOW = "https://push2.eastmoney.com/api/qt/ulist.np/get"
EASTMONEY_DAILY_FLOW = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
EASTMONEY_TOKEN = "b2884a393a59ad64002292a3e90d46a5"


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _quote_iso(raw: Any) -> str | None:
    try:
        return datetime.strptime(str(raw), "%Y%m%d%H%M%S").replace(tzinfo=CHINA_TZ).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def _session_fraction(now: datetime) -> float | None:
    local = now.astimezone(CHINA_TZ)
    current = local.time()
    morning_open, morning_close = time(9, 30), time(11, 30)
    afternoon_open, afternoon_close = time(13, 0), time(15, 0)
    if current < morning_open:
        return None
    if current <= morning_close:
        elapsed = (local - local.replace(hour=9, minute=30, second=0, microsecond=0)).total_seconds() / 60
    elif current < afternoon_open:
        elapsed = 120
    elif current <= afternoon_close:
        elapsed = 120 + (local - local.replace(hour=13, minute=0, second=0, microsecond=0)).total_seconds() / 60
    else:
        elapsed = 240
    return max(min(elapsed / 240, 1), 1 / 240)


class LiveSnapshotCollector:
    """Collect only auditable public facts; missing fields remain missing."""

    def __init__(
        self,
        root: Path,
        *,
        quote_fetcher: Callable[[list[str]], dict[str, dict[str, Any]]] = fetch_tencent_quotes,
        kline_fetcher: Callable[[str], list[dict[str, Any]]] | None = None,
        fund_flow_fetcher: Callable[[list[str], str], dict[str, Any]] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.module_root = self.root / "ai_hardware_monitor"
        self.quote_fetcher = quote_fetcher
        self.kline_fetcher = kline_fetcher or self._fetch_kline
        self.fund_flow_fetcher = fund_flow_fetcher or self._fetch_fund_flow
        self.stocks_config = load_json(self.module_root / "config" / "stocks.json")

    def collect(self, *, now: datetime) -> dict[str, Any]:
        local_now = now.astimezone(CHINA_TZ)
        trade_date = local_now.date().isoformat()
        stock_defs = self.stocks_config.get("stocks") if isinstance(self.stocks_config.get("stocks"), list) else []
        benchmark = self.stocks_config.get("benchmark") if isinstance(self.stocks_config.get("benchmark"), dict) else {}
        codes = [str(item["code"]) for item in stock_defs if isinstance(item, dict) and item.get("code")]
        benchmark_code = str(benchmark.get("code") or "sh000300")
        missing: list[str] = []
        sources: list[dict[str, Any]] = []

        try:
            quotes = self.quote_fetcher(codes + [benchmark_code])
            sources.append({"id": "tencent_realtime_quote", "state": "usable"})
        except Exception as exc:
            quotes = {}
            sources.append({"id": "tencent_realtime_quote", "state": "failed", "detail": type(exc).__name__})
            missing.append("股票池与沪深300实时行情")

        pace_fraction = _session_fraction(local_now)
        stock_rows: list[dict[str, Any]] = []
        quote_times: list[str] = []
        kline_success = 0
        for definition in stock_defs:
            if not isinstance(definition, dict):
                continue
            code = str(definition.get("code") or "")
            quote = quotes.get(code)
            if not isinstance(quote, dict):
                missing.append(f"{definition.get('name')}实时行情")
                continue
            quote_as_of = _quote_iso(quote.get("as_of"))
            if not quote_as_of or not str(quote.get("as_of") or "").startswith(trade_date.replace("-", "")):
                missing.append(f"{definition.get('name')}当日行情")
                continue
            try:
                close = float(quote["close"])
                previous_close = float(quote["previous_close"])
                change_pct = (close / previous_close - 1) * 100
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                missing.append(f"{definition.get('name')}有效价格")
                continue
            bars: list[dict[str, Any]] = []
            try:
                bars = self.kline_fetcher(code)
                kline_success += 1
            except Exception:
                missing.append(f"{definition.get('name')}日K")
            closes = [float(item["close"]) for item in bars[-10:] if float(item.get("close") or 0) > 0]
            volumes = [float(item["volume"]) for item in bars[-5:] if float(item.get("volume") or 0) > 0]
            ma5 = statistics.fmean(closes[-5:]) if len(closes) >= 5 else None
            ma10 = statistics.fmean(closes[-10:]) if len(closes) >= 10 else None
            # 腾讯A股主板/创业板字段为手，科创板字段为股；先统一成股再与日K比较。
            raw_volume = float(quote.get("volume") or 0)
            current_volume_shares = raw_volume if code.startswith("sh68") else raw_volume * 100
            expected_volume = statistics.fmean(volumes) * pace_fraction if len(volumes) >= 5 and pace_fraction else None
            turnover_pace = current_volume_shares / expected_volume if expected_volume and expected_volume > 0 else None
            row = {
                "code": code,
                "name": definition.get("name"),
                "segment": definition.get("segment"),
                "role": definition.get("role"),
                "price": round(close, 4),
                "change_pct": round(change_pct, 4),
                "amount_yi": quote.get("amount_yi"),
                "turnover_pace": round(turnover_pace, 4) if turnover_pace is not None else None,
                "ma5": round(ma5, 4) if ma5 is not None else None,
                "ma10": round(ma10, 4) if ma10 is not None else None,
                "above_ma5": close > ma5 if ma5 is not None else None,
                "above_ma10": close > ma10 if ma10 is not None else None,
                "quote_as_of": quote_as_of,
                "quote_source": "腾讯财经公开行情",
                "trend_source": "新浪财经公开日K" if bars else None,
            }
            stock_rows.append(row)
            quote_times.append(quote_as_of)

        if kline_success:
            sources.append({"id": "sina_daily_kline", "state": "usable" if kline_success == len(stock_defs) else "degraded"})
        else:
            sources.append({"id": "sina_daily_kline", "state": "failed"})

        proxy_change = statistics.fmean(float(item["change_pct"]) for item in stock_rows) if stock_rows else None
        benchmark_quote = quotes.get(benchmark_code)
        benchmark_change = None
        if isinstance(benchmark_quote, dict):
            try:
                benchmark_change = (float(benchmark_quote["close"]) / float(benchmark_quote["previous_close"]) - 1) * 100
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                pass
        if benchmark_change is None:
            missing.append("沪深300当日涨跌幅")
        advance_ratio = (sum(1 for item in stock_rows if float(item["change_pct"]) > 0) / len(stock_rows) * 100) if stock_rows else None

        market_rank = None
        comparable_count = None
        try:
            industry_codes = [f"pt01801{index:03d}" for index in range(1, 501)]
            industry_quotes: dict[str, dict[str, Any]] = {}
            for offset in range(0, len(industry_codes), 80):
                industry_quotes.update(self.quote_fetcher(industry_codes[offset : offset + 80]))
            industry_changes = []
            for quote in industry_quotes.values():
                quote_day = str(quote.get("as_of") or "")[:8]
                try:
                    if quote_day == trade_date.replace("-", ""):
                        industry_changes.append((float(quote["close"]) / float(quote["previous_close"]) - 1) * 100)
                except (KeyError, TypeError, ValueError, ZeroDivisionError):
                    continue
            if proxy_change is not None and len(industry_changes) >= 50:
                market_rank = 1 + sum(1 for value in industry_changes if value > proxy_change)
                comparable_count = len(industry_changes)
                sources.append({"id": "tencent_industry_rank", "state": "usable", "comparable_count": comparable_count})
            else:
                missing.append("AI硬件代理篮子可比行业排名")
        except Exception as exc:
            sources.append({"id": "tencent_industry_rank", "state": "failed", "detail": type(exc).__name__})
            missing.append("AI硬件代理篮子可比行业排名")

        core_codes = {str(value) for value in self.stocks_config.get("core_leader_codes", [])}
        core_rows = [item for item in stock_rows if item.get("code") in core_codes]
        outperform_count = sum(1 for item in core_rows if proxy_change is not None and float(item["change_pct"]) > proxy_change)
        valid_paces = [float(item["turnover_pace"]) for item in core_rows if item.get("turnover_pace") is not None]
        trend_count = sum(1 for item in core_rows if item.get("above_ma5") is True and item.get("above_ma10") is True)

        funds = {"continuous_net_inflow_days": None, "pool_net_inflow_yi": None, "etf_net_inflow_yi": None}
        try:
            flow = self.fund_flow_fetcher(codes, trade_date)
            if isinstance(flow, dict):
                funds.update({key: flow.get(key) for key in funds if key in flow})
                sources.append({"id": "eastmoney_pool_fund_flow", "state": flow.get("quality_state") or "degraded"})
        except Exception as exc:
            sources.append({"id": "eastmoney_pool_fund_flow", "state": "failed", "detail": type(exc).__name__})

        environment = self._governed_environment(trade_date)
        if environment.pop("_used", False):
            sources.append({"id": "v2_governed_environment", "state": "usable"})
        else:
            sources.append({"id": "v2_governed_environment", "state": "waiting"})

        snapshot: dict[str, Any] = {
            "schema_version": 1,
            "model_version": "1.0.0",
            "trade_date": trade_date,
            "as_of": max(quote_times) if quote_times else local_now.isoformat(timespec="seconds"),
            "collection_mode": "live_public_facts",
            "source_quality": {
                "state": "usable" if len(stock_rows) == len(stock_defs) and benchmark_change is not None and kline_success == len(stock_defs) else "degraded",
                "sources": sources,
                "missing": missing,
            },
            "sector": {
                "proxy_id": "ai_hardware_equal_weight_v1",
                "proxy_change_pct": round(proxy_change, 4) if proxy_change is not None else None,
                "benchmark_change_pct": round(benchmark_change, 4) if benchmark_change is not None else None,
                "relative_outperformance_pct": round(proxy_change - benchmark_change, 4) if proxy_change is not None and benchmark_change is not None else None,
                "market_rank": market_rank,
                "comparable_theme_count": comparable_count,
                "rank_universe": "腾讯98个行业指数" if comparable_count else None,
                "advance_ratio_pct": round(advance_ratio, 4) if advance_ratio is not None else None,
            },
            "leaders": {
                "core_count": len(core_rows),
                "outperform_count": outperform_count if core_rows and proxy_change is not None else None,
                "outperform_ratio": round(outperform_count / len(core_rows), 4) if core_rows and proxy_change is not None else None,
                "median_turnover_pace": round(statistics.median(valid_paces), 4) if valid_paces else None,
                "trend_confirmed_count": trend_count if core_rows else None,
                "trend_confirmed_ratio": round(trend_count / len(core_rows), 4) if core_rows else None,
            },
            "funds": funds,
            "market_environment": environment,
            "stocks": stock_rows,
        }
        overlay = load_json(self.module_root / "data" / "upstream-snapshot.json")
        if isinstance(overlay, dict) and overlay.get("trade_date") == trade_date:
            snapshot = _deep_merge(snapshot, overlay)
            snapshot["source_quality"].setdefault("sources", []).append({"id": "governed_sector_and_fund_input", "state": "usable"})
        else:
            remaining = []
            if snapshot["sector"].get("market_rank") is None:
                remaining.append("AI硬件代理篮子可比行业排名")
            if snapshot["funds"].get("continuous_net_inflow_days") is None:
                remaining.append("连续资金净流入天数")
            if snapshot["funds"].get("pool_net_inflow_yi") is None:
                remaining.append("股票池净流入")
            if snapshot["funds"].get("etf_net_inflow_yi") is None:
                remaining.append("相关ETF净流入")
            if snapshot["market_environment"].get("market_turnover_ratio") is None:
                remaining.append("两市成交额可比基线")
            if snapshot["market_environment"].get("technology_advance_ratio_pct") is None:
                remaining.append("科技股上涨宽度")
            if snapshot["market_environment"].get("limit_up_down_ratio") is None:
                remaining.append("同交易日涨跌停结构")
            snapshot["source_quality"]["missing"] = list(dict.fromkeys(snapshot["source_quality"]["missing"] + remaining))
            snapshot["source_quality"]["state"] = "degraded"
        return snapshot

    def _governed_environment(self, trade_date: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "market_turnover_ratio": None,
            "technology_advance_ratio_pct": None,
            "limit_up_down_ratio": None,
            "_used": False,
        }
        liquidity = load_json(self.root / "data" / "v2" / "inputs" / "market-liquidity.json")
        if liquidity.get("trade_date") == trade_date:
            change = liquidity.get("turnover_change_pct")
            try:
                result["market_turnover_ratio"] = round(1 + float(change) / 100, 4) if change is not None else None
                result["_used"] = True
            except (TypeError, ValueError):
                pass
        sentiment = load_json(self.root / "data" / "v2" / "inputs" / "sentiment-structure.json")
        if sentiment.get("trade_date") == trade_date:
            up = sentiment.get("limit_up_count_raw")
            down = sentiment.get("limit_down_count_raw")
            try:
                result["limit_up_down_ratio"] = round(float(up) / max(float(down), 1), 4)
                result["_used"] = True
            except (TypeError, ValueError):
                pass
        return result

    @staticmethod
    def _fetch_kline(code: str) -> list[dict[str, Any]]:
        url = f"{SINA_KLINE}?{urllib.parse.urlencode({'symbol': code, 'scale': 240, 'ma': 'no', 'datalen': 30})}"
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quotes.sina.cn/"})
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise ValueError("kline_response_not_list")
        return [item for item in payload if isinstance(item, dict) and item.get("day")]

    @staticmethod
    def _fetch_json(url: str, params: dict[str, str]) -> dict[str, Any]:
        request_url = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(request_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("rc") != 0:
            raise ValueError("fund_flow_response_invalid")
        return payload

    @classmethod
    def _fetch_fund_flow(cls, codes: list[str], trade_date: str) -> dict[str, Any]:
        secids = [f"{1 if code.startswith('sh') else 0}.{code[2:]}" for code in codes]
        current = cls._fetch_json(
            EASTMONEY_CURRENT_FLOW,
            {"fltt": "2", "invt": "2", "fields": "f12,f14,f62", "secids": ",".join(secids)},
        )
        current_rows = ((current.get("data") or {}).get("diff") or [])
        current_values = []
        for item in current_rows if isinstance(current_rows, list) else []:
            try:
                current_values.append(float(item["f62"]))
            except (KeyError, TypeError, ValueError):
                continue
        pool_current = sum(current_values) if len(current_values) == len(codes) else None

        by_day: dict[str, float] = {}
        history_success = 0
        for secid in secids:
            try:
                payload = cls._fetch_json(
                    EASTMONEY_DAILY_FLOW,
                    {
                        "secid": secid,
                        "lmt": "8",
                        "klt": "101",
                        "fields1": "f1,f2,f3,f7",
                        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
                        "ut": EASTMONEY_TOKEN,
                    },
                )
                rows = ((payload.get("data") or {}).get("klines") or [])
                parsed = 0
                for raw in rows if isinstance(rows, list) else []:
                    parts = str(raw).split(",")
                    if len(parts) < 2:
                        continue
                    by_day[parts[0]] = by_day.get(parts[0], 0.0) + float(parts[1])
                    parsed += 1
                if parsed:
                    history_success += 1
            except Exception:
                continue
        continuous_days = None
        if history_success == len(codes) and pool_current is not None:
            by_day[trade_date] = pool_current
            continuous_days = 0
            for day in sorted(by_day, reverse=True):
                if day > trade_date:
                    continue
                if by_day[day] > 0:
                    continuous_days += 1
                else:
                    break
        return {
            "continuous_net_inflow_days": continuous_days,
            "pool_net_inflow_yi": round(pool_current / 100_000_000, 4) if pool_current is not None else None,
            "etf_net_inflow_yi": None,
            "quality_state": "usable" if history_success == len(codes) and pool_current is not None else "degraded",
        }

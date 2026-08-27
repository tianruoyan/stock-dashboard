from __future__ import annotations

import contextlib
import io
import urllib.parse
import warnings
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from v2_platform.learning import TradingCalendar, as_list, load_json, write_json
from v2_platform.sentiment_collector import fetch_json, fetch_tencent_quotes


EASTMONEY_UNIVERSE_URL = "https://82.push2.eastmoney.com/api/qt/clist/get"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
CHINA_TZ = ZoneInfo("Asia/Shanghai")
NEW_YORK_TZ = ZoneInfo("America/New_York")
SEOUL_TZ = ZoneInfo("Asia/Seoul")


def now_china() -> datetime:
    return datetime.now(timezone.utc).astimezone(CHINA_TZ)


def fetch_sina_universe() -> list[dict[str, Any]]:
    with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        warnings.simplefilter("ignore")
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("akshare_not_available_for_sina_fallback") from exc
        frame = ak.stock_zh_a_spot()
    return frame.to_dict("records")


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_universe_time(rows: list[dict[str, Any]], observed_at: datetime, trade_date: date) -> datetime:
    timestamps = [int(value) for row in rows if (value := number(row.get("f124"))) and value > 0]
    if timestamps:
        resolved = datetime.fromtimestamp(max(timestamps), tz=CHINA_TZ)
    elif observed_at.date() == trade_date:
        resolved = observed_at
    else:
        raise ValueError("universe_quote_time_missing_for_historical_date")
    if resolved.date() != trade_date:
        raise ValueError("universe_quote_trade_date_mismatch")
    return resolved


def parse_tencent_time(raw: Any, market: str) -> datetime | None:
    value = str(raw or "").strip()
    formats = ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S")
    for pattern in formats:
        try:
            parsed = datetime.strptime(value, pattern)
        except ValueError:
            continue
        source_tz = NEW_YORK_TZ if market == "US" else (SEOUL_TZ if market == "KR" else CHINA_TZ)
        return parsed.replace(tzinfo=source_tz).astimezone(CHINA_TZ)
    return None


class V2MarketFactCollector:
    """Collect public market facts without creating AI-derived facts or user data."""

    def __init__(
        self,
        root: Path,
        *,
        universe_fetcher: Callable[[str, dict[str, str]], dict[str, Any]] = fetch_json,
        sina_universe_fetcher: Callable[[], list[dict[str, Any]]] = fetch_sina_universe,
        quote_fetcher: Callable[[list[str]], dict[str, dict[str, Any]]] = fetch_tencent_quotes,
        clock: Callable[[], datetime] = now_china,
    ) -> None:
        self.root = root.resolve()
        self.universe_fetcher = universe_fetcher
        self.sina_universe_fetcher = sina_universe_fetcher
        self.quote_fetcher = quote_fetcher
        self.clock = clock
        self.calendar = TradingCalendar(load_json(self.root / "config/v2-market-calendar.json"), "CN")

    def collect(self, trade_date: date, *, observed_at: datetime | None = None) -> dict[str, Any]:
        if self.calendar.is_open(trade_date) is not True:
            raise ValueError("trade_date_not_verified_open_day")
        observed = observed_at or self.clock()
        if observed.tzinfo is None:
            raise ValueError("observed_at_timezone_required")
        observed = observed.astimezone(CHINA_TZ)
        try:
            universe = self._universe(trade_date, observed)
        except Exception as exc:
            retained = self._retained_same_day_outputs(trade_date, observed)
            if retained is None:
                raise
            report = {
                "schema_version": 1,
                "version": "2026-07-30.s2.2",
                "mode": "shadow_only",
                "trade_date": trade_date.isoformat(),
                "generated_at": observed.isoformat(timespec="seconds"),
                "state": "waiting_update",
                "summary": "实时行情源暂时不可用，继续使用今天最近一次已核验数据，恢复后自动更新。",
                "source_error": f"{type(exc).__name__}:{str(exc)[:160]}",
                "outputs": [
                    {
                        "id": filename.removesuffix(".json"),
                        "as_of": payload.get("as_of"),
                        "quality_state": "waiting_update",
                        "retained_quality_state": payload.get("quality_state"),
                    }
                    for filename, payload in retained.items()
                ],
                "guardrails": {
                    "public_sources_only": True,
                    "user_assets_read": False,
                    "user_assets_modified": False,
                    "missing_facts_ai_filled": False,
                    "automatic_trading": False,
                    "retained_previous_same_day_facts": True,
                    "cross_day_fallback_allowed": False,
                },
            }
            write_json(self.root / "data/v2/public-market-fact-health.json", report)
            return report
        breadth, liquidity = self._breadth_liquidity(universe)
        sentiment = load_json(self.root / "local_inputs/sentiment-structure.json")
        mainline = self._mainline(trade_date, universe["as_of"], sentiment, breadth)
        external = self._external(trade_date, observed)
        outputs = {
            "market-breadth.json": breadth,
            "market-liquidity.json": liquidity,
            "mainline-structure.json": mainline,
            "external-market.json": external,
        }
        for filename, payload in outputs.items():
            write_json(self.root / "local_inputs" / filename, payload)
        report = {
            "schema_version": 1,
            "version": "2026-07-19.s2.1",
            "mode": "shadow_only",
            "trade_date": trade_date.isoformat(),
            "generated_at": observed.isoformat(timespec="seconds"),
            "state": "usable" if breadth["quality_state"] == "usable" else "degraded",
            "outputs": [
                {
                    "id": filename.removesuffix(".json"),
                    "as_of": payload.get("as_of"),
                    "quality_state": payload.get("quality_state"),
                }
                for filename, payload in outputs.items()
            ],
            "guardrails": {
                "public_sources_only": True,
                "user_assets_read": False,
                "user_assets_modified": False,
                "missing_facts_ai_filled": False,
                "automatic_trading": False,
            },
        }
        write_json(self.root / "data/v2/public-market-fact-health.json", report)
        return report

    def _retained_same_day_outputs(
        self,
        trade_date: date,
        observed_at: datetime,
    ) -> dict[str, dict[str, Any]] | None:
        filenames = (
            "market-breadth.json",
            "market-liquidity.json",
            "mainline-structure.json",
            "external-market.json",
        )
        retained: dict[str, dict[str, Any]] = {}
        for filename in filenames:
            payload = load_json(self.root / "local_inputs" / filename)
            if payload.get("trade_date") != trade_date.isoformat():
                return None
            as_of = str(payload.get("as_of") or "")
            try:
                fact_time = datetime.fromisoformat(as_of)
            except ValueError:
                return None
            if fact_time.tzinfo is None:
                return None
            if fact_time.astimezone(CHINA_TZ) > observed_at + timedelta(minutes=2):
                return None
            retained[filename] = payload
        return retained

    def _universe(self, trade_date: date, observed_at: datetime) -> dict[str, Any]:
        params = {
            "pn": "1",
            "pz": "10000",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": "f2,f3,f6,f12,f13,f14,f124",
        }
        try:
            payload = self.universe_fetcher(EASTMONEY_UNIVERSE_URL, params)
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            rows = [item for item in as_list(data.get("diff")) if isinstance(item, dict)]
            if len(rows) < 4000:
                raise ValueError(f"universe_incomplete:{len(rows)}")
            quote_at = parse_universe_time(rows, observed_at, trade_date)
            return {
                "rows": rows,
                "as_of": quote_at.isoformat(timespec="seconds"),
                "source_id": "eastmoney_a_share_universe_live",
                "source_name": "东方财富沪深京A股公开行情",
                "source_url": f"{EASTMONEY_UNIVERSE_URL}?{urllib.parse.urlencode(params)}",
                "date_verification": "行情行时间戳",
            }
        except Exception as primary_error:
            rows = self._sina_universe(trade_date)
            if len(rows) < 4000:
                raise RuntimeError(f"universe_sources_failed:{type(primary_error).__name__}:sina_count_{len(rows)}") from primary_error
            return {
                "rows": rows,
                "as_of": rows[0]["_verified_as_of"],
                "source_id": "sina_a_share_universe_live",
                "source_name": "新浪财经A股公开行情",
                "source_url": "https://vip.stock.finance.sina.com.cn/mkt/#hs_a",
                "date_verification": "五个腾讯核心指数行情日期交叉核验",
            }

    def _sina_universe(self, trade_date: date) -> list[dict[str, Any]]:
        index_rows = [item for item in as_list(load_json(self.root / "data/intraday.json").get("indices")) if isinstance(item, dict)]
        verified_dates = {
            str(item.get("quote_time") or "")[:8]
            for item in index_rows
            if str(item.get("quote_time") or "")[:8].isdigit()
        }
        target = trade_date.strftime("%Y%m%d")
        if verified_dates != {target} or len(index_rows) < 4:
            raise ValueError("sina_universe_trade_date_not_cross_verified")
        raw_rows = self.sina_universe_fetcher()
        rows = []
        times = []
        for item in raw_rows:
            close = number(item.get("最新价"))
            pct = number(item.get("涨跌幅"))
            amount = number(item.get("成交额"))
            if close is None or pct is None or amount is None:
                continue
            raw_time = str(item.get("时间戳") or "15:00:00")
            try:
                parsed_time = datetime.strptime(raw_time, "%H:%M:%S").time()
            except ValueError:
                parsed_time = time(15, 0)
            if time(9, 15) <= parsed_time <= time(15, 30):
                times.append(parsed_time)
            rows.append({
                "f2": close,
                "f3": pct,
                "f6": amount,
                "f12": item.get("代码"),
                "f13": None,
                "f14": item.get("名称"),
            })
        quote_at = datetime.combine(trade_date, max(times, default=time(15, 0)), tzinfo=CHINA_TZ).isoformat(timespec="seconds")
        for row in rows:
            row["_verified_as_of"] = quote_at
        return rows

    def _breadth_liquidity(self, universe: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        rows = universe["rows"]
        valid = [row for row in rows if number(row.get("f3")) is not None and number(row.get("f2")) not in {None, 0}]
        advance = sum(1 for row in valid if float(row["f3"]) > 0)
        decline = sum(1 for row in valid if float(row["f3"]) < 0)
        flat = sum(1 for row in valid if float(row["f3"]) == 0)
        amounts = sorted(
            ((float(value), row) for row in valid if (value := number(row.get("f6"))) is not None and value >= 0),
            key=lambda item: item[0],
        )
        total_turnover = sum(value for value, _ in amounts) / 100_000_000
        top20 = sum(value for value, _ in amounts[-20:]) / 100_000_000
        concentration = top20 / total_turnover * 100 if total_turnover > 0 else None
        primary_source = universe["source_id"] == "eastmoney_a_share_universe_live"
        quality = "usable" if len(valid) >= 4000 and primary_source else "degraded"
        breadth = {
            "schema_version": 1,
            "trade_date": str(universe["as_of"])[:10],
            "as_of": universe["as_of"],
            "source_id": universe["source_id"],
            "source_name": universe["source_name"],
            "source_url": universe["source_url"],
            "universe_definition_id": "cn_a_sh_sz_bj_valid_quote_v2",
            "scope": "沪深京A股；仅统计具有有效价格和涨跌幅的证券。",
            "advance_count": advance,
            "decline_count": decline,
            "flat_count": flat,
            "total_count": len(valid),
            "missing_quote_count": len(rows) - len(valid),
            "quality_state": quality,
            "method_version": "live_breadth_v2",
            "quality_note": "主来源完整返回。" if primary_source else "主来源未返回，使用新浪公开行情并以腾讯核心指数日期交叉核验。",
        }
        liquidity = {
            "schema_version": 1,
            "trade_date": breadth["trade_date"],
            "as_of": universe["as_of"],
            "source_id": f"{universe['source_id']}_turnover",
            "source_name": universe["source_name"],
            "source_url": universe["source_url"],
            "scope": "沪深京A股当前累计成交额",
            "total_turnover": round(total_turnover, 2),
            "unit": "亿元",
            "turnover_change_pct": None,
            "comparison_method": "当前累计成交额；上一交易日同一时点基线尚待自动积累",
            "top_concentration_pct": round(concentration, 4) if concentration is not None else None,
            "concentration_method": "成交额前20只占当前全市场累计成交额",
            "quality_state": "degraded" if concentration is not None else "unknown",
            "method_version": "live_liquidity_v2",
            "missing_evidence": ["上一交易日同一时点成交额基线"],
            "date_verification": universe.get("date_verification"),
        }
        return breadth, liquidity

    def _mainline(
        self,
        trade_date: date,
        as_of: str,
        sentiment: dict[str, Any],
        breadth: dict[str, Any],
    ) -> dict[str, Any]:
        if sentiment.get("trade_date") != trade_date.isoformat():
            return self._empty_mainline(trade_date, as_of, "涨跌停梯队与当前交易日不一致")
        grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"up": [], "down": []})
        for side, key in (("up", "limit_up_ladder"), ("down", "limit_down_ladder")):
            ladder = sentiment.get(key) if isinstance(sentiment.get(key), dict) else {}
            for level in as_list(ladder.get("items")):
                if not isinstance(level, dict):
                    continue
                for stock in as_list(level.get("stocks")):
                    if not isinstance(stock, dict):
                        continue
                    industry = str(stock.get("industry") or "行业待分类").strip()
                    grouped[industry][side].append(stock)
        ranked = sorted(grouped.items(), key=lambda item: len(item[1]["up"]) + len(item[1]["down"]), reverse=True)
        themes = []
        for industry, sides in ranked[:6]:
            up, down = sides["up"], sides["down"]
            if len(up) + len(down) < 2:
                continue
            if len(up) >= 2 and len(up) >= max(2, len(down) * 2):
                state = "partial_support"
                conclusion = "涨停代表较集中，但仍需行业宽度、成交和非涨停中军确认。"
            elif len(down) >= 2 and len(down) >= max(2, len(up) * 2):
                state = "risk"
                conclusion = "跌停代表集中，当前按行业风险扩散观察。"
            else:
                state = "mixed"
                conclusion = "涨跌停代表同时存在，行业内部明显分化。"
            representatives = []
            for side_label, rows in (("涨停代表", up), ("跌停代表", down)):
                for stock in rows[:3]:
                    representatives.append({
                        "code": stock.get("code"),
                        "name": stock.get("name"),
                        "change_pct": stock.get("change_pct"),
                        "as_of": sentiment.get("as_of") or as_of,
                        "source": sentiment.get("source_name") or "东方财富涨跌停股池",
                        "role": side_label,
                    })
            themes.append({
                "theme": industry,
                "state": state,
                "fact": f"同口径涨停{len(up)}只、跌停{len(down)}只。",
                "conclusion": conclusion,
                "representative_securities": representatives,
            })
        broad_risk = breadth["decline_count"] > breadth["advance_count"] * 1.5
        support_themes = sum(item["state"] == "partial_support" for item in themes)
        risk_themes = sum(item["state"] == "risk" for item in themes)
        if broad_risk or risk_themes:
            level = "suppress"
            conclusion = "全市场宽度或涨跌停行业分布偏弱，局部强势不能直接升级为主线。"
        elif support_themes >= 2:
            level = "partial_support"
            conclusion = "多个行业出现涨停集中，但仍缺少完整行业宽度和成交扩散证据。"
        else:
            level = "unknown"
            conclusion = "涨跌停行业分布尚未形成可确认主线。"
        return {
            "schema_version": 1,
            "trade_date": trade_date.isoformat(),
            "as_of": sentiment.get("as_of") or as_of,
            "source_id": "price_limit_industry_distribution_live",
            "source_name": "东方财富涨跌停行业分布",
            "source_url": sentiment.get("source_url"),
            "scope": "沪深A股涨跌停池行业分布；不等同于全行业涨跌幅和成交宽度。",
            "support_level": level,
            "quality_state": "degraded",
            "method_version": "live_mainline_distribution_v2",
            "conclusion": conclusion,
            "themes": themes,
            "counter_evidence": ["涨跌停数量集中不等于行业全部个股和成交同步。"],
            "missing_evidence": ["完整行业上涨下跌宽度", "行业成交额与历史基线", "核心、中军和后排的连续时点确认"],
        }

    @staticmethod
    def _empty_mainline(trade_date: date, as_of: str, reason: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "trade_date": trade_date.isoformat(),
            "as_of": as_of,
            "source_id": "price_limit_industry_distribution_live",
            "source_name": "东方财富涨跌停行业分布",
            "source_url": None,
            "scope": "当前交易日主线事实",
            "support_level": "unknown",
            "quality_state": "unknown",
            "method_version": "live_mainline_distribution_v2",
            "conclusion": "当前没有足够证据判断主线。",
            "themes": [],
            "counter_evidence": [],
            "missing_evidence": [reason],
        }

    def _external(self, trade_date: date, observed_at: datetime) -> dict[str, Any]:
        codes = [
            "usIXIC", "usNVDA", "usMU",
            "hkHSI", "hkHSTECH", "hk00981", "hk01347",
            "kr005930", "kr000660",
        ]
        try:
            quotes = self.quote_fetcher(codes)
        except Exception:
            quotes = {}
        rows = []
        missing = []
        specs = [
            ("US", ["usIXIC", "usNVDA", "usMU"], "美股前一交易窗口"),
            ("HK", ["hkHSI", "hkHSTECH", "hk00981", "hk01347"], "港股当前交易窗口"),
            ("KR", ["kr005930", "kr000660"], "韩国半导体当前交易窗口"),
        ]
        display_names = {
            "kr005930": "三星电子",
            "kr000660": "SK海力士",
        }
        for market, market_codes, label in specs:
            samples = []
            for code in market_codes:
                quote = quotes.get(code)
                if not isinstance(quote, dict):
                    continue
                quote_at = parse_tencent_time(quote.get("as_of"), market)
                close, previous = number(quote.get("close")), number(quote.get("previous_close"))
                if not quote_at or close is None or previous in {None, 0} or quote_at > observed_at + timedelta(minutes=2):
                    continue
                age_days = (observed_at.date() - quote_at.date()).days
                if age_days < 0 or age_days > 4:
                    continue
                samples.append({
                    "name": display_names.get(code) or quote.get("name") or code,
                    "code": code,
                    "change_pct": round((close / float(previous) - 1) * 100, 4),
                    "as_of": quote_at.isoformat(timespec="seconds"),
                })
            if not samples:
                missing.append(f"{market}公开行情缺失或时点不可用")
                continue
            average = sum(item["change_pct"] for item in samples) / len(samples)
            direction = "up" if average > 0.3 else ("down" if average < -0.3 else "mixed")
            facts = "、".join(f"{item['name']}{item['change_pct']:+.2f}%" for item in samples)
            rows.append({
                "market": market,
                "a_share_trade_date": trade_date.isoformat(),
                "as_of": max(item["as_of"] for item in samples),
                "direction": direction,
                "mapping_eligible": True,
                "quality_state": "usable",
                "source_id": f"tencent_{market.lower()}_public_quotes",
                "source_name": "腾讯财经公开行情",
                "source_url": TENCENT_QUOTE_URL + ",".join(market_codes),
                "conclusion": f"{label}：{facts}；只用于映射验证，不机械推断A股涨跌。",
                "samples": samples,
            })
        directions = [item["direction"] for item in rows]
        conclusion = "已取得外盘公开行情，需结合A股代表股兑现或背离判断传导。" if rows else "外盘公开行情缺失，只保留为背景。"
        eligible_as_of = max(
            (str(item.get("as_of")) for item in rows if item.get("as_of")),
            default=observed_at.isoformat(timespec="seconds"),
        )
        return {
            "schema_version": 1,
            "trade_date": trade_date.isoformat(),
            "as_of": eligible_as_of,
            "collected_at": observed_at.isoformat(timespec="seconds"),
            "source_url": TENCENT_QUOTE_URL + ",".join(codes),
            "quality_state": "degraded" if missing else "usable",
            "conclusion": conclusion,
            "markets": rows,
            "missing_evidence": missing,
            "direction_summary": directions,
            "anti_lookahead": "每条外盘行情时间必须不晚于本次A股观察时间；a_share_trade_date只表示该事实被哪个A股交易日使用。",
        }

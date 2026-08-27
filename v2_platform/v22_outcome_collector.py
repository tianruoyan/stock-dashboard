from __future__ import annotations

import json
import time as time_module
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from v2_platform.learning import TradingCalendar, as_dict, as_list, load_json, write_json


SINA_KLINE = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
OUTPUT = "data/v2/v22/outcome-prices.json"
REPORT_OUTPUT = "data/v2/v22/outcome-price-report.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class V22OutcomePriceCollector:
    """Fill only due outcome windows from immutable V2.2 trigger snapshots."""

    def __init__(
        self,
        root: Path,
        *,
        fetcher: Callable[[str], bytes] | None = None,
        as_of: datetime | None = None,
    ) -> None:
        self.root = root.resolve()
        self.fetcher = fetcher or self._fetch
        self.parallel_fetch = fetcher is None
        resolved = as_of or datetime.now(timezone.utc).astimezone()
        if resolved.tzinfo is None:
            raise ValueError("as_of must include timezone")
        self.as_of = resolved
        self.calendar = TradingCalendar(load_json(self.root / "config/v2-market-calendar.json"), "CN")

    def collect(self) -> dict[str, Any]:
        index = load_json(self.root / "data/v2/v22/trigger-quote-index.json")
        existing = load_json(self.root / OUTPUT)
        snapshots = self._snapshots(index)
        by_key = {
            (str(item.get("trigger_snapshot_id")), str(item.get("code"))): item
            for item in as_list(existing.get("observations"))
            if isinstance(item, dict) and item.get("trigger_snapshot_id") and item.get("code")
        }
        codes = sorted({
            str(quote.get("code"))
            for snapshot in snapshots
            for quote in as_list(snapshot.get("representative_quotes"))
            if isinstance(quote, dict) and quote.get("code") and quote.get("market") == "CN"
        })
        bars_by_code: dict[str, dict[str, dict[str, float]]] = {}
        failures: list[dict[str, str]] = []
        fetch_errors: dict[str, str] = {}
        if self.parallel_fetch and len(codes) > 1:
            with ThreadPoolExecutor(max_workers=min(8, len(codes)), thread_name_prefix="v22-outcome") as pool:
                futures = {pool.submit(self._bars, code): code for code in codes}
                for future in as_completed(futures):
                    code = futures[future]
                    try:
                        bars_by_code[code] = future.result()
                    except Exception as exc:
                        fetch_errors[code] = f"{type(exc).__name__}:{str(exc)[:120]}"
        else:
            for code in codes:
                try:
                    bars_by_code[code] = self._bars(code)
                except Exception as exc:
                    fetch_errors[code] = f"{type(exc).__name__}:{str(exc)[:120]}"
        failures.extend({"code": code, "reason": fetch_errors[code]} for code in sorted(fetch_errors))

        conflicts: list[dict[str, Any]] = []
        for snapshot in snapshots:
            trigger_date = self._date(snapshot.get("trade_date"))
            if not trigger_date or self.calendar.is_open(trigger_date) is not True:
                failures.append({"code": str(snapshot.get("snapshot_id") or "unknown"), "reason": "trigger_trade_date_not_verified_open_day"})
                continue
            schedule = self._schedule(trigger_date)
            for quote in as_list(snapshot.get("representative_quotes")):
                if not isinstance(quote, dict) or quote.get("market") != "CN" or not quote.get("code"):
                    continue
                code = str(quote["code"])
                key = (str(snapshot.get("snapshot_id")), code)
                old = as_dict(by_key.get(key))
                reference_price = quote.get("trigger_price")
                reference_at = quote.get("quote_time")
                if not isinstance(reference_price, (int, float)) or reference_price <= 0 or not reference_at:
                    failures.append({"code": code, "reason": "immutable_trigger_reference_incomplete"})
                    continue
                windows = dict(as_dict(old.get("windows")))
                missing_windows: list[dict[str, Any]] = []
                bars = bars_by_code.get(code, {})
                for label, target in schedule.items():
                    if not self._is_due(target):
                        continue
                    bar = bars.get(target.isoformat())
                    if not bar:
                        missing_windows.append({
                            "window": label,
                            "target_date": target.isoformat(),
                            "status": "行情缺失或停牌，未按零涨跌处理",
                        })
                        continue
                    proposed = {
                        "price": bar["close"],
                        "high": bar.get("high"),
                        "low": bar.get("low"),
                        "quote_time": f"{target.isoformat()}T15:00:00+08:00",
                        "source": self._url(code),
                        "collected_at": now_iso(),
                        "quality_state": "historical_daily_bar",
                    }
                    stored = as_dict(windows.get(label))
                    if stored:
                        if stored.get("price") != proposed["price"] or stored.get("quote_time") != proposed["quote_time"]:
                            conflicts.append({
                                "trigger_snapshot_id": snapshot.get("snapshot_id"),
                                "code": code,
                                "window": label,
                                "resolution": "保留首次验证结果，不覆盖。",
                            })
                        continue
                    windows[label] = proposed
                by_key[key] = {
                    "trigger_snapshot_id": snapshot.get("snapshot_id"),
                    "case_id": snapshot.get("case_id"),
                    "state_hash": snapshot.get("state_hash"),
                    "kind": snapshot.get("kind"),
                    "code": code,
                    "name": quote.get("name"),
                    "reference_price": float(reference_price),
                    "reference_at": reference_at,
                    "reference_source_id": quote.get("source_id"),
                    "reference_source_label": quote.get("source_label"),
                    "reference_collected_at": quote.get("collected_at"),
                    "windows": windows,
                    "missing_windows": sorted(missing_windows, key=lambda item: str(item.get("window"))),
                }

        payload = {
            "schema_version": 1,
            "generated_at": now_iso(),
            "mode": "shadow_only",
            "collector": "sina_cn_daily_kline_for_v22_frozen_triggers",
            "calendar_version": self.calendar.version,
            "observations": sorted(by_key.values(), key=lambda item: (str(item.get("trigger_snapshot_id")), str(item.get("code")))),
            "failures": failures,
            "conflicts": conflicts,
            "guardrails": {
                "current_price_used_as_historical_trigger": False,
                "not_due_window_filled": False,
                "missing_price_treated_as_zero": False,
                "verified_result_overwritten": False,
                "automatic_trading": False,
                "user_assets_modified": False,
            },
        }
        state = "current"
        if self._stable(existing) != self._stable(payload):
            write_json(self.root / OUTPUT, payload)
            state = "updated"
        completed = sum(len(as_dict(item.get("windows"))) for item in payload["observations"])
        report = {
            "schema_version": 1,
            "generated_at": now_iso(),
            "mode": "shadow_only",
            "state": "degraded" if failures or conflicts else state,
            "trigger_snapshot_count": len(snapshots),
            "observation_count": len(payload["observations"]),
            "completed_window_count": completed,
            "failure_count": len(failures),
            "conflict_count": len(conflicts),
            "summary": "尚无可回填的触发行情快照。" if not snapshots else f"已形成{completed}个到期结果窗口。",
            "guardrails": payload["guardrails"],
        }
        write_json(self.root / REPORT_OUTPUT, report)
        return report

    def _snapshots(self, index: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for item in as_list(index.get("snapshots")):
            if not isinstance(item, dict) or not item.get("relative_path"):
                continue
            snapshot = load_json(self.root / str(item["relative_path"]))
            if snapshot and snapshot.get("immutable_hash") == item.get("immutable_hash"):
                rows.append(snapshot)
        return rows

    def _schedule(self, trigger_date: date) -> dict[str, date]:
        result = {"收盘": trigger_date}
        for window in (1, 3, 5, 10):
            target = self.calendar.advance(trigger_date, window)
            if target:
                result[f"T+{window}"] = target
        return result

    def _is_due(self, target: date) -> bool:
        if target < self.as_of.date():
            return True
        return target == self.as_of.date() and self.as_of.timetz().replace(tzinfo=None) >= time(15, 5)

    def _bars(self, code: str) -> dict[str, dict[str, float]]:
        payload = json.loads(self.fetcher(self._url(code)).decode("utf-8"))
        rows: dict[str, dict[str, float]] = {}
        for item in as_list(payload):
            if not isinstance(item, dict) or not item.get("day"):
                continue
            try:
                close = float(item.get("close") or 0)
                high = float(item.get("high") or close)
                low = float(item.get("low") or close)
            except (TypeError, ValueError):
                continue
            if close > 0 and high > 0 and low > 0:
                rows[str(item["day"])] = {"close": close, "high": high, "low": low}
        if not rows:
            raise ValueError("no_valid_daily_bars")
        return rows

    @staticmethod
    def _date(value: Any) -> date | None:
        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _stable(payload: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in payload.items() if key != "generated_at"}

    @staticmethod
    def _url(code: str) -> str:
        return f"{SINA_KLINE}?{urlencode({'symbol': code, 'scale': 240, 'ma': 'no', 'datalen': 320})}"

    @staticmethod
    def _fetch(url: str) -> bytes:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quotes.sina.cn/"})
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urlopen(request, timeout=12) as response:
                    return response.read()
            except (URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < 2:
                    time_module.sleep(0.25 * (attempt + 1))
        if last_error is not None:
            raise last_error
        raise RuntimeError("historical_quote_fetch_failed")

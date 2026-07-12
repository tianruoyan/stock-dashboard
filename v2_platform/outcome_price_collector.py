from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from v2_platform.learning import as_dict, as_list, load_json, write_json


SINA_KLINE = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"


class V2OutcomePriceCollector:
    """Backfill auditable close prices for frozen replay snapshots; never trades."""

    def __init__(self, root: Path, *, fetcher: Callable[[str], bytes] | None = None) -> None:
        self.root = root.resolve()
        self.data = self.root / "data" / "v2"
        self.fetcher = fetcher or self._fetch

    def collect(self) -> dict[str, Any]:
        existing = load_json(self.data / "outcome-prices.json")
        by_key = {
            (item.get("snapshot_id"), item.get("signal_id"), item.get("code")): item
            for item in as_list(existing.get("observations"))
            if isinstance(item, dict)
        }
        snapshots = self._snapshots()
        valid_keys = {
            (snap.get("snapshot_id"), sig.get("signal_id"), sec.get("code"))
            for snap in snapshots
            for sig in as_list(snap.get("signals")) if isinstance(sig, dict)
            for sec in as_list(sig.get("securities")) if isinstance(sec, dict) and sec.get("code")
        }
        by_key = {
            key: item for key, item in by_key.items()
            if key in valid_keys or not str(item.get("source") or "").startswith(SINA_KLINE)
        }
        codes = sorted({str(sec.get("code")) for snap in snapshots for sig in as_list(snap.get("signals")) for sec in as_list(sig.get("securities")) if isinstance(sec, dict) and sec.get("code")})
        bars_by_code: dict[str, dict[str, dict[str, Any]]] = {}
        failures: list[dict[str, str]] = []
        for code in codes:
            try:
                bars_by_code[code] = self._bars(code)
            except Exception as exc:
                failures.append({"code": code, "reason": f"{type(exc).__name__}:{str(exc)[:120]}"})

        for snapshot in snapshots:
            reference_date = self._reference_date(snapshot)
            for signal in as_list(snapshot.get("signals")):
                if not isinstance(signal, dict):
                    continue
                for security in as_list(signal.get("securities")):
                    if not isinstance(security, dict) or not security.get("code"):
                        continue
                    code = str(security["code"])
                    bars = bars_by_code.get(code, {})
                    ref_day = self._first_bar_on_or_after(bars, reference_date)
                    if not ref_day:
                        continue
                    key = (snapshot.get("snapshot_id"), signal.get("signal_id"), code)
                    old = as_dict(by_key.get(key))
                    # User/licensed observations win; the public collector only fills its own or absent rows.
                    if old and not str(old.get("source") or "").startswith(SINA_KLINE):
                        continue
                    windows = dict(as_dict(old.get("windows")))
                    for planned in as_list(signal.get("outcome_windows")):
                        if not isinstance(planned, dict) or not planned.get("window") or not planned.get("target_date"):
                            continue
                        bar = bars.get(str(planned["target_date"]))
                        if bar:
                            windows[str(planned["window"])] = {
                                "price": bar["close"],
                                "as_of": f"{planned['target_date']}T15:00:00+08:00",
                                "source": self._url(code),
                            }
                    by_key[key] = {
                        "snapshot_id": snapshot.get("snapshot_id"),
                        "signal_id": signal.get("signal_id"),
                        "code": code,
                        "reference_price": bars[ref_day]["close"],
                        "reference_at": f"{ref_day}T15:00:00+08:00",
                        "source": self._url(code),
                        "windows": windows,
                    }

        payload = {
            "schema_version": 1,
            "collector": "sina_cn_daily_kline_public_backfill",
            "observations": sorted(by_key.values(), key=lambda item: (str(item.get("snapshot_id")), str(item.get("signal_id")), str(item.get("code")))),
            "failures": failures,
            "guardrail": "仅回填冻结快照的公开收盘价；不生成交易、不修改判断、不自动晋级模型。",
        }
        if self._stable(existing) != self._stable(payload):
            write_json(self.data / "outcome-prices.json", payload)
            state = "updated"
        else:
            state = "current"
        due = sum(len(as_dict(item.get("windows"))) for item in payload["observations"])
        report = {"state": state if not failures else "degraded", "observation_count": len(payload["observations"]), "evaluated_window_input_count": due, "failure_count": len(failures)}
        self._update_public_health(report)
        return report

    def _update_public_health(self, report: dict[str, Any]) -> None:
        path = self.data / "public-input-health.json"
        health = load_json(path)
        if not health:
            return
        rows = [item for item in as_list(health.get("collectors")) if isinstance(item, dict) and item.get("id") != "outcome_prices"]
        rows.append(
            {
                "id": "outcome_prices",
                "state": "current" if report["state"] in {"current", "updated"} else "failed",
                "observation_count": report["observation_count"],
                "evaluated_window_input_count": report["evaluated_window_input_count"],
                "detail": "等待目标交易日收盘" if report["evaluated_window_input_count"] == 0 else "到期窗口已自动回填",
            }
        )
        health["collectors"] = rows
        if report["state"] == "degraded":
            health["state"] = "degraded"
        write_json(path, health)

    def _snapshots(self) -> list[dict[str, Any]]:
        index = load_json(self.data / "replay-index.json")
        rows = []
        for item in as_list(index.get("snapshots")):
            if isinstance(item, dict) and item.get("path"):
                snapshot = load_json(self.root / str(item["path"]))
                if snapshot:
                    rows.append(snapshot)
        return rows

    def _bars(self, code: str) -> dict[str, dict[str, Any]]:
        payload = json.loads(self.fetcher(self._url(code)).decode("utf-8"))
        rows = {}
        for item in as_list(payload):
            if not isinstance(item, dict) or not item.get("day"):
                continue
            close = float(item.get("close") or 0)
            if close > 0:
                rows[str(item["day"])] = {"close": close}
        if not rows:
            raise ValueError("no_valid_daily_bars")
        return rows

    @staticmethod
    def _reference_date(snapshot: dict[str, Any]) -> str:
        day = str(snapshot.get("decision_date") or "")
        raw = snapshot.get("decision_as_of")
        try:
            stamp = datetime.fromisoformat(str(raw))
            # A decision after the close must use the next available session, not that day's close.
            if stamp.timetz().replace(tzinfo=None) > time(15, 0):
                return (stamp.date()).isoformat() + "+1"
        except (TypeError, ValueError):
            pass
        return day

    @staticmethod
    def _first_bar_on_or_after(bars: dict[str, dict[str, Any]], target: str) -> str | None:
        after_close = target.endswith("+1")
        day = target.removesuffix("+1")
        candidates = sorted(value for value in bars if value > day or (not after_close and value >= day))
        return candidates[0] if candidates else None

    @staticmethod
    def _stable(payload: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in payload.items() if key not in {"updated_at", "generated_at"}}

    @staticmethod
    def _url(code: str) -> str:
        return f"{SINA_KLINE}?{urlencode({'symbol': code, 'scale': 240, 'ma': 'no', 'datalen': 260})}"

    @staticmethod
    def _fetch(url: str) -> bytes:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quotes.sina.cn/"})
        with urlopen(request, timeout=12) as response:
            return response.read()

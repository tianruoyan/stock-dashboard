from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


SOURCE_ID = "futu_opend_lv1"
SOURCE_LABEL = "富途 OpenD 行情"
A_SHARE_SOURCE_LABEL = "富途 OpenD A股LV1行情"
HK_SOURCE_LABEL = "富途 OpenD 港股LV2行情"


def to_futu_code(code: str) -> str | None:
    normalized = str(code or "").strip().lower().replace(".", "")
    if normalized.startswith("sh") and len(normalized) == 8:
        return f"SH.{normalized[2:]}"
    if normalized.startswith("sz") and len(normalized) == 8:
        return f"SZ.{normalized[2:]}"
    if normalized.startswith("hk") and len(normalized) == 7:
        return f"HK.{normalized[2:]}"
    return None


def from_futu_code(code: str) -> str | None:
    normalized = str(code or "").strip().upper()
    if normalized.startswith("SH.") and len(normalized) == 9:
        return f"sh{normalized[3:]}"
    if normalized.startswith("SZ.") and len(normalized) == 9:
        return f"sz{normalized[3:]}"
    if normalized.startswith("HK.") and len(normalized) == 8:
        return f"hk{normalized[3:]}"
    return None


class FutuQuoteProvider:
    """Read-only quote adapter for the local Futu OpenD gateway."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 11111,
        context_factory: Callable[..., Any] | None = None,
        batch_size: int = 400,
        clock: Callable[[], datetime] | None = None,
        max_future_seconds: int = 5,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.context_factory = context_factory
        self.batch_size = max(1, min(400, int(batch_size)))
        self.clock = clock or (lambda: datetime.now(timezone.utc).astimezone())
        self.max_future_seconds = max(0, int(max_future_seconds))

    def fetch_quotes(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        requested = {mapped: code for code in codes if (mapped := to_futu_code(code))}
        if not requested:
            return {}
        context_factory, ok_value = self._runtime()
        context = context_factory(host=self.host, port=self.port)
        quotes: dict[str, dict[str, Any]] = {}
        try:
            futu_codes = list(requested)
            for offset in range(0, len(futu_codes), self.batch_size):
                batch = futu_codes[offset : offset + self.batch_size]
                for data in self._snapshot_frames(context, batch, ok_value):
                    for _, row in data.iterrows():
                        normalized = from_futu_code(row.get("code"))
                        if not normalized:
                            continue
                        close = self._number(row.get("last_price"))
                        previous = self._number(row.get("prev_close_price"))
                        turnover = self._number(row.get("turnover"))
                        quote_time = self._quote_time(row.get("update_time"))
                        observed = self.clock()
                        if observed.tzinfo is None:
                            observed = observed.replace(tzinfo=timezone(timedelta(hours=8)))
                        if (
                            close is None
                            or previous is None
                            or close <= 0
                            or previous <= 0
                            or turnover is None
                            or turnover <= 0
                            or quote_time is None
                            or (quote_time - observed.astimezone(quote_time.tzinfo)).total_seconds() > self.max_future_seconds
                        ):
                            continue
                        source_label = HK_SOURCE_LABEL if normalized.startswith("hk") else A_SHARE_SOURCE_LABEL
                        quotes[normalized] = {
                            "name": str(row.get("name") or ""),
                            "code": normalized,
                            "close": close,
                            "previous_close": previous,
                            "volume": self._number(row.get("volume")) or 0.0,
                            "amount_yi": round(turnover / 100_000_000, 4) if turnover is not None else None,
                            "high": self._number(row.get("high_price")),
                            "low": self._number(row.get("low_price")),
                            "as_of": quote_time.isoformat(timespec="seconds"),
                            "security_status": str(row.get("sec_status") or ""),
                            "source_id": SOURCE_ID,
                            "source_label": source_label,
                        }
        finally:
            with suppress(Exception):
                context.close()
        return quotes

    def _snapshot_frames(self, context: Any, batch: list[str], ok_value: Any) -> list[Any]:
        """Keep a bad symbol from discarding valid quotes in the same request."""
        result, data = context.get_market_snapshot(batch)
        if result == ok_value:
            return [data]
        detail = str(data)
        symbol_error = any(
            marker in detail.lower()
            for marker in ("未知股票", "unknown stock", "format of code", "invalid code")
        )
        if not symbol_error:
            raise RuntimeError(f"futu_snapshot_failed:{detail[:180]}")
        if len(batch) == 1:
            return []
        middle = len(batch) // 2
        return self._snapshot_frames(context, batch[:middle], ok_value) + self._snapshot_frames(
            context,
            batch[middle:],
            ok_value,
        )

    def _runtime(self) -> tuple[Callable[..., Any], Any]:
        if self.context_factory is not None:
            return self.context_factory, 0
        try:
            from futu import OpenQuoteContext, RET_OK, SysConfig
        except ImportError as exc:
            raise RuntimeError("futu_api_not_installed") from exc
        with suppress(Exception):
            SysConfig.enable_console_log(False)
        return OpenQuoteContext, RET_OK

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number == number else None

    @staticmethod
    def _quote_time(value: Any) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return datetime.strptime(raw, pattern).replace(tzinfo=timezone(timedelta(hours=8)))
            except ValueError:
                continue
        return None

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from v2_platform.learning import as_list, load_json
from v2_platform.quote_consistency import compare_quotes, parse_quote_time
from v2_platform.sentiment_collector import fetch_tencent_quotes


CHINA_TZ = timezone(timedelta(hours=8))
SOURCE_ID = "tencent_http"
SOURCE_LABEL = "腾讯财经公开行情"
SECONDARY_SOURCE_ID = "futu_opend_lv1"
SECONDARY_SOURCE_LABEL = "富途 OpenD 行情"
DUAL_SOURCE_ID = "tencent_futu_cross_verified"
DUAL_SOURCE_LABEL = "腾讯与富途行情交叉核验"


def quote_time_iso(value: Any) -> str | None:
    for pattern in ("%Y%m%d%H%M%S", "%Y/%m/%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(str(value), pattern).replace(tzinfo=CHINA_TZ)
            return parsed.isoformat(timespec="seconds")
        except (TypeError, ValueError):
            continue
    return None


def canonical_representative_code(value: Any) -> str:
    """Normalize public quote codes and repair known cross-market prefix leakage."""
    normalized = str(value or "").strip().lower().replace(".", "")
    if len(normalized) == 6 and normalized.isdigit():
        if normalized.startswith(("5", "6")):
            return "sh" + normalized
        if normalized.startswith(("0", "1", "3")):
            return "sz" + normalized
        if normalized.startswith(("4", "8", "9")):
            return "bj" + normalized
        return ""
    if len(normalized) == 8 and normalized[:2] in {"sh", "sz", "bj"} and normalized[2:].isdigit():
        ticker = normalized[2:]
        if ticker.startswith("920"):
            return "bj" + ticker
        return normalized
    if len(normalized) == 7 and normalized.startswith("hk") and normalized[2:].isdigit():
        return normalized
    return ""


class V2RepresentativeQuoteCollector:
    def __init__(
        self,
        root: Path,
        *,
        quote_fetcher: Callable[[list[str]], dict[str, dict[str, Any]]] = fetch_tencent_quotes,
        secondary_quote_fetcher: Callable[[list[str]], dict[str, dict[str, Any]]] | None = None,
        consistency_policy: dict[str, Any] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.quote_fetcher = quote_fetcher
        self.secondary_quote_fetcher = secondary_quote_fetcher
        self.consistency_policy = consistency_policy or {}

    def collect(self) -> dict[str, Any]:
        names = self._representative_names()
        code_by_name = {
            str(item.get("name")): canonical_representative_code(item.get("code"))
            for item in as_list(load_json(self.root / "data" / "v2" / "stock-pool.json").get("stocks"))
            if isinstance(item, dict) and item.get("name") and canonical_representative_code(item.get("code"))
        }
        overrides = load_json(self.root / "config" / "v2-representative-stock-codes.json").get("codes")
        if isinstance(overrides, dict):
            code_by_name.update({
                str(name): normalized
                for name, code in overrides.items()
                if name and (normalized := canonical_representative_code(code))
            })
        styles = load_json(self.root / "config" / "v2-style-baskets.json").get("styles")
        if isinstance(styles, dict):
            for style in styles.values():
                if not isinstance(style, dict):
                    continue
                for member in as_list(style.get("members")):
                    if isinstance(member, dict) and member.get("name") and member.get("code"):
                        name = str(member["name"])
                        normalized = canonical_representative_code(member["code"])
                        if not normalized:
                            continue
                        code_by_name[name] = normalized
                        names.append(name)
        mainline = load_json(self.root / "data" / "v2" / "inputs" / "mainline-structure.json")
        for theme in as_list(mainline.get("themes")):
            if not isinstance(theme, dict):
                continue
            for security in as_list(theme.get("representative_securities")):
                if isinstance(security, dict) and security.get("name") and security.get("code"):
                    name = str(security["name"])
                    normalized = canonical_representative_code(security["code"])
                    if not normalized:
                        continue
                    code_by_name[name] = normalized
                    names.append(name)
        names = list(dict.fromkeys(names))
        requested = {name: code_by_name[name] for name in names if name in code_by_name}
        raw_quotes: dict[str, dict[str, Any]] = {}
        secondary_quotes: dict[str, dict[str, Any]] = {}
        source_errors: list[dict[str, str]] = []
        codes = list(dict.fromkeys(requested.values()))
        for offset in range(0, len(codes), 80):
            batch = codes[offset : offset + 80]
            fetchers = [(SOURCE_ID, self.quote_fetcher)]
            if self.secondary_quote_fetcher is not None:
                fetchers.append((SECONDARY_SOURCE_ID, self.secondary_quote_fetcher))
            with ThreadPoolExecutor(max_workers=len(fetchers)) as pool:
                futures = {source_id: pool.submit(fetcher, batch) for source_id, fetcher in fetchers}
                for source_id, future in futures.items():
                    try:
                        rows = future.result()
                    except Exception as exc:
                        source_errors.append({"source_id": source_id, "reason": f"{type(exc).__name__}:{str(exc)[:160]}"})
                        continue
                    if source_id == SOURCE_ID:
                        raw_quotes.update(rows)
                    else:
                        secondary_quotes.update(rows)

        quotes = []
        missing = []
        for name, code in requested.items():
            primary = raw_quotes.get(code or "")
            secondary = secondary_quotes.get(code or "")
            verification = compare_quotes(primary, secondary, self._consistency_policy_for(code))
            selected = primary if verification.get("selected_source") == "primary" else secondary
            if not isinstance(selected, dict):
                missing.append({"name": name, "code": code, "reason": "两路行情均缺失"})
                continue
            try:
                close = float(selected["close"])
                previous_close = float(selected["previous_close"])
            except (KeyError, TypeError, ValueError):
                missing.append({"name": name, "code": code, "reason": "行情字段不完整"})
                continue
            parsed_at = parse_quote_time(selected.get("as_of"))
            as_of = parsed_at.isoformat(timespec="seconds") if parsed_at else None
            if close <= 0 or previous_close <= 0 or not as_of:
                missing.append({"name": name, "code": code, "reason": "行情数值或时间不可用"})
                continue
            state = str(verification.get("state") or "unavailable")
            if state == "confirmed":
                source_id, source_label = DUAL_SOURCE_ID, DUAL_SOURCE_LABEL
            elif self.secondary_quote_fetcher is None:
                source_id, source_label = SOURCE_ID, SOURCE_LABEL
            elif verification.get("selected_source") == "secondary":
                source_id, source_label = SECONDARY_SOURCE_ID, "富途行情（主行情暂缺）"
            elif state in {"conflict", "date_mismatch", "time_unaligned"}:
                source_id, source_label = SOURCE_ID, "腾讯行情（与富途核验存在差异）"
            else:
                source_id, source_label = SOURCE_ID, "腾讯行情（等待富途核验）"
            quotes.append(
                {
                    "name": name,
                    "code": code,
                    "stock_change_pct": round((close / previous_close - 1) * 100, 4),
                    "stock_quote_as_of": as_of,
                    "stock_quote_source": source_label,
                    "stock_quote_source_id": source_id,
                    "stock_quote_verification": verification.get("user_state"),
                    "cross_source_verified": verification.get("cross_source_verified") is True,
                    "quote_verification": verification,
                    "close": close,
                    "previous_close": previous_close,
                    "turnover_yi": selected.get("amount_yi"),
                    "source_observations": {
                        "primary": self._observation(primary, SOURCE_ID, SOURCE_LABEL),
                        "secondary": self._observation(
                            secondary,
                            SECONDARY_SOURCE_ID,
                            str((secondary or {}).get("source_label") or SECONDARY_SOURCE_LABEL),
                        ),
                    },
                }
            )

        generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        confirmed_count = sum(item.get("cross_source_verified") is True for item in quotes)
        conflict_count = sum(
            (item.get("quote_verification") or {}).get("state") in {"conflict", "date_mismatch", "time_unaligned"}
            for item in quotes
        )
        return {
            "schema_version": 2,
            "generated_at": generated_at,
            "source_id": DUAL_SOURCE_ID if self.secondary_quote_fetcher is not None else SOURCE_ID,
            "source_label": DUAL_SOURCE_LABEL if self.secondary_quote_fetcher is not None else SOURCE_LABEL,
            "mode": "shadow_only" if self.secondary_quote_fetcher is not None else "single_source",
            "candidate_count": len(names),
            "requested_count": len(requested),
            "quote_count": len(quotes),
            "dual_source_confirmed_count": confirmed_count,
            "single_source_count": len(quotes) - confirmed_count - conflict_count,
            "conflict_count": conflict_count,
            "quotes": quotes,
            "missing": missing,
            "source_errors": source_errors,
            "guardrails": {
                "conflict_values_averaged": False,
                "single_source_called_cross_verified": False,
                "automatic_trading": False,
                "user_assets_modified": False,
            },
            "excluded_unmapped": [
                {"name": name, "reason": "未映射为证券，不作为代表股行情请求"}
                for name in names
                if name not in code_by_name
            ],
        }

    def _consistency_policy_for(self, code: str) -> dict[str, Any]:
        policy = dict(self.consistency_policy)
        close_times = policy.get("market_close_time_by_market")
        if isinstance(close_times, dict):
            market = "hk" if str(code).lower().startswith("hk") else "a_share"
            configured = close_times.get(market)
            if configured:
                policy["market_close_time"] = str(configured)
        return policy

    @staticmethod
    def _observation(quote: Any, source_id: str, source_label: str) -> dict[str, Any] | None:
        if not isinstance(quote, dict):
            return None
        parsed_at = parse_quote_time(quote.get("as_of"))
        return {
            "source_id": source_id,
            "source_label": source_label,
            "quote_time": parsed_at.isoformat(timespec="seconds") if parsed_at else str(quote.get("as_of") or ""),
            "close": quote.get("close"),
            "previous_close": quote.get("previous_close"),
            "turnover_yi": quote.get("amount_yi"),
        }

    def _representative_names(self) -> list[str]:
        names: list[str] = []
        formal = load_json(self.root / "config" / "v2-formal-observation.json")
        for item in as_list(formal.get("stocks")):
            if not isinstance(item, dict) or item.get("formal_observation_requested") is not True:
                continue
            if item.get("name"):
                names.append(str(item["name"]))
        alert = load_json(self.root / "data" / "alert.json")
        alert_rows = [
            *as_list(alert.get("alerts")),
            *as_list(alert.get("historical_alerts")),
        ]
        for item in alert_rows:
            if not isinstance(item, dict):
                continue
            for stock in as_list(item.get("leaders")):
                if isinstance(stock, dict) and stock.get("name"):
                    names.append(str(stock["name"]))
        watch = load_json(self.root / "data" / "opportunity-watch.json")
        for item in as_list(watch.get("items")):
            if not isinstance(item, dict):
                continue
            names.extend(str(name) for name in as_list(item.get("watch_stocks")) if name)
        mainline = load_json(self.root / "data" / "v2" / "inputs" / "mainline-structure.json")
        for theme in as_list(mainline.get("themes")):
            if not isinstance(theme, dict):
                continue
            for security in as_list(theme.get("representative_securities")):
                if isinstance(security, dict) and security.get("name"):
                    names.append(str(security["name"]))
        return list(dict.fromkeys(names))

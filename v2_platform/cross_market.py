from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from v2_platform.environment_evidence import trade_date_of


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def direction_from_text(value: Any) -> str:
    raw = str(value or "").lower()
    positive = ("上涨", "走强", "反弹", "positive", "up ", "rise")
    negative = ("下跌", "走弱", "回落", "negative", "down ", "fall")
    if any(token in raw for token in positive) and not any(token in raw for token in negative):
        return "up"
    if any(token in raw for token in negative) and not any(token in raw for token in positive):
        return "down"
    return "unknown"


class V22CrossMarketBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.config = load_json(self.root / "config/v2-cross-market-mappings.json")
        external = load_json(self.root / "data/v2/inputs/external-market.json")
        governed_rows = [item for item in as_list(external.get("markets")) if isinstance(item, dict)]
        decision = load_json(self.root / "data/v2/decision-system.json")
        environment = decision.get("market_environment") if isinstance(decision.get("market_environment"), dict) else {}
        legacy_rows = [item for item in as_list(environment.get("cross_market")) if isinstance(item, dict)]
        self.origin_rows = governed_rows or legacy_rows
        quotes = load_json(self.root / "data/v2/inputs/representative-stock-quotes.json")
        self.quotes = {str(item.get("code") or "").lower(): item for item in as_list(quotes.get("quotes")) if isinstance(item, dict)}

    def build(self, environment: dict[str, Any]) -> list[dict[str, Any]]:
        trade_date = str(environment.get("trade_date") or "")
        rows = []
        for mapping in as_list(self.config.get("mappings")):
            if isinstance(mapping, dict):
                rows.append(self._mapping(mapping, trade_date))
        return rows

    def _mapping(self, mapping: dict[str, Any], trade_date: str) -> dict[str, Any]:
        market = str(mapping.get("origin_market") or "")
        keywords = [str(value).lower() for value in as_list(mapping.get("origin_keywords"))]
        candidates = [item for item in self.origin_rows if str(item.get("market") or "") == market]
        matched = []
        for item in candidates:
            raw = json.dumps(item, ensure_ascii=False).lower()
            if any(keyword in raw for keyword in keywords):
                matched.append(item)
        current = [
            item for item in matched
            if str(item.get("a_share_trade_date") or trade_date_of(item.get("as_of")) or "") == trade_date
            and item.get("mapping_eligible") is not False
        ]
        reps = []
        for security in as_list(mapping.get("representative_securities")):
            if not isinstance(security, dict):
                continue
            quote = self.quotes.get(str(security.get("code") or "").lower())
            if not quote or trade_date_of(quote.get("stock_quote_as_of")) != trade_date or number(quote.get("stock_change_pct")) is None:
                continue
            reps.append({"code": security.get("code"), "name": security.get("name"), "change_pct": number(quote.get("stock_change_pct")), "as_of": quote.get("stock_quote_as_of"), "source": quote.get("stock_quote_source")})
        explicit_directions = {str(item.get("direction")) for item in current if item.get("direction") in {"up", "down"}}
        origin_text = "；".join(str(item.get("conclusion") or "") for item in current)
        origin_direction = next(iter(explicit_directions)) if len(explicit_directions) == 1 else direction_from_text(origin_text)
        a_share_direction = "unknown"
        if len(reps) >= 2:
            average = sum(float(item["change_pct"]) for item in reps) / len(reps)
            a_share_direction = "up" if average > 0.5 else ("down" if average < -0.5 else "flat")
        counter = list(mapping.get("invalidation_conditions"))
        if not current:
            state = "background_only"
            conclusion = "海外触发缺少当前交易日、当前时点的可核验来源，只保留为背景。"
            counter.append("未取得当前交易日海外事实。")
        elif origin_direction == "unknown":
            state = "pending"
            conclusion = "海外方向尚不清晰，等待A股代表股和来源共同确认。"
        elif a_share_direction == "unknown":
            state = "pending"
            conclusion = "海外触发已观察，但A股代表股行情不足，不能确认传导。"
        elif (origin_direction == "up" and a_share_direction == "up") or (origin_direction == "down" and a_share_direction == "down"):
            state = "confirmed"
            conclusion = "海外方向与A股代表股同向，传导得到阶段性确认。"
        else:
            state = "divergent"
            conclusion = "海外方向与A股代表股背离，不支持机械映射。"
            counter.append("A股代表股未同向兑现。")
        return {
            "mapping_id": mapping.get("mapping_id"),
            "mapping_version": self.config.get("version"),
            "origin_market": market,
            "origin_objects": as_list(mapping.get("origin_objects")),
            "origin_as_of": current[0].get("as_of") if current else None,
            "origin_direction": origin_direction,
            "origin_source_state": "current" if current else "missing_or_stale",
            "transmission_type": mapping.get("transmission_type"),
            "a_share_themes": as_list(mapping.get("a_share_themes")),
            "representative_securities": reps,
            "a_share_direction": a_share_direction,
            "transmission_state": state,
            "conclusion": conclusion,
            "counter_evidence": counter,
            "valid_window": as_list(self.config.get("default_valid_windows")),
            "valid_until": f"{trade_date}T15:00:00+08:00" if trade_date else None,
            "supports_g5_upgrade": state == "confirmed",
            "single_company_event_theme_upgrade": False,
            "user_assets_modified": False,
        }

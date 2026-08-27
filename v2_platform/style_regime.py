from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any

from v2_platform.environment_evidence import newest_time, trade_date_of


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


class V22StyleRegimeBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.config = load_json(self.root / "config/v2-style-baskets.json")
        self.taxonomy = load_json(self.root / "config/v2-style-taxonomy.json")
        quotes = load_json(self.root / "data/v2/inputs/representative-stock-quotes.json")
        self.quotes = {
            str(item.get("code") or "").lower(): item
            for item in as_list(quotes.get("quotes"))
            if isinstance(item, dict) and item.get("code")
        }
        self.market_structure = load_json(self.root / "data/v2/market-structure.json")

    def build(self, environment: dict[str, Any]) -> list[dict[str, Any]]:
        trade_date = str(environment.get("trade_date") or "")
        sentiment = next((item for item in as_list(environment.get("dimensions")) if isinstance(item, dict) and item.get("dimension_code") == "sentiment_structure"), {})
        result = []
        styles = self.config.get("styles") if isinstance(self.config.get("styles"), dict) else {}
        for style_id in ("old_deng", "middle_deng", "small_deng"):
            style = styles.get(style_id) if isinstance(styles.get(style_id), dict) else {}
            result.append(self._basket(style_id, style, trade_date, sentiment))
        result.append(self._microcap(styles.get("microcap") if isinstance(styles.get("microcap"), dict) else {}, trade_date, sentiment))
        return result

    def _basket(self, style_id: str, style: dict[str, Any], trade_date: str, sentiment: dict[str, Any]) -> dict[str, Any]:
        members = [item for item in as_list(style.get("members")) if isinstance(item, dict)]
        observed = []
        for member in members:
            quote = self.quotes.get(str(member.get("code") or "").lower())
            if not quote or trade_date_of(quote.get("stock_quote_as_of")) != trade_date or number(quote.get("stock_change_pct")) is None:
                continue
            observed.append({
                "code": member.get("code"),
                "name": member.get("name"),
                "group": member.get("group"),
                "change_pct": number(quote.get("stock_change_pct")),
                "as_of": quote.get("stock_quote_as_of"),
                "source": quote.get("stock_quote_source"),
                "turnover_yi": number(quote.get("turnover_yi")),
            })
        coverage = len(observed) / len(members) if members else 0.0
        threshold = float(self.config.get("minimum_coverage_ratio") or 0.6)
        changes = [float(item["change_pct"]) for item in observed]
        positive_ratio = sum(value > 0 for value in changes) / len(changes) if changes else 0.0
        negative_ratio = sum(value < 0 for value in changes) / len(changes) if changes else 0.0
        med = median(changes) if changes else None
        turnover_values = [float(item["turnover_yi"]) for item in observed if item.get("turnover_yi") is not None]
        turnover_coverage = len(turnover_values) / len(members) if members else 0.0
        if coverage < threshold:
            price_state = "unknown"
            breadth_state = "unknown"
            conclusion = f"{style.get('label') or style_id}代表股只有{len(observed)}/{len(members)}只有当天行情，暂时不能判断这个风格整体强弱。"
            quality = "unknown"
        else:
            if med is not None and med >= 1 and positive_ratio >= 0.6:
                price_state, breadth_state = "strengthening", "expanding"
            elif med is not None and med <= -1 and negative_ratio >= 0.6:
                price_state, breadth_state = "weakening", "narrowing"
            else:
                price_state, breadth_state = "mixed", "split"
            turnover_ready = turnover_coverage >= threshold
            if price_state == "strengthening":
                conclusion = (
                    f"{style.get('label') or style_id}代表股多数上涨，方向正在走强；但缺少过去正常成交水平作比较，暂时不能确认资金是否明显回流。"
                    if turnover_ready else f"{style.get('label') or style_id}代表股多数上涨，但成交额数据不完整，暂时不能确认资金是否真正回流。"
                )
            elif price_state == "weakening":
                conclusion = (
                    f"{style.get('label') or style_id}代表股多数下跌，方向正在承压；但缺少过去正常成交水平作比较，暂时不能判断抛压是否明显增加。"
                    if turnover_ready else f"{style.get('label') or style_id}代表股多数下跌，但成交额数据不完整，暂时不能判断抛压有多重。"
                )
            else:
                conclusion = f"{style.get('label') or style_id}代表股涨跌不一，暂时看不出资金的一致选择，先观察。"
            quality = "usable" if turnover_coverage >= threshold else "degraded"
        representative = sorted(observed, key=lambda item: abs(float(item["change_pct"])), reverse=True)[:6]
        counter = []
        if observed:
            best = max(observed, key=lambda item: float(item["change_pct"]))
            worst = min(observed, key=lambda item: float(item["change_pct"]))
            counter.append(f"最强样本{best['name']}{best['change_pct']:+.2f}%，最弱样本{worst['name']}{worst['change_pct']:+.2f}%，需防止单股代表整体。")
        if turnover_coverage < threshold:
            counter.append("代表股成交额数据不完整，暂时无法判断资金参与强弱。")
        return {
            "style_id": style_id,
            "label": style.get("label") or style_id,
            "definition_version": self.config.get("definition_version"),
            "basket_version": self.config.get("version"),
            "basket_status": style.get("status"),
            "construction": style.get("construction"),
            "member_count": len(members),
            "observed_count": len(observed),
            "coverage_ratio": round(coverage, 4),
            "price_state": price_state,
            "turnover_state": "observed" if turnover_coverage >= threshold else "unknown",
            "turnover_coverage_ratio": round(turnover_coverage, 4),
            "turnover_total_yi": round(sum(turnover_values), 4) if turnover_values else None,
            "breadth_state": breadth_state,
            "leader_confirmation": "unconfirmed" if len(representative) < 2 else ("weakening" if price_state == "weakening" else "partial"),
            "sentiment_state": "risk" if sentiment.get("support_level") in {"suppress", "risk_release"} else "unknown",
            "median_change_pct": round(med, 4) if med is not None else None,
            "positive_ratio": round(positive_ratio, 4) if observed else None,
            "negative_ratio": round(negative_ratio, 4) if observed else None,
            "representative_securities": representative,
            "counter_evidence": counter,
            "conclusion": conclusion,
            "quality_state": quality,
            "as_of": newest_time([item.get("as_of") for item in observed]),
            "user_assets_modified": False,
        }

    def _microcap(self, style: dict[str, Any], trade_date: str, sentiment: dict[str, Any]) -> dict[str, Any]:
        selected = self.market_structure.get("selected_observation") if isinstance(self.market_structure.get("selected_observation"), dict) else {}
        usable = trade_date_of(selected.get("as_of")) == trade_date and number(selected.get("change_pct")) is not None
        value = number(selected.get("change_pct")) if usable else None
        price_state = "weakening" if value is not None and value < 0 else ("strengthening" if value is not None and value > 0 else "unknown")
        conclusion = (
            f"中证2000小微盘宽基代理{value:+.2f}%；不等于纯微盘，也不从小登推断。"
            if value is not None else "纯微盘数据缺失；中证2000代理也未形成同日可用行情。"
        )
        representative = []
        if usable:
            representative.append({
                "code": "932000",
                "name": selected.get("name") or "中证2000指数",
                "change_pct": value,
                "as_of": selected.get("as_of"),
                "source": selected.get("source_name") or "新浪财经中证2000公开行情",
                "source_url": selected.get("source_url"),
                "role": "小微盘宽基代理",
            })
        return {
            "style_id": "microcap",
            "label": style.get("label") or "微盘",
            "definition_version": self.config.get("definition_version"),
            "basket_version": self.config.get("version"),
            "basket_status": style.get("status"),
            "construction": style.get("construction"),
            "member_count": 0,
            "observed_count": 1 if usable else 0,
            "coverage_ratio": None,
            "price_state": price_state,
            "turnover_state": "unknown",
            "breadth_state": "proxy_only" if usable else "unknown",
            "leader_confirmation": "not_applicable",
            "sentiment_state": "risk" if sentiment.get("support_level") in {"suppress", "risk_release"} else "unknown",
            "median_change_pct": value,
            "positive_ratio": None,
            "negative_ratio": None,
            "representative_securities": representative,
            "counter_evidence": ["中证2000是小微盘宽基代理，不代表纯微盘，也不代表小登题材。", "纯微盘正式数据仍缺失。"],
            "conclusion": conclusion,
            "quality_state": "degraded" if usable else "unknown",
            "as_of": selected.get("as_of") if usable else None,
            "user_assets_modified": False,
        }

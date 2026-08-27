from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PUBLIC_OUTPUT = "data/v2/v22/industry-tracking.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def stable_id(name: str) -> str:
    return "industry_" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]


def parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


class V22IndustryTrackingBuilder:
    def __init__(self, root: Path, now: datetime | None = None) -> None:
        self.root = root.resolve()
        self.now = (now or datetime.now(timezone.utc).astimezone()).astimezone()

    def build(self) -> dict[str, Any]:
        formal = load_json(self.root / "config/v2-formal-observation.json")
        quotes = load_json(self.root / "data/v2/inputs/representative-stock-quotes.json")
        topics = load_json(self.root / "data/topics.json")
        environment = load_json(self.root / "data/v2/v22/market-environment.json")
        quote_by_code = {
            str(item.get("code") or "").lower(): item
            for item in as_list(quotes.get("quotes"))
            if isinstance(item, dict) and item.get("code")
        }
        stock_by_name = {
            str(item.get("name") or ""): item
            for item in as_list(formal.get("stocks"))
            if isinstance(item, dict) and item.get("name")
        }
        topic_by_name = {
            str(item.get("name") or ""): item
            for item in as_list(topics.get("topics"))
            if isinstance(item, dict) and item.get("name")
        }
        rows = []
        for theme in as_list(formal.get("themes")):
            if not isinstance(theme, dict) or not theme.get("name"):
                continue
            names = [str(value) for value in as_list(theme.get("stocks")) if value]
            representatives = []
            source_refs: list[dict[str, Any]] = []
            chain_sides: set[str] = set()
            for name in names:
                stock = stock_by_name.get(name) or {}
                code = str(stock.get("code") or "").lower()
                quote = quote_by_code.get(code) or {}
                quote_at = parse_time(quote.get("stock_quote_as_of"))
                quote_current = bool(quote_at and quote_at.date() == self.now.date())
                representatives.append(
                    {
                        "name": name,
                        "code": code,
                        "benefit_tier": stock.get("benefit_tier"),
                        "evidence_grade": stock.get("evidence_grade"),
                        "change_pct": quote.get("stock_change_pct"),
                        "quote_as_of": quote.get("stock_quote_as_of"),
                        "quote_source": quote.get("stock_quote_source"),
                        "quote_state": "当前交易日已核验" if quote_current else "等待当前交易日行情",
                        "counter_evidence": as_list(stock.get("counter_evidence")),
                        "trigger_conditions": as_list(stock.get("trigger_conditions")),
                        "invalidation_conditions": as_list(stock.get("invalidation_conditions")),
                    }
                )
                if stock.get("chain_side"):
                    chain_sides.add(str(stock["chain_side"]))
                source_refs.extend(dict(value) for value in as_list(stock.get("source_refs")) if isinstance(value, dict))
            linked_topics = []
            for topic_name in as_list(theme.get("related_runtime_topics")):
                current = topic_by_name.get(str(topic_name))
                if not current:
                    linked_topics.append({"name": str(topic_name), "state": "等待专题更新"})
                    continue
                linked_topics.append(
                    {
                        "name": str(topic_name),
                        "state": current.get("status") or "待更新",
                        "conclusion": current.get("conclusion") or current.get("note") or "",
                        "action": current.get("action") or "",
                        "updated_at": current.get("updated_at") or topics.get("timestamp"),
                    }
                )
            judgement_at = parse_time(theme.get("current_updated_at"))
            judgement_current = bool(judgement_at and (self.now - judgement_at.astimezone(self.now.tzinfo)).total_seconds() <= 7 * 86400)
            deduped_refs = []
            seen_urls: set[str] = set()
            for ref in source_refs:
                url = str(ref.get("url") or "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                deduped_refs.append(ref)
            rows.append(
                {
                    "industry_id": stable_id(str(theme["name"])),
                    "name": str(theme["name"]),
                    "chain_sides": sorted(chain_sides),
                    "classification": theme.get("current_status") or "证据不足",
                    "classification_as_of": theme.get("current_updated_at"),
                    "classification_state": "当前有效" if judgement_current else "等待重新验证",
                    "conclusion": theme.get("current_conclusion") or "等待研究结论。",
                    "action": theme.get("current_action") or "持续观察。",
                    "frequency": theme.get("frequency") or "盘后复核",
                    "focus": as_list(theme.get("focus")),
                    "missing_evidence": as_list(theme.get("missing_evidence")),
                    "failure_trigger": theme.get("failure_trigger") or "缺少明确失效条件。",
                    "representative_stocks": representatives,
                    "linked_market_topics": linked_topics,
                    "source_refs": deduped_refs,
                    "market_environment": {
                        "trade_date": environment.get("trade_date"),
                        "as_of": environment.get("as_of"),
                        "headline": environment.get("headline") or environment.get("current_judgement"),
                        "quality_state": environment.get("quality_state") or environment.get("overall_quality"),
                    },
                    "automatic_upgrade": False,
                    "is_user_asset": False,
                    "trading_enabled": False,
                }
            )
        return {
            "schema_version": 1,
            "generated_at": self.now.isoformat(timespec="seconds"),
            "mode": "shadow_only",
            "headline": "正式观察专题已进入行业持续跟踪；分类只随正式证据复核，不因单日涨幅自动升级。",
            "tracking_count": len(rows),
            "items": rows,
            "guardrails": {
                "user_assets_modified": False,
                "v1_modified": False,
                "automatic_trading": False,
                "automatic_classification_upgrade": False,
                "missing_evidence_ai_filled": False,
            },
        }

    def write(self) -> dict[str, Any]:
        payload = self.build()
        output = self.root / PUBLIC_OUTPUT
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = output.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        json.loads(tmp.read_text(encoding="utf-8"))
        tmp.replace(output)
        return payload

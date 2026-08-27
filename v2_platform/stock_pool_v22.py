from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from v2_platform.watchlist_sync import normalize_code


PUBLIC_OUTPUT = "data/v2/v22/stock-pool-shadow.json"
RESEARCH_REQUIREMENTS = (
    ("identity", "证券身份"),
    ("theme_or_domain", "主题或产业位置"),
    ("role", "角色或未分类依据"),
    ("attention_reason", "关注原因"),
    ("counter_evidence", "反向证据"),
    ("catalyst_or_reason", "催化或持续观察理由"),
    ("trigger", "触发条件"),
    ("invalidation", "失效条件"),
    ("environment", "适用与不适用市场环境"),
)


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


def parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


def quote_map(decision: dict[str, Any], representative_quotes: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    cards = [
        *as_list(decision.get("opportunity_radar")),
        *as_list(decision.get("opportunity_history")),
        *as_list(decision.get("validation_queue")),
    ]
    for card in cards:
        if not isinstance(card, dict):
            continue
        for item in as_list(card.get("representative_stocks")):
            if not isinstance(item, dict):
                continue
            code = normalize_code(item.get("stock_code"))
            if not code or item.get("stock_change_pct") is None:
                continue
            candidate = {
                "name": str(item.get("name") or ""),
                "change_pct": item.get("stock_change_pct"),
                "as_of": item.get("stock_quote_as_of"),
                "source": item.get("stock_quote_source"),
            }
            existing = result.get(code)
            if existing is None:
                result[code] = candidate
                continue
            current_time = parse_time(candidate.get("as_of"))
            existing_time = parse_time(existing.get("as_of"))
            if current_time and (not existing_time or current_time > existing_time):
                result[code] = candidate
    for item in as_list((representative_quotes or {}).get("quotes")):
        if not isinstance(item, dict):
            continue
        code = normalize_code(item.get("code"))
        if not code or item.get("stock_change_pct") is None:
            continue
        candidate = {
            "name": str(item.get("name") or ""),
            "change_pct": item.get("stock_change_pct"),
            "as_of": item.get("stock_quote_as_of"),
            "source": item.get("stock_quote_source"),
        }
        existing = result.get(code)
        current_time = parse_time(candidate.get("as_of"))
        existing_time = parse_time((existing or {}).get("as_of"))
        if existing is None or (current_time and (not existing_time or current_time > existing_time)):
            result[code] = candidate
    return result


def quote_view(code: str, quotes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    quote = quotes.get(code) or {}
    if quote.get("change_pct") is None or not quote.get("as_of") or not quote.get("source"):
        return {
            "state": "行情待核验",
            "change_pct": None,
            "as_of": None,
            "source": None,
        }
    return {
        "state": "真实行情已核验",
        "change_pct": quote.get("change_pct"),
        "as_of": quote.get("as_of"),
        "source": quote.get("source"),
    }


def research_assessment(item: dict[str, Any]) -> dict[str, Any]:
    code = normalize_code(item.get("code"))
    domains = [entry for entry in as_list(item.get("domains")) if isinstance(entry, dict)]
    themes = [entry for entry in as_list(item.get("themes")) if isinstance(entry, dict)]
    roles = [str(value) for value in as_list(item.get("roles"))]
    role_evidence = [str(value) for value in as_list(item.get("role_evidence")) if str(value).strip()]
    counter_evidence = [str(value) for value in as_list(item.get("counter_evidence")) if str(value).strip()]
    invalidations = [str(value) for value in as_list(item.get("invalidation_conditions")) if str(value).strip()]
    catalysts = [str(value) for value in as_list(item.get("catalysts")) if str(value).strip()]
    suitable = [str(value) for value in as_list(item.get("suitable_environment")) if str(value).strip()]
    unsuitable = [str(value) for value in as_list(item.get("unsuitable_environment")) if str(value).strip()]
    evidence = {
        "identity": bool(code) and (item.get("identity_verified") is True or bool(str(item.get("identity_source") or "").strip())),
        "theme_or_domain": bool(themes) or any(str(domain.get("id") or "") not in {"", "other"} for domain in domains),
        "role": bool(roles and role_evidence),
        "attention_reason": bool(str(item.get("attention_reason") or "").strip()),
        "counter_evidence": bool(counter_evidence or invalidations),
        "catalyst_or_reason": bool(catalysts or str(item.get("attention_reason") or "").strip()),
        "trigger": bool(as_list(item.get("trigger_conditions"))),
        "invalidation": bool(invalidations),
        "environment": bool(suitable and unsuitable),
    }
    missing = [label for key, label in RESEARCH_REQUIREMENTS if not evidence[key]]
    return {
        "eligible": not missing,
        "state": "正式观察条件已满足" if not missing else "研究要素待补",
        "missing": missing,
        "evidence": evidence,
    }


def style_relations(code: str, watchlist: dict[str, Any]) -> list[str]:
    labels = {
        "old_deng": "老登样本",
        "middle_deng": "中登样本",
        "small_deng": "小登样本",
        "microcap": "微盘样本",
    }
    relations = []
    for pool, label in labels.items():
        raw = watchlist.get(pool)
        rows = as_list(raw.get("stocks")) if isinstance(raw, dict) else []
        if any(normalize_code(item.get("code")) == code for item in rows if isinstance(item, dict)):
            relations.append(label)
    return relations


def priority_value(value: Any) -> int:
    return {"high": 0, "normal": 1, "low": 2}.get(str(value), 1)


def intent_value(value: Any, context: str) -> int:
    intent = str(value or "")
    if context == "risk":
        return {"holding": 0, "swing": 1, "watch": 2, "event": 3, "research": 4}.get(intent, 3)
    return {"watch": 0, "swing": 1, "event": 2, "holding": 3, "research": 4}.get(intent, 3)


def prioritize_cockpit_assets(
    user_assets: Iterable[dict[str, Any]],
    formal_observation: Iterable[dict[str, Any]],
    temporary_candidates: Iterable[dict[str, Any]],
    *,
    context: str = "opportunity",
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    users = sorted(
        (dict(item) for item in user_assets),
        key=lambda item: (priority_value(item.get("user_priority")), intent_value(item.get("user_intent"), context), str(item.get("code") or "")),
    )
    for layer, rows in (
        ("用户自选", users),
        ("正式观察", [dict(item) for item in formal_observation]),
        ("系统发现", [dict(item) for item in temporary_candidates]),
    ):
        for item in rows:
            code = normalize_code(item.get("code"))
            if not code or code in seen:
                continue
            seen.add(code)
            result.append({**item, "code": code, "display_layer": layer})
    return result


class V22StockPoolBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def build(self) -> dict[str, Any]:
        stock_pool = load_json(self.root / "data/v2/stock-pool.json")
        decision = load_json(self.root / "data/v2/decision-system.json")
        watchlist = load_json(self.root / "config/watchlist.json")
        migration = load_json(self.root / "data/v2/v22/watchlist-migration-audit.json")
        representative_quotes = load_json(self.root / "data/v2/inputs/representative-stock-quotes.json")
        quotes = quote_map(decision, representative_quotes)
        pool_codes = {
            normalize_code(item.get("code"))
            for item in as_list(stock_pool.get("stocks"))
            if isinstance(item, dict) and normalize_code(item.get("code"))
        }
        formal_candidates = []
        formal_observation = []
        for item in as_list(stock_pool.get("stocks")):
            if not isinstance(item, dict):
                continue
            code = normalize_code(item.get("code"))
            quote_identity = quotes.get(code) or {}
            identity_verified = bool(
                code
                and quote_identity.get("source")
                and str(quote_identity.get("name") or "").strip() == str(item.get("name") or "").strip()
            )
            assessment = research_assessment({**item, "identity_verified": identity_verified})
            formal_requested = item.get("formal_observation_requested") is True
            trading_candidate_opt_in = item.get("trading_candidate_opt_in") is True if formal_requested else True
            row = {
                "code": code or str(item.get("code") or ""),
                "name": str(item.get("name") or ""),
                "themes": [str(entry.get("name") or "") for entry in as_list(item.get("themes")) if isinstance(entry, dict) and entry.get("name")],
                "domains": [str(entry.get("name") or "") for entry in as_list(item.get("domains")) if isinstance(entry, dict) and entry.get("name")],
                "roles": [str(value) for value in as_list(item.get("roles"))],
                "role_evidence": [str(value) for value in as_list(item.get("role_evidence"))],
                "attention_reason": str(item.get("attention_reason") or ""),
                "counter_evidence": [str(value) for value in as_list(item.get("counter_evidence"))],
                "catalysts": [str(value) for value in as_list(item.get("catalysts"))],
                "trigger_conditions": [str(value) for value in as_list(item.get("trigger_conditions"))],
                "invalidation_conditions": [str(value) for value in as_list(item.get("invalidation_conditions"))],
                "suitable_environment": [str(value) for value in as_list(item.get("suitable_environment"))],
                "unsuitable_environment": [str(value) for value in as_list(item.get("unsuitable_environment"))],
                "source_refs": [dict(value) for value in as_list(item.get("source_refs")) if isinstance(value, dict)],
                "chain_side": str(item.get("chain_side") or ""),
                "benefit_tier": str(item.get("benefit_tier") or ""),
                "evidence_grade": str(item.get("evidence_grade") or ""),
                "research_classification": str(item.get("research_classification") or ""),
                "observation_source": str(item.get("observation_source") or "research_system"),
                "formal_observation_requested": formal_requested,
                "trading_candidate_opt_in": trading_candidate_opt_in,
                "style_relations": style_relations(code, watchlist) if code else [],
                "research_state": assessment["state"],
                "missing_requirements": assessment["missing"],
                "quote": quote_view(code, quotes) if code else quote_view("", quotes),
                "ai_view": "等待研究要素补全" if not assessment["eligible"] else (str(item.get("research_classification") or "可进入正式观察")),
                "is_user_asset": False,
            }
            if assessment["eligible"]:
                formal_observation.append(row)
            else:
                formal_candidates.append(row)
        formal_candidates.sort(key=lambda item: (len(item["missing_requirements"]), item["code"]))
        formal_observation.sort(key=lambda item: item["code"])
        formal_codes = {item["code"] for item in formal_observation}
        trading_opt_in_codes = {
            item["code"] for item in formal_observation if item.get("trading_candidate_opt_in") is True
        }
        temporary_map: dict[str, dict[str, Any]] = {}
        for card in as_list(decision.get("validation_queue")):
            if not isinstance(card, dict):
                continue
            for stock in as_list(card.get("representative_stocks")):
                if not isinstance(stock, dict):
                    continue
                code = normalize_code(stock.get("stock_code"))
                if not code or code in pool_codes:
                    continue
                temporary_map.setdefault(code, {
                    "code": code,
                    "name": str(stock.get("name") or ""),
                    "discovery_context": str(card.get("theme") or card.get("title") or "系统线索"),
                    "ai_view": "系统发现，尚未加入我的关注",
                    "risk": "代表股和交易条件尚未全部确认",
                    "quote": quote_view(code, quotes),
                    "is_user_asset": False,
                    "formal_observation": False,
                    "applied": False,
                })
        temporary_candidates = sorted(temporary_map.values(), key=lambda item: item["code"])
        trading_map: dict[str, dict[str, Any]] = {}
        for card in as_list(decision.get("opportunity_radar")):
            if not isinstance(card, dict):
                continue
            for stock in as_list(card.get("representative_stocks")):
                if not isinstance(stock, dict):
                    continue
                code = normalize_code(stock.get("stock_code"))
                if code not in formal_codes or code not in trading_opt_in_codes:
                    continue
                trading_map[code] = {
                    "code": code,
                    "name": str(stock.get("name") or ""),
                    "decision": str(card.get("action") or "等待确认"),
                    "case_title": str(card.get("title") or "交易候选"),
                    "quote": quote_view(code, quotes),
                    "formal_observation_required": True,
                }
        migration_counts = migration.get("counts") if isinstance(migration.get("counts"), dict) else {}
        return {
            "schema_version": 1,
            "generated_at": now_iso(),
            "stage": "E3股票池分层影子投影",
            "mode": "shadow_only",
            "headline": "用户资产、正式观察、交易候选、风格样本和系统发现已分层；不自动改变用户关注。",
            "user_asset_layer": {
                "public_records": [],
                "local_read_endpoint": "/_v2-user-assets",
                "public_user_fields_included": False,
                "migration_applied": False,
                "legacy_source_candidate_count": int(migration_counts.get("legacy_ths_source_candidates") or 0),
                "currently_observed_candidate_count": int(migration_counts.get("currently_observed_candidates") or 0),
            },
            "formal_observation": {
                "active_count": len(formal_observation),
                "items": formal_observation,
                "near_ready_count": len(formal_candidates),
                "near_ready_items": formal_candidates[:24],
            },
            "trading_candidates": {
                "count": len(trading_map),
                "items": sorted(trading_map.values(), key=lambda item: item["code"]),
                "rule": "交易候选必须来自正式观察、明确允许进入交易候选且通过市场门禁；用户身份不能绕过交易门禁。",
            },
            "style_evidence": {
                "old_deng_count": len(as_list((watchlist.get("old_deng") or {}).get("stocks"))) if isinstance(watchlist.get("old_deng"), dict) else 0,
                "middle_deng_count": len(as_list((watchlist.get("middle_deng") or {}).get("stocks"))) if isinstance(watchlist.get("middle_deng"), dict) else 0,
                "small_deng_count": len(as_list((watchlist.get("small_deng") or {}).get("stocks"))) if isinstance(watchlist.get("small_deng"), dict) else 0,
                "microcap_is_separate": True,
                "may_change_user_assets": False,
            },
            "temporary_candidates": {
                "count": len(temporary_candidates),
                "items": temporary_candidates[:30],
                "automatic_upgrade": False,
            },
            "inventory": {
                "source_stock_count": int(stock_pool.get("stock_count") or len(as_list(stock_pool.get("stocks")))),
                "role_unclassified_count": int(stock_pool.get("role_unclassified_count") or 0),
                "watch_small_overlap_count": int(migration_counts.get("watch_small_overlap") or 0),
                "explained_destination_count": int(stock_pool.get("stock_count") or len(as_list(stock_pool.get("stocks")))),
            },
            "cockpit_read_order": ["用户自选", "正式观察", "系统发现"],
            "guardrails": {
                "user_assets_modified": False,
                "user_fields_published": False,
                "style_pool_used_as_stock_pool": False,
                "temporary_candidate_auto_upgraded": False,
                "research_observation_modified_user_assets": False,
                "automatic_trading": False,
            },
        }

    def write(self) -> dict[str, Any]:
        payload = self.build()
        output = self.root / PUBLIC_OUTPUT
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload

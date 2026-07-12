from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def clean_text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def clean_stock_name(value: Any) -> str:
    name = clean_text(value)
    name = re.sub(r"[（(].*?[）)]", "", name).strip()
    return name.replace("⚠️", "").strip()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def market_from_code(code: str) -> str:
    prefix = code[:2].lower()
    return {"sh": "CN-SSE", "sz": "CN-SZSE", "bj": "CN-BSE", "hk": "HKEX", "us": "US"}.get(prefix, "unknown")


class V2ResearchSystemBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.watchlist = load_json(self.root / "config" / "watchlist.json")
        self.topic_config = load_json(self.root / "config" / "topics-list.json")
        self.topic_state = load_json(self.root / "data" / "topics.json")
        self.taxonomy = load_json(self.root / "config" / "v2-theme-taxonomy.json")

    def build(self) -> tuple[dict[str, Any], dict[str, Any]]:
        topics = self._topics()
        stocks = self._stocks(topics)
        research = self._research_library(topics, stocks)
        stock_pool = self._stock_pool(stocks, topics)
        return research, stock_pool

    def _domains_for(self, searchable: str) -> list[dict[str, str]]:
        lowered = searchable.lower()
        matches = []
        for domain in as_list(self.taxonomy.get("domains")):
            if not isinstance(domain, dict):
                continue
            keywords = [clean_text(item) for item in as_list(domain.get("keywords")) if clean_text(item)]
            if any(keyword.lower() in lowered for keyword in keywords):
                matches.append({"id": clean_text(domain.get("id")), "name": clean_text(domain.get("name"))})
        if matches:
            return matches
        fallback = as_dict(self.taxonomy.get("unmapped_domain"))
        return [{"id": clean_text(fallback.get("id")) or "other", "name": clean_text(fallback.get("name")) or "其他/待归类"}]

    def _topics(self) -> list[dict[str, Any]]:
        state_by_name = {
            clean_text(item.get("name")): item
            for item in as_list(self.topic_state.get("topics"))
            if isinstance(item, dict) and clean_text(item.get("name"))
        }
        rows = []
        for item in as_list(self.topic_config.get("topics")):
            if not isinstance(item, dict):
                continue
            name = clean_text(item.get("name")) or "未命名专题"
            focus = [clean_text(value) for value in as_list(item.get("focus")) if clean_text(value)]
            stock_names = [clean_stock_name(value) for value in as_list(item.get("stocks")) if clean_stock_name(value)]
            current = as_dict(state_by_name.get(name))
            searchable = " ".join([name, *focus, *stock_names])
            domains = self._domains_for(searchable)
            rows.append(
                {
                    "id": stable_id("topic", name),
                    "name": name,
                    "domains": domains,
                    "priority": item.get("priority"),
                    "level": clean_text(item.get("level")) or "专题",
                    "frequency": clean_text(item.get("frequency")) or "未配置",
                    "stock_names": sorted(set(stock_names)),
                    "focus": focus,
                    "current_status": clean_text(current.get("status")) or "current_state_missing",
                    "current_conclusion": clean_text(current.get("conclusion")) or clean_text(current.get("note")) or "当前专题状态没有同名可审计输入。",
                    "current_action": clean_text(current.get("action")) or "等待专题更新。",
                    "current_updated_at": current.get("updated_at") or self.topic_state.get("timestamp"),
                    "mapping_basis": "config/topics-list.json explicit topic fields",
                }
            )
        return rows

    @staticmethod
    def _roles(tags: list[str]) -> list[str]:
        joined = " ".join(tags)
        roles = []
        rules = (("leader", "龙头"), ("core", "中军"), ("high_beta", "弹性"), ("platform", "平台"))
        for role, keyword in rules:
            if keyword in joined:
                roles.append(role)
        return roles or ["unclassified"]

    def _stocks(self, topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_code: dict[str, dict[str, Any]] = {}
        for pool_name, raw_pool in self.watchlist.items():
            pool = as_dict(raw_pool)
            for raw in as_list(pool.get("stocks")):
                if not isinstance(raw, dict):
                    continue
                code = clean_text(raw.get("code")).lower()
                name = clean_stock_name(raw.get("name"))
                if not code or not name:
                    continue
                row = by_code.setdefault(
                    code,
                    {
                        "security_id": stable_id("security", code),
                        "code": code,
                        "name": name,
                        "market": market_from_code(code),
                        "source_pools": [],
                        "tags": [],
                        "source_notes": [],
                    },
                )
                row["source_pools"].append(pool_name)
                row["tags"].extend(clean_text(value) for value in as_list(raw.get("tags")) if clean_text(value))
                if clean_text(raw.get("source")):
                    row["source_notes"].append(clean_text(raw.get("source")))
        for row in by_code.values():
            row["source_pools"] = sorted(set(row["source_pools"]))
            row["tags"] = sorted(set(row["tags"]))
            row["source_notes"] = sorted(set(row["source_notes"]))
            matched_topics = [topic for topic in topics if row["name"] in topic["stock_names"]]
            domain_map = {
                domain["id"]: domain for topic in matched_topics for domain in topic["domains"]
            }
            if not matched_topics:
                domain_map = {domain["id"]: domain for domain in self._domains_for(" ".join([row["name"], *row["tags"]]))}
            row["themes"] = [{"id": topic["id"], "name": topic["name"]} for topic in matched_topics]
            row["domains"] = list(domain_map.values())
            row["roles"] = self._roles(row["tags"])
            row["attention_reason"] = "；".join(filter(None, ["/".join(row["tags"][:5]), "/".join(row["source_notes"][:2])])) or "仅保留自股票池，关注原因待补。"
            focus = [value for topic in matched_topics for value in topic["focus"]]
            row["catalysts"] = [value for value in focus if any(k in value for k in ("订单", "公告", "政策", "IPO", "财报", "交付", "扩产", "催化"))][:6]
            row["trigger_conditions"] = [value for value in focus if any(k in value for k in ("放量", "突破", "回踩", "承接", "扩散", "确认", "共振", "止跌"))][:6]
            row["invalidation_conditions"] = [value for value in focus if any(k in value for k in ("风险", "回避", "无扩散", "不得", "不作为", "降级", "跌破", "拖累"))][:6]
            row["history_status"] = "not_started"
            row["mapping_basis"] = "explicit watchlist + explicit topic stock list/tag keyword"
        return sorted(by_code.values(), key=lambda item: (item["market"], item["code"]))

    def _research_library(self, topics: list[dict[str, Any]], stocks: list[dict[str, Any]]) -> dict[str, Any]:
        domains = []
        configured = [item for item in as_list(self.taxonomy.get("domains")) if isinstance(item, dict)]
        for domain in configured:
            domain_id = clean_text(domain.get("id"))
            domain_topics = [topic for topic in topics if any(item["id"] == domain_id for item in topic["domains"])]
            domain_stocks = [stock for stock in stocks if any(item["id"] == domain_id for item in stock["domains"])]
            domains.append(
                {
                    "id": domain_id,
                    "name": clean_text(domain.get("name")),
                    "coverage_state": "mapped" if domain_topics or domain_stocks else "coverage_gap",
                    "topic_count": len(domain_topics),
                    "stock_count": len(domain_stocks),
                    "topics": domain_topics,
                    "stock_refs": [{"security_id": stock["security_id"], "code": stock["code"], "name": stock["name"]} for stock in domain_stocks],
                }
            )
        unmapped = [topic for topic in topics if any(item["id"] == "other" for item in topic["domains"])]
        return {
            "schema_version": SCHEMA_VERSION,
            "taxonomy_version": clean_text(self.taxonomy.get("taxonomy_version")),
            "generated_at": now_iso(),
            "mapping_policy": clean_text(self.taxonomy.get("mapping_policy")),
            "domains": domains,
            "unmapped_topics": unmapped,
            "source_files": ["config/topics-list.json", "data/topics.json", "config/watchlist.json", "config/v2-theme-taxonomy.json"],
        }

    def _stock_pool(self, stocks: list[dict[str, Any]], topics: list[dict[str, Any]]) -> dict[str, Any]:
        role_gaps = sum(1 for item in stocks if item["roles"] == ["unclassified"])
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now_iso(),
            "stock_count": len(stocks),
            "topic_count": len(topics),
            "role_unclassified_count": role_gaps,
            "governance": {
                "role_policy": "仅从显式标签识别龙头/中军/弹性/平台；无证据时保持 unclassified。",
                "position_policy": "股票池不代表持仓，不生成个性化买卖动作。",
                "history_policy": "历史表现将在回溯阶段按快照与结果窗口写入，当前不得补造。",
            },
            "stocks": stocks,
        }

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
        self.templates = load_json(self.root / "config" / "v2-research-templates.json")
        self.formal_observation = load_json(self.root / "config" / "v2-formal-observation.json")

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
                    "current_status": clean_text(current.get("status")) or "观察",
                    "current_conclusion": clean_text(current.get("conclusion")) or clean_text(current.get("note")) or "当前专题状态没有同名可审计输入。",
                    "current_action": clean_text(current.get("action")) or "等待专题更新。",
                    "current_updated_at": current.get("updated_at") or self.topic_state.get("timestamp"),
                    "mapping_basis": "config/topics-list.json explicit topic fields",
                }
            )
        seen_names = {row["name"] for row in rows}
        for item in as_list(self.formal_observation.get("themes")):
            if not isinstance(item, dict):
                continue
            name = clean_text(item.get("name")) or "未命名正式观察专题"
            if name in seen_names:
                continue
            focus = [clean_text(value) for value in as_list(item.get("focus")) if clean_text(value)]
            stock_names = [clean_stock_name(value) for value in as_list(item.get("stocks")) if clean_stock_name(value)]
            configured_domains = [
                {"id": clean_text(domain.get("id")), "name": clean_text(domain.get("name"))}
                for domain in as_list(item.get("domains"))
                if isinstance(domain, dict) and clean_text(domain.get("id"))
            ]
            rows.append(
                {
                    "id": stable_id("topic", name),
                    "name": name,
                    "domains": configured_domains or self._domains_for(" ".join([name, *focus, *stock_names])),
                    "priority": item.get("priority"),
                    "level": clean_text(item.get("level")) or "正式观察专题",
                    "frequency": clean_text(item.get("frequency")) or "盘后复核",
                    "stock_names": sorted(set(stock_names)),
                    "focus": focus,
                    "current_status": clean_text(item.get("current_status")) or "观察",
                    "current_conclusion": clean_text(item.get("current_conclusion")) or "等待持续核验。",
                    "current_action": clean_text(item.get("current_action")) or "持续观察。",
                    "current_updated_at": item.get("current_updated_at"),
                    "mapping_basis": "config/v2-formal-observation.json research_import",
                }
            )
            seen_names.add(name)
        return rows

    @staticmethod
    def _roles(tags: list[str], topic_names: list[str]) -> tuple[list[str], list[str]]:
        joined = " ".join(tags)
        roles = []
        evidence = []
        rules = (("leader", "龙头"), ("core", "中军"), ("high_beta", "弹性"), ("platform", "平台"))
        for role, keyword in rules:
            if keyword in joined:
                roles.append(role)
                evidence.append(f"自选标签明确包含“{keyword}”")
        if "core" not in roles and any(keyword in joined for keyword in ("指数权重", "核心资产", "大盘权重")):
            roles.append("core")
            evidence.append("自选标签明确标注指数/大盘权重，作为中军角色依据")
        for topic_name in topic_names:
            for role, keyword in rules:
                if role not in roles and keyword in topic_name:
                    roles.append(role)
                    evidence.append(f"专题名称“{topic_name}”明确包含“{keyword}”")
        return (roles or ["unclassified"], evidence or ["缺少显式角色标签，保持未分类"])

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
        formal_by_code: dict[str, dict[str, Any]] = {}
        for raw in as_list(self.formal_observation.get("stocks")):
            if not isinstance(raw, dict):
                continue
            code = clean_text(raw.get("code")).lower()
            name = clean_stock_name(raw.get("name"))
            if not code or not name:
                continue
            formal_by_code[code] = raw
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
            row["source_pools"].append("research_import")
            row["tags"].extend(clean_text(value) for value in as_list(raw.get("tags")) if clean_text(value))
            row["source_notes"].append("V2正式观察研究导入")
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
            row["roles"], row["role_evidence"] = self._roles(row["tags"], [topic["name"] for topic in matched_topics])
            row["attention_reason"] = "；".join(filter(None, ["/".join(row["tags"][:5]), "/".join(row["source_notes"][:2])])) or "仅保留自股票池，关注原因待补。"
            focus = [value for topic in matched_topics for value in topic["focus"]]
            row["catalysts"] = [value for value in focus if any(k in value for k in ("订单", "公告", "政策", "IPO", "财报", "交付", "扩产", "催化"))][:6]
            row["trigger_conditions"] = [value for value in focus if any(k in value for k in ("放量", "突破", "回踩", "承接", "扩散", "确认", "共振", "止跌"))][:6]
            row["invalidation_conditions"] = [value for value in focus if any(k in value for k in ("风险", "回避", "无扩散", "不得", "不作为", "降级", "跌破", "拖累"))][:6]
            row["history_status"] = "not_started"
            row["mapping_basis"] = "explicit watchlist + explicit topic stock list/tag keyword"
            formal = as_dict(formal_by_code.get(row["code"]))
            if formal:
                explicit_roles = [clean_text(value) for value in as_list(formal.get("roles")) if clean_text(value)]
                explicit_role_evidence = [clean_text(value) for value in as_list(formal.get("role_evidence")) if clean_text(value)]
                row["identity_source"] = clean_text(formal.get("identity_source"))
                row["roles"] = explicit_roles or ["unclassified"]
                row["role_evidence"] = explicit_role_evidence or ["研究导入未提供角色证据，保持未分类"]
                row["attention_reason"] = clean_text(formal.get("attention_reason")) or row["attention_reason"]
                row["counter_evidence"] = [clean_text(value) for value in as_list(formal.get("counter_evidence")) if clean_text(value)]
                row["catalysts"] = [clean_text(value) for value in as_list(formal.get("catalysts")) if clean_text(value)]
                row["trigger_conditions"] = [clean_text(value) for value in as_list(formal.get("trigger_conditions")) if clean_text(value)]
                row["invalidation_conditions"] = [clean_text(value) for value in as_list(formal.get("invalidation_conditions")) if clean_text(value)]
                row["suitable_environment"] = [clean_text(value) for value in as_list(formal.get("suitable_environment")) if clean_text(value)]
                row["unsuitable_environment"] = [clean_text(value) for value in as_list(formal.get("unsuitable_environment")) if clean_text(value)]
                row["source_refs"] = [dict(value) for value in as_list(formal.get("source_refs")) if isinstance(value, dict)]
                row["chain_side"] = clean_text(formal.get("chain_side"))
                row["benefit_tier"] = clean_text(formal.get("benefit_tier"))
                row["evidence_grade"] = clean_text(formal.get("evidence_grade"))
                row["research_classification"] = clean_text(formal.get("research_classification"))
                row["formal_observation_requested"] = formal.get("formal_observation_requested") is True
                row["trading_candidate_opt_in"] = formal.get("trading_candidate_opt_in") is True
                row["observation_source"] = "research_import"
                row["is_user_asset"] = False
                row["mapping_basis"] = "official evidence research_import + explicit formal observation theme"
        return sorted(by_code.values(), key=lambda item: (item["market"], item["code"]))

    def _research_library(self, topics: list[dict[str, Any]], stocks: list[dict[str, Any]]) -> dict[str, Any]:
        domains = []
        configured = [item for item in as_list(self.taxonomy.get("domains")) if isinstance(item, dict)]
        templates = {
            clean_text(item.get("domain_id")): item
            for item in as_list(self.templates.get("templates"))
            if isinstance(item, dict) and clean_text(item.get("domain_id"))
        }
        for domain in configured:
            domain_id = clean_text(domain.get("id"))
            domain_topics = [topic for topic in topics if any(item["id"] == domain_id for item in topic["domains"])]
            domain_stocks = [stock for stock in stocks if any(item["id"] == domain_id for item in stock["domains"])]
            template = as_dict(templates.get(domain_id))
            if domain_topics or domain_stocks:
                coverage_state = "mapped"
            elif template:
                coverage_state = "template_ready_mapping_gap"
            else:
                coverage_state = "coverage_gap"
            domains.append(
                {
                    "id": domain_id,
                    "name": clean_text(domain.get("name")),
                    "coverage_state": coverage_state,
                    "topic_count": len(domain_topics),
                    "stock_count": len(domain_stocks),
                    "topics": domain_topics,
                    "stock_refs": [{"security_id": stock["security_id"], "code": stock["code"], "name": stock["name"]} for stock in domain_stocks],
                    "research_template": template or None,
                }
            )
        unmapped = [topic for topic in topics if any(item["id"] == "other" for item in topic["domains"])]
        return {
            "schema_version": SCHEMA_VERSION,
            "taxonomy_version": clean_text(self.taxonomy.get("taxonomy_version")),
            "generated_at": now_iso(),
            "mapping_policy": clean_text(self.taxonomy.get("mapping_policy")),
            "research_governance": clean_text(self.templates.get("governance")),
            "domains": domains,
            "unmapped_topics": unmapped,
            "source_files": ["config/topics-list.json", "data/topics.json", "config/watchlist.json", "config/v2-theme-taxonomy.json", "config/v2-research-templates.json", "config/v2-formal-observation.json"],
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
                "role_policy": "仅从显式自选标签和专题名称识别龙头/中军/弹性/平台；每个角色同时保存 role_evidence，无证据时保持 unclassified。",
                "position_policy": "股票池不代表持仓，不生成个性化买卖动作。",
                "history_policy": "历史表现将在回溯阶段按快照与结果窗口写入，当前不得补造。",
            },
            "stocks": stocks,
        }

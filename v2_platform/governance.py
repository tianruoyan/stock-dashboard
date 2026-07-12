from __future__ import annotations

from pathlib import Path
from typing import Any

from v2_platform.learning import as_dict, as_list, load_json


class V2GovernanceBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.sources = load_json(self.root / "config" / "v2-source-governance.json")
        self.automation = load_json(self.root / "config" / "v2-automation-routing.json")

    def build(self) -> dict[str, Any]:
        path = self.root / str(self.sources.get("input_path") or "data/v2/inputs/events.json")
        event_payload = load_json(path)
        blogger_accounts_payload = load_json(self.root / ".v2_private" / "blogger-accounts.json")
        blogger_accounts = [item for item in as_list(blogger_accounts_payload.get("accounts")) if isinstance(item, dict)]
        enabled_accounts = [item for item in blogger_accounts if item.get("enabled") is not False]
        events = [self._validate_event(item) for item in as_list(event_payload.get("events")) if isinstance(item, dict)]
        usable_events = [item for item in events if item.get("quality_state") == "usable"]
        blogger_events = [item for item in events if item.get("source_type") == "blogger_social"]
        official_events = [item for item in usable_events if item.get("source_type") in {"official_policy", "official_research", "exchange_filing", "company_filing"}]
        tasks = [item for item in as_list(self.automation.get("legacy_tasks")) if isinstance(item, dict)]
        categories = set(str(item) for item in as_list(self.automation.get("categories")))
        routing_issues = []
        for item in tasks:
            unknown = sorted(set(str(value) for value in as_list(item.get("target_categories"))) - categories)
            if unknown:
                routing_issues.append({"task": item.get("name"), "issue": "unknown_category", "values": unknown})
        return {
            "schema_version": 1,
            "source_governance_version": self.sources.get("version"),
            "automation_routing_version": self.automation.get("version"),
            "fact_inference_action_layers": self.sources.get("fact_inference_action_layers"),
            "event_registry": {
                "state": "available" if events else "input_pending",
                "event_count": len(events),
                "usable_event_count": len(usable_events),
                "official_event_count": len(official_events),
                "blogger_event_count": len(blogger_events),
                "blogger_account_count": len(blogger_accounts),
                "blogger_enabled_account_count": len(enabled_accounts),
                "blogger_platform_counts": {
                    platform: sum(str(item.get("platform")) == platform for item in enabled_accounts)
                    for platform in sorted({str(item.get("platform")) for item in enabled_accounts if item.get("platform")})
                },
                "blogger_account_privacy": "本机私有配置；账号名称和链接不进入公开决策产物。",
                "events": events,
                "input_path": str(path.relative_to(self.root)),
                "blogger_policy": as_dict(as_dict(self.sources.get("source_types")).get("blogger_social")),
                "conflict_policy": as_list(self.sources.get("conflict_policy")),
            },
            "automation_routing": {
                "state": "valid" if not routing_issues else "invalid",
                "task_count": len(tasks),
                "tasks": tasks,
                "issues": routing_issues,
                "cutover_rule": self.automation.get("cutover_rule"),
            },
        }

    def _validate_event(self, item: dict[str, Any]) -> dict[str, Any]:
        required = [str(value) for value in as_list(self.sources.get("required_fields"))]
        missing = [key for key in required if item.get(key) in (None, "")]
        source_type = str(item.get("source_type") or "")
        rule = as_dict(as_dict(self.sources.get("source_types")).get(source_type))
        flags = []
        if not rule:
            flags.append("unknown_source_type")
        if source_type == "blogger_social" and item.get("fact_state") in {"verified_fact", "fact"}:
            flags.append("blogger_cannot_support_fact")
        if source_type in {"blogger_social", "user_note"}:
            normalized_role = rule.get("required_role")
            fact_state = "expectation_only" if source_type == "blogger_social" else "research_input_only"
        else:
            normalized_role = item.get("role") or "fact_candidate"
            fact_state = "pending_verification" if missing or flags else str(item.get("fact_state") or "source_verified")
        return {
            **item,
            "normalized_role": normalized_role,
            "fact_state": fact_state,
            "quality_state": "invalid" if missing or flags else "usable",
            "missing_fields": missing,
            "quality_flags": flags,
        }

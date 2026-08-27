from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2_platform.cross_market import V22CrossMarketBuilder
from v2_platform.environment_evidence import canonical_hash, stable_id
from v2_platform.environment_state_machine import decide_environment_transition
from v2_platform.g5_gate import build_g5_links
from v2_platform.style_regime import V22StyleRegimeBuilder


PUBLIC_OUTPUT = "data/v2/v22/environment-decision.json"
SNAPSHOT_INDEX = "data/v2/v22/environment-decision-snapshot-index.json"
POLICY_VERSION = "2026-07-19.e5.4"
PRESENTATION_VERSION = "plain-language-2026-07-23.1"


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


class V22EnvironmentDecisionBuilder:
    def __init__(self, root: Path, *, built_at: datetime | None = None) -> None:
        self.root = root.resolve()
        resolved = built_at or datetime.now(timezone.utc).astimezone()
        if resolved.tzinfo is None:
            raise ValueError("built_at must include timezone")
        self.built_at = resolved

    def build(self, *, previous: dict[str, Any] | None = None) -> dict[str, Any]:
        environment = load_json(self.root / "data/v2/v22/market-environment.json")
        decision = load_json(self.root / "data/v2/decision-system.json")
        if not environment.get("environment_snapshot_id"):
            raise ValueError("market environment snapshot missing")
        styles = V22StyleRegimeBuilder(self.root).build(environment)
        cross_market = V22CrossMarketBuilder(self.root).build(environment)
        prior = previous if previous is not None else self._previous_transition(environment)
        transition = decide_environment_transition(environment, previous=prior, policy_version=POLICY_VERSION)
        g5_links = build_g5_links(decision, environment, transition, cross_market)
        decision_snapshot_id = stable_id(
            "environment_decision",
            environment.get("environment_snapshot_id"),
            transition.get("transition_id"),
            canonical_hash(styles),
            canonical_hash(cross_market),
            canonical_hash(g5_links),
            POLICY_VERSION,
            PRESENTATION_VERSION,
        )
        style_strength = [item for item in styles if item.get("price_state") == "strengthening"]
        style_weakness = [item for item in styles if item.get("price_state") == "weakening"]
        confirmed_external = [item for item in cross_market if item.get("transmission_state") == "confirmed"]
        payload: dict[str, Any] = {
            "schema_version": 1,
            "mode": "shadow_only",
            "decision_snapshot_id": decision_snapshot_id,
            "environment_snapshot_id": environment.get("environment_snapshot_id"),
            "trade_date": environment.get("trade_date"),
            "session_phase": environment.get("session_phase"),
            "as_of": environment.get("as_of"),
            "built_at": self.built_at.isoformat(timespec="seconds"),
            "policy_version": POLICY_VERSION,
            "presentation_version": PRESENTATION_VERSION,
            "primary_state": transition.get("primary_state"),
            "action_constraint": transition.get("action_constraint"),
            "state_transition": transition,
            "style_regimes": styles,
            "cross_market_mappings": cross_market,
            "g5_links": g5_links,
            "summary": {
                "strengthening_styles": [item.get("style_id") for item in style_strength],
                "weakening_styles": [item.get("style_id") for item in style_weakness],
                "confirmed_external_count": len(confirmed_external),
                "g5_support": sum(item.get("g5_result") == "support" for item in g5_links),
                "g5_suppress": sum(item.get("g5_result") in {"suppress", "block"} for item in g5_links),
            },
            "user_view": {
                "当前状态": transition.get("primary_state"),
                "当前允许": transition.get("action_constraint"),
                "状态变化原因": transition.get("transition_reason"),
                "确认要求": "积极变化至少连续两个不同事实快照确认；可靠风险证据可快速降低行动许可。",
                "风格说明": "老登、中登、小登使用显式观察篮子；微盘独立，不与小登互换。",
                "外盘说明": "只有当前交易日海外触发与A股代表股同向兑现，才可支持环境门禁。",
            },
            "guardrails": {
                "current_v1_modified": False,
                "production_entry_changed": False,
                "automatic_trading": False,
                "user_assets_modified": False,
                "style_pool_used_as_user_pool": False,
                "temporary_candidate_auto_upgraded": False,
                "model_promoted": False,
                "g5_bypasses_other_gates": False,
                "single_company_event_auto_upgrades_theme": False,
            },
        }
        immutable_material = {key: value for key, value in payload.items() if key not in {"built_at", "immutable_hash"}}
        payload["immutable_hash"] = canonical_hash(immutable_material)
        return payload

    def _previous_transition(self, environment: dict[str, Any]) -> dict[str, Any] | None:
        index = load_json(self.root / SNAPSHOT_INDEX)
        rows = [item for item in as_list(index.get("snapshots")) if isinstance(item, dict)]
        rows.sort(key=lambda item: (str(item.get("as_of") or ""), str(item.get("decision_snapshot_id") or "")))
        for item in reversed(rows):
            path = self.root / str(item.get("relative_path") or "")
            previous = load_json(path)
            if previous.get("environment_snapshot_id") != environment.get("environment_snapshot_id"):
                transition = previous.get("state_transition")
                if isinstance(transition, dict):
                    return transition
        return None

    def write(self) -> dict[str, Any]:
        current_path = self.root / PUBLIC_OUTPUT
        existing = load_json(current_path)
        payload = self.build()
        if existing.get("decision_snapshot_id") == payload.get("decision_snapshot_id") and existing.get("policy_version") == POLICY_VERSION:
            self._write_index(existing, self._snapshot_path(existing))
            return existing
        snapshot = self._snapshot_path(payload)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        if snapshot.exists():
            saved = load_json(snapshot)
            if saved.get("immutable_hash") != payload.get("immutable_hash"):
                raise ValueError("immutable environment decision snapshot conflict")
        else:
            snapshot.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        current_path.parent.mkdir(parents=True, exist_ok=True)
        current_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._write_index(payload, snapshot)
        return payload

    def _snapshot_path(self, payload: dict[str, Any]) -> Path:
        return self.root / "data/v2/v22/environment-decision-snapshots" / str(payload.get("trade_date")) / f"{payload.get('decision_snapshot_id')}.json"

    def _write_index(self, payload: dict[str, Any], snapshot: Path) -> None:
        if not snapshot.exists():
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        path = self.root / SNAPSHOT_INDEX
        existing = load_json(path)
        rows = [item for item in as_list(existing.get("snapshots")) if isinstance(item, dict)]
        if not any(item.get("decision_snapshot_id") == payload.get("decision_snapshot_id") for item in rows):
            rows.append({
                "decision_snapshot_id": payload.get("decision_snapshot_id"),
                "environment_snapshot_id": payload.get("environment_snapshot_id"),
                "trade_date": payload.get("trade_date"),
                "as_of": payload.get("as_of"),
                "primary_state": payload.get("primary_state"),
                "immutable_hash": payload.get("immutable_hash"),
                "relative_path": str(snapshot.relative_to(self.root)),
            })
        rows.sort(key=lambda item: (str(item.get("as_of") or ""), str(item.get("decision_snapshot_id") or "")))
        path.write_text(json.dumps({"schema_version": 1, "generated_at": now_iso(), "snapshot_count": len(rows), "snapshots": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

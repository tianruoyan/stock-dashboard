from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4


POLICY_PATH = "config/v2-longbridge-analysis-policy.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def clean_text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(value)).hexdigest()}"


def stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("|".join(clean_text(part) for part in parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def load_json_or_empty(path: Path) -> dict[str, Any]:
    try:
        return load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {}


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def timezone_aware(value: Any) -> bool:
    text = clean_text(value)
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def url_host(value: Any) -> str:
    parsed = urlparse(clean_text(value))
    return (parsed.hostname or "").lower() if parsed.scheme in {"http", "https"} else ""


def nested_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).strip().lower())
            keys.update(nested_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(nested_keys(child))
    return keys


def safe_identifier(value: Any) -> str:
    text = clean_text(value)
    return "".join(character for character in text if character.isalnum() or character in {"-", "_", "."})[:96]


@dataclass(frozen=True)
class LongbridgeAnalysisPolicy:
    payload: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "LongbridgeAnalysisPolicy":
        return cls(load_json(path))

    @property
    def version(self) -> str:
        return clean_text(self.payload.get("version"))

    @property
    def forbidden_keys(self) -> set[str]:
        return {clean_text(item).lower() for item in as_list(self.payload.get("forbidden_input_keys")) if clean_text(item)}

    @property
    def private_keys(self) -> set[str]:
        return {
            clean_text(item).lower()
            for item in as_list(self.payload.get("private_input_keys_never_published"))
            if clean_text(item)
        }

    @property
    def immutable_boundaries(self) -> dict[str, bool]:
        return {str(key): bool(value) for key, value in as_dict(self.payload.get("immutable_boundaries")).items()}


class LongbridgeAnalysisImporter:
    def __init__(
        self,
        root: Path,
        input_path: Path | None = None,
        *,
        policy_path: Path | None = None,
        generated_at: str | None = None,
    ) -> None:
        self.root = root.resolve()
        self.policy = LongbridgeAnalysisPolicy.load(policy_path or self.root / POLICY_PATH)
        configured_input = self.root / clean_text(self.policy.payload.get("default_input"))
        self.input_path = (input_path or configured_input).resolve()
        self.output_path = self.root / clean_text(self.policy.payload.get("public_output"))
        self.report_path = self.root / clean_text(self.policy.payload.get("import_report"))
        self.generated_at = generated_at or now_iso()

    def evaluate_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        hard_batch_errors: list[str] = []
        if not isinstance(payload, dict):
            hard_batch_errors.append("batch_not_object")
        if int(payload.get("schema_version") or 0) != 1:
            hard_batch_errors.append("unsupported_schema_version")
        batch_forbidden = sorted(nested_keys({key: value for key, value in payload.items() if key != "items"}) & self.policy.forbidden_keys)
        if batch_forbidden:
            hard_batch_errors.append("forbidden_batch_keys:" + ",".join(batch_forbidden))
        items = as_list(payload.get("items"))
        accepted: list[dict[str, Any]] = []
        review_queue: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        if hard_batch_errors:
            return {
                "batch_errors": hard_batch_errors,
                "accepted": accepted,
                "review_queue": review_queue,
                "rejected": rejected,
            }
        for index, raw in enumerate(items):
            if not isinstance(raw, dict):
                rejected.append(self._minimal_result({}, index, ["item_not_object"], []))
                continue
            state, normalized, reasons, warnings = self._normalize_item(raw, index)
            if state == "accepted":
                accepted.append(normalized)
            elif state == "review_required":
                review_queue.append(self._minimal_result(raw, index, reasons, warnings))
            else:
                rejected.append(self._minimal_result(raw, index, reasons, warnings))
        return {
            "batch_errors": hard_batch_errors,
            "accepted": accepted,
            "review_queue": review_queue,
            "rejected": rejected,
        }

    def run(self, *, write: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
        current = load_json_or_empty(self.output_path)
        if not self.input_path.exists():
            artifact = current or self._empty_artifact("input_pending")
            report = self._report(
                status="waiting",
                input_state="input_pending",
                accepted=0,
                review_queue=[],
                rejected=[],
                batch_errors=[],
                last_valid_preserved=bool(current),
            )
            if write:
                if not current:
                    atomic_write_json(self.output_path, artifact)
                atomic_write_json(self.report_path, report)
            return report, artifact

        try:
            raw_payload = load_json(self.input_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            report = self._report(
                status="invalid",
                input_state="unreadable",
                accepted=0,
                review_queue=[],
                rejected=[],
                batch_errors=[f"{type(exc).__name__}:invalid_json"],
                last_valid_preserved=bool(current),
            )
            artifact = current or self._empty_artifact("invalid_input_no_reference")
            if write:
                if not current:
                    atomic_write_json(self.output_path, artifact)
                atomic_write_json(self.report_path, report)
            return report, artifact

        evaluated = self.evaluate_payload(raw_payload)
        accepted = evaluated["accepted"]
        review_queue = evaluated["review_queue"]
        rejected = evaluated["rejected"]
        batch_errors = evaluated["batch_errors"]
        if accepted:
            artifact = self._artifact(raw_payload, accepted)
            status = "passed" if not review_queue and not rejected and not batch_errors else "degraded"
            input_state = "imported"
            last_valid_preserved = False
            if write:
                atomic_write_json(self.output_path, artifact)
        else:
            artifact = current or self._empty_artifact("no_eligible_reference")
            status = "waiting" if not as_list(raw_payload.get("items")) and not batch_errors else "invalid"
            input_state = "empty" if status == "waiting" else "rejected_or_review_only"
            last_valid_preserved = bool(current)
            if write and not current:
                atomic_write_json(self.output_path, artifact)
        report = self._report(
            status=status,
            input_state=input_state,
            accepted=len(accepted),
            review_queue=review_queue,
            rejected=rejected,
            batch_errors=batch_errors,
            last_valid_preserved=last_valid_preserved,
        )
        if write:
            atomic_write_json(self.report_path, report)
        return report, artifact

    def _normalize_item(
        self,
        raw: dict[str, Any],
        index: int,
    ) -> tuple[str, dict[str, Any], list[str], list[str]]:
        errors: list[str] = []
        review: list[str] = []
        warnings: list[str] = []
        required = [clean_text(item) for item in as_list(self.policy.payload.get("required_item_fields"))]
        reviewable_collections = {"subjects", "claims", "citations", "invalidation_conditions"}
        missing = [
            field
            for field in required
            if field not in raw or (field not in reviewable_collections and raw.get(field) in (None, "", []))
        ]
        if missing:
            errors.append("missing_required_fields:" + ",".join(sorted(missing)))
        forbidden = sorted(nested_keys(raw) & self.policy.forbidden_keys)
        if forbidden:
            errors.append("forbidden_input_keys:" + ",".join(forbidden))
        if clean_text(raw.get("provider")).lower() != "longbridge":
            errors.append("provider_must_be_longbridge")
        product = clean_text(raw.get("product"))
        if product not in {clean_text(item) for item in as_list(self.policy.payload.get("allowed_products"))}:
            errors.append("unsupported_product")
        scope = clean_text(raw.get("scope"))
        if scope not in {clean_text(item) for item in as_list(self.policy.payload.get("allowed_scopes"))}:
            errors.append("unsupported_scope")
        source_host = url_host(raw.get("source_url"))
        if source_host not in {clean_text(item).lower() for item in as_list(self.policy.payload.get("allowed_source_hosts"))}:
            errors.append("source_url_not_longbridge_official")
        for field in ("published_at", "observed_at"):
            if raw.get(field) not in (None, "") and not timezone_aware(raw.get(field)):
                errors.append(f"{field}_must_include_timezone")

        subjects = []
        for subject in as_list(raw.get("subjects")):
            if not isinstance(subject, dict) or not clean_text(subject.get("type")) or not clean_text(subject.get("value")):
                review.append("invalid_subject")
                continue
            subjects.append({"type": clean_text(subject.get("type")), "value": clean_text(subject.get("value"))})
        if not subjects:
            review.append("no_valid_subject")

        citation_required = [clean_text(item) for item in as_list(self.policy.payload.get("required_citation_fields"))]
        citations = []
        citation_ids: set[str] = set()
        for citation in as_list(raw.get("citations")):
            if not isinstance(citation, dict):
                review.append("citation_not_object")
                continue
            missing_citation = [field for field in citation_required if citation.get(field) in (None, "")]
            if missing_citation or not url_host(citation.get("url")) or not timezone_aware(citation.get("published_at")):
                review.append("incomplete_citation")
                continue
            citation_id = safe_identifier(citation.get("citation_id"))
            if not citation_id:
                review.append("invalid_citation_id")
                continue
            citation_ids.add(citation_id)
            citations.append(
                {
                    "citation_id": citation_id,
                    "title": clean_text(citation.get("title")),
                    "url": clean_text(citation.get("url")),
                    "published_at": clean_text(citation.get("published_at")),
                    "source_type": clean_text(citation.get("source_type")) or "provider_citation",
                }
            )
        if not citations:
            review.append("no_complete_citation")

        allowed_claims = {clean_text(item) for item in as_list(self.policy.payload.get("allowed_claim_types"))}
        claim_roles = as_dict(self.policy.payload.get("claim_roles"))
        claims = []
        has_counter = False
        for claim_index, claim in enumerate(as_list(raw.get("claims"))):
            if not isinstance(claim, dict):
                review.append("claim_not_object")
                continue
            claim_type = clean_text(claim.get("claim_type"))
            statement = clean_text(claim.get("statement"))
            if claim_type not in allowed_claims or not statement:
                review.append("invalid_claim")
                continue
            refs = [safe_identifier(item) for item in as_list(claim.get("citation_ids")) if safe_identifier(item)]
            unknown_refs = sorted(set(refs) - citation_ids)
            if unknown_refs:
                review.append("claim_has_unknown_citation")
            if claim_type == "reported_fact" and not refs:
                review.append("reported_fact_without_citation")
            has_counter = has_counter or claim_type in {"risk", "counter_view"}
            claims.append(
                {
                    "claim_id": safe_identifier(claim.get("claim_id"))
                    or stable_id("lb_claim", raw.get("analysis_id"), claim_index, statement),
                    "claim_type": claim_type,
                    "statement": statement,
                    "citation_ids": refs,
                    "normalized_role": clean_text(claim_roles.get(claim_type)),
                    "local_verification_status": (
                        "pending_independent_verification" if claim_type == "reported_fact" else "not_a_local_fact"
                    ),
                    "action_permitted": False,
                }
            )
        if not claims:
            review.append("no_valid_claim")
        if not has_counter:
            review.append("counter_evidence_missing")
        invalidation = [clean_text(item) for item in as_list(raw.get("invalidation_conditions")) if clean_text(item)]
        if not invalidation:
            review.append("invalidation_conditions_missing")

        model = as_dict(raw.get("model"))
        model_name = clean_text(model.get("name")) or "Longbridge model (undisclosed)"
        model_version = clean_text(model.get("version")) or "undisclosed"
        disclosure = clean_text(model.get("disclosure_state")) or "undisclosed"
        if model_version == "undisclosed" or disclosure == "undisclosed":
            warnings.append("model_version_or_disclosure_missing")

        if errors:
            return "rejected", {}, sorted(set(errors)), sorted(set(warnings))
        if review:
            return "review_required", {}, sorted(set(review)), sorted(set(warnings))

        source_digest = content_hash(
            {key: value for key, value in raw.items() if str(key).strip().lower() not in self.policy.private_keys}
        )
        analysis_id = safe_identifier(raw.get("analysis_id")) or stable_id("lb_analysis", source_digest)
        reference_id = stable_id("lb_reference", analysis_id, source_digest, self.policy.version)
        normalized = {
            "reference_id": reference_id,
            "analysis_id": analysis_id,
            "provider": "Longbridge",
            "product": product,
            "scope": scope,
            "title": clean_text(raw.get("title")),
            "source_url": clean_text(raw.get("source_url")),
            "source_host": source_host,
            "published_at": clean_text(raw.get("published_at")),
            "observed_at": clean_text(raw.get("observed_at")),
            "subjects": subjects,
            "horizon": clean_text(raw.get("horizon")),
            "claims": claims,
            "citations": citations,
            "invalidation_conditions": invalidation,
            "model": {
                "name": model_name,
                "version": model_version,
                "disclosure_state": disclosure,
                "replayability": "limited" if "undisclosed" in {model_version, disclosure} else "declared_only",
            },
            "attribution": f"Longbridge · {product} · {model_name}",
            "evidence_role": "external_institutional_analysis_reference",
            "fact_state": "provider_analysis_not_local_fact",
            "quality_state": "usable_reference",
            "allowed_uses": list(as_list(self.policy.payload.get("allowed_uses"))),
            "immutable_boundaries": deepcopy(self.policy.immutable_boundaries),
            "required_local_checks": [
                "核验 reported_fact 的原始引文、主体、时间和口径",
                "用当前市场事实检查观点是否仍在有效窗口",
                "检查本地代表股共振、市场环境、位置与可交易性",
                "保留反向证据；不得以机构身份替代 G0—G7",
            ],
            "warnings": sorted(set(warnings)),
            "source_content_hash": source_digest,
            "provenance_hash": content_hash(
                {"policy_version": self.policy.version, "source_content_hash": source_digest, "reference_id": reference_id}
            ),
        }
        return "accepted", normalized, [], sorted(set(warnings))

    def _artifact(self, raw_payload: dict[str, Any], accepted: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "mode": "shadow_reference_only",
            "provider": "Longbridge",
            "policy_version": self.policy.version,
            "batch_id": safe_identifier(raw_payload.get("batch_id")) or stable_id("lb_batch", content_hash(accepted)),
            "generated_at": self.generated_at,
            "input_state": "imported",
            "reference_count": len(accepted),
            "references": accepted,
            "governance": self._governance(),
            "immutable_hash": content_hash(
                {"policy_version": self.policy.version, "references": accepted, "mode": "shadow_reference_only"}
            ),
        }

    def _empty_artifact(self, input_state: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "mode": "shadow_reference_only",
            "provider": "Longbridge",
            "policy_version": self.policy.version,
            "generated_at": self.generated_at,
            "input_state": input_state,
            "reference_count": 0,
            "references": [],
            "governance": self._governance(),
            "immutable_hash": content_hash(
                {"policy_version": self.policy.version, "references": [], "mode": "shadow_reference_only"}
            ),
        }

    def _governance(self) -> dict[str, Any]:
        return {
            "provider_role": "外部机构分析模型与观点来源；不是交易系统、行情唯一真相源或用户资产来源。",
            "attribution_rule": "前台必须使用“长桥分析认为/长桥模型提示”等归属表达，并显示时间与来源链接。",
            "fact_rule": "长桥 reported_fact 仍是事实候选，须经本地独立来源和质量层核验。",
            "decision_rule": "引用可以补充研究、解释和反证，但不得独立通过 G0、升级决策案例或改变行动状态。",
            "watchlist_rule": "长桥不接管、不读取、不同步同花顺自选，也不创建任何用户资产来源关系。",
            "immutable_boundaries": deepcopy(self.policy.immutable_boundaries),
        }

    def _minimal_result(
        self,
        raw: dict[str, Any],
        index: int,
        reasons: list[str],
        warnings: list[str],
    ) -> dict[str, Any]:
        return {
            "analysis_id": safe_identifier(raw.get("analysis_id")) or f"item_{index + 1}",
            "content_hash": content_hash(
                {key: value for key, value in raw.items() if str(key).strip().lower() not in self.policy.private_keys}
            ),
            "reason_codes": sorted(set(reasons)),
            "warnings": sorted(set(warnings)),
        }

    def _report(
        self,
        *,
        status: str,
        input_state: str,
        accepted: int,
        review_queue: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
        batch_errors: list[str],
        last_valid_preserved: bool,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": status,
            "mode": "shadow_reference_only",
            "provider": "Longbridge",
            "policy_version": self.policy.version,
            "generated_at": self.generated_at,
            "input_state": input_state,
            "input_path": str(self.input_path),
            "summary": {
                "accepted": accepted,
                "review_required": len(review_queue),
                "rejected": len(rejected),
                "last_valid_preserved": last_valid_preserved,
            },
            "batch_errors": batch_errors,
            "review_queue": review_queue,
            "rejected": rejected,
            "production_behavior_changed": False,
            "user_assets_changed": False,
            "watchlist_sync_changed": False,
            "trading_enabled": False,
        }


def acceptance_probe_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "batch_id": "synthetic-acceptance-probe",
        "collected_at": "2026-08-02T10:00:00+08:00",
        "items": [
            {
                "analysis_id": "synthetic-valid-reference",
                "product": "longbridge_agent_platform",
                "provider": "Longbridge",
                "scope": "industry",
                "title": "合约验收用机构分析样例（非真实投资观点）",
                "source_url": "https://longbridge.com/ai",
                "published_at": "2026-08-02T09:00:00+08:00",
                "observed_at": "2026-08-02T09:01:00+08:00",
                "subjects": [{"type": "industry", "value": "contract-test-only"}],
                "horizon": "contract-test-window",
                "claims": [
                    {
                        "claim_id": "fact-1",
                        "claim_type": "reported_fact",
                        "statement": "这是结构校验文本，不陈述真实市场事实。",
                        "citation_ids": ["source-1"]
                    },
                    {
                        "claim_id": "view-1",
                        "claim_type": "trading_view",
                        "statement": "这是不可执行的结构校验观点。",
                        "citation_ids": ["source-1"]
                    },
                    {
                        "claim_id": "risk-1",
                        "claim_type": "risk",
                        "statement": "缺少独立核验时不得使用。",
                        "citation_ids": ["source-1"]
                    }
                ],
                "citations": [
                    {
                        "citation_id": "source-1",
                        "title": "Longbridge Developers",
                        "url": "https://open.longbridge.com/docs",
                        "published_at": "2026-08-02T08:00:00+08:00",
                        "source_type": "provider_documentation"
                    }
                ],
                "invalidation_conditions": ["本条仅用于合约验收，不得进入真实研究。"],
                "model": {"name": "Synthetic contract probe", "version": "1", "disclosure_state": "synthetic"}
            }
        ]
    }


def build_acceptance_report(root: Path, *, generated_at: str | None = None) -> dict[str, Any]:
    importer = LongbridgeAnalysisImporter(root, generated_at=generated_at)
    policy = importer.policy
    checks: list[dict[str, Any]] = []

    def record(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "passed" if passed else "failed", "detail": detail})

    boundaries = policy.immutable_boundaries
    record("policy_shadow_only", policy.payload.get("mode") == "shadow_reference_only", "接入模式必须为 shadow_reference_only。")
    record("all_effect_boundaries_false", bool(boundaries) and not any(boundaries.values()), "所有交易、账户、自选、用户资产、门禁和晋升权限必须为 false。")

    valid = importer.evaluate_payload(acceptance_probe_payload())
    record("valid_reference_accepted", len(valid["accepted"]) == 1 and not valid["rejected"], "完整、带反证和失效条件的合约样例应进入引用集。")
    accepted = valid["accepted"][0] if valid["accepted"] else {}
    claims = as_list(accepted.get("claims"))
    reported = next((item for item in claims if item.get("claim_type") == "reported_fact"), {})
    trading_view = next((item for item in claims if item.get("claim_type") == "trading_view"), {})
    record("reported_fact_needs_local_verification", reported.get("local_verification_status") == "pending_independent_verification", "长桥声称的事实不能自动成为本地已核验事实。")
    record("trading_view_non_actionable", trading_view.get("action_permitted") is False and trading_view.get("normalized_role") == "provider_view_non_actionable", "长桥交易观点只能作为不可执行外部观点。")

    forbidden_payload = deepcopy(acceptance_probe_payload())
    forbidden_payload["items"][0]["order"] = {"symbol": "TEST.US", "side": "buy"}
    forbidden = importer.evaluate_payload(forbidden_payload)
    record("trade_payload_rejected", len(forbidden["rejected"]) == 1 and not forbidden["accepted"], "任何订单、交易或账户字段必须被拒绝。")

    incomplete_payload = deepcopy(acceptance_probe_payload())
    incomplete_payload["items"][0]["claims"] = [
        item for item in incomplete_payload["items"][0]["claims"] if item["claim_type"] not in {"risk", "counter_view"}
    ]
    incomplete = importer.evaluate_payload(incomplete_payload)
    record("counter_evidence_required", len(incomplete["review_queue"]) == 1 and not incomplete["accepted"], "缺少反证的机构分析只能进入复核队列。")

    public_text = json.dumps(accepted, ensure_ascii=False)
    private_keys = policy.private_keys | policy.forbidden_keys
    record("public_output_has_no_private_keys", not any(f'"{key}"' in public_text for key in private_keys), "公开引用不得包含原始对话、账户、持仓、自选或用户字段。")

    rollout = load_json_or_empty(root / "config/v2-rollout.json")
    record(
        "v1_v2_roles_unchanged",
        as_dict(rollout.get("operation_strategy")).get("v1_role") == "production_primary"
        and as_dict(rollout.get("v2")).get("mode") == "shadow_only"
        and as_dict(rollout.get("v2_2")).get("production_behavior_changed") is False,
        "V1 继续生产主入口，V2/V2.2 继续 shadow。",
    )
    watchlist_policy = load_json_or_empty(root / "config/v2-watchlist-source-policy.json")
    watchlist_sources = set(as_dict(watchlist_policy.get("sources")))
    record("longbridge_not_watchlist_source", not any("longbridge" in item for item in watchlist_sources), "长桥不得注册为同花顺自选的替代来源。")

    status = "passed" if all(item["status"] == "passed" for item in checks) else "failed"
    return {
        "schema_version": 1,
        "status": status,
        "mode": "shadow_reference_only",
        "provider": "Longbridge",
        "policy_version": policy.version,
        "generated_at": generated_at or now_iso(),
        "synthetic_probe_only": True,
        "summary": {"passed": sum(item["status"] == "passed" for item in checks), "failed": sum(item["status"] == "failed" for item in checks)},
        "checks": checks,
        "conclusion": "长桥仅作为可归属、可追溯的外部机构分析引用；未获得交易、自选、账户、用户资产、门禁或模型晋升权限。",
    }

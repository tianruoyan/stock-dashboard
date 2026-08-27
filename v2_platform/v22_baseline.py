from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from v2_platform.publishing import PublishPolicy


SCHEMA_VERSION = 1
DESIGN_DOCUMENTS = (
    "AI投资决策系统V2.2_智能决策层产品设计文档.md",
    "V2.2_股票池体系数据模型与实施方案.md",
    "V2.2_市场环境模型数据模型与实施方案.md",
)
SELF_OUTPUT = "data/v2/v22/baseline-audit.json"


def generated_runtime_artifact(relative: str) -> bool:
    path = Path(relative)
    return "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"} or path.name == ".DS_Store"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_file(path: Path) -> str | None:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError:
        return None


def git_text(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def git_bytes(repo: Path, *args: str) -> bytes | None:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    return proc.stdout if proc.returncode == 0 else None


def changed_paths(repo: Path, protected_paths: Iterable[str], baseline: str) -> list[str]:
    paths = list(protected_paths)
    committed = git_text(repo, "diff", "--name-only", f"{baseline}..HEAD", "--", *paths).splitlines()
    working = git_text(repo, "status", "--porcelain", "--", *paths).splitlines()
    normalized_working = []
    for line in working:
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            normalized_working.append(path)
    return sorted(path for path in set(committed + normalized_working) if not generated_runtime_artifact(path))


def current_files(root: Path, protected_paths: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in protected_paths:
        path = root / relative
        candidates = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file()) if path.is_dir() else []
        for candidate in candidates:
            key = candidate.relative_to(root).as_posix()
            if generated_runtime_artifact(key):
                continue
            digest = sha256_file(candidate)
            if digest:
                result[key] = digest
    return result


def baseline_files(root: Path, protected_paths: Iterable[str], baseline: str) -> dict[str, str]:
    paths = list(protected_paths)
    names = git_text(root, "ls-tree", "-r", "--name-only", baseline, "--", *paths).splitlines()
    result: dict[str, str] = {}
    for name in sorted(set(names)):
        content = git_bytes(root, "show", f"{baseline}:{name}")
        if content is not None:
            result[name] = sha256_bytes(content)
    return result


def v1_fingerprint(rollout: dict[str, Any]) -> dict[str, Any]:
    config = rollout.get("production_v1") if isinstance(rollout.get("production_v1"), dict) else {}
    root = Path(str(config.get("path") or ""))
    baseline = str(config.get("baseline_commit") or "")
    entry = str(config.get("entry") or "index.html")
    protected = [str(item) for item in config.get("protected_paths") or []]
    baseline_full = git_text(root, "rev-parse", baseline) if root.exists() and baseline else ""
    current_head = git_text(root, "rev-parse", "HEAD") if root.exists() else ""
    current_manifest = current_files(root, protected) if root.exists() else {}
    baseline_manifest = baseline_files(root, protected, baseline) if root.exists() and baseline_full else {}
    changed = changed_paths(root, protected, baseline) if root.exists() and baseline_full else ["configuration_or_repository_missing"]
    entry_exists = bool(root.exists() and (root / entry).is_file())
    manifest_equal = bool(current_manifest) and current_manifest == baseline_manifest
    return {
        "path": str(root),
        "entry": entry,
        "entry_exists": entry_exists,
        "baseline_commit": baseline,
        "baseline_commit_full": baseline_full,
        "current_head": current_head,
        "protected_paths": protected,
        "protected_file_count": len(current_manifest),
        "baseline_manifest_hash": sha256_bytes(canonical_json(baseline_manifest)),
        "current_manifest_hash": sha256_bytes(canonical_json(current_manifest)),
        "manifest_equal": manifest_equal,
        "changed_protected_paths": changed,
        "passed": entry_exists and manifest_equal and not changed,
    }


def worktree_state(root: Path) -> dict[str, Any]:
    unstaged = set(git_text(root, "diff", "--name-only").splitlines())
    staged = set(git_text(root, "diff", "--cached", "--name-only").splitlines())
    untracked = set(git_text(root, "ls-files", "--others", "--exclude-standard").splitlines())
    entries = []
    for relative in sorted((unstaged | staged | untracked) - {SELF_OUTPUT}):
        path = root / relative
        if relative in untracked:
            status = "untracked"
        elif relative in staged and relative in unstaged:
            status = "modified_and_staged"
        elif relative in staged:
            status = "staged"
        else:
            status = "modified"
        present = path.is_file()
        entries.append({
            "status": status,
            "path": relative,
            "state": "present" if present else "deleted",
            "size_bytes": path.stat().st_size if present else 0,
            "content_hash": sha256_file(path) if present else sha256_bytes(b"<deleted>"),
        })
    modified_count = sum(item["status"] != "untracked" for item in entries)
    untracked_count = sum(item["status"] == "untracked" for item in entries)
    return {
        "branch": git_text(root, "branch", "--show-current"),
        "head": git_text(root, "rev-parse", "HEAD"),
        "dirty": bool(entries),
        "changed_path_count": len(entries),
        "modified_path_count": modified_count,
        "untracked_path_count": untracked_count,
        "entries": entries,
    }


def source_fingerprints(root: Path, project_root: Path) -> dict[str, Any]:
    paths = {
        "design_documents": [project_root / name for name in DESIGN_DOCUMENTS],
        "data_inputs": [
            root / "config/watchlist.json",
            root / "data/v2/stock-pool.json",
            root / "data/v2/decision-system.json",
        ],
    }
    result: dict[str, Any] = {}
    for group, candidates in paths.items():
        result[group] = [
            {
                "path": str(path.relative_to(project_root) if path.is_relative_to(project_root) else path),
                "exists": path.is_file(),
                "content_hash": sha256_file(path),
            }
            for path in candidates
        ]
    return result


def evidence_counts(root: Path) -> dict[str, Any]:
    replay = load_json(root / "data/v2/replay-index.json")
    review = load_json(root / "data/v2/signal-review.json")
    outcomes = load_json(root / "data/v2/signal-outcomes.json")
    decision = load_json(root / "data/v2/decision-system.json")
    stock_pool = load_json(root / "data/v2/stock-pool.json")
    return {
        "snapshot_files": len(list((root / "data/v2/snapshots").rglob("*.json"))),
        "snapshot_index_count": int(replay.get("snapshot_count") or 0),
        "evaluation_snapshot_count": int(replay.get("evaluation_snapshot_count") or 0),
        "review_raw_snapshot_count": int(review.get("raw_snapshot_count") or 0),
        "review_excluded_variant_count": int(review.get("excluded_variant_count") or 0),
        "pending_signal_count": int(review.get("pending_signal_count") or 0),
        "evaluated_signal_count": int(review.get("evaluated_signal_count") or 0),
        "evaluated_window_count": int(outcomes.get("evaluated_window_count") or 0),
        "outcome_signal_count": len(outcomes.get("signals") or []),
        "radar_count": len(decision.get("opportunity_radar") or []),
        "validation_queue_count": len(decision.get("validation_queue") or []),
        "stock_pool_count": int(stock_pool.get("stock_count") or 0),
    }


def all_false(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(item is False for item in value.values())


def feature_scope_matches_stage(stage: str, value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    enabled = {str(key) for key, enabled in value.items() if enabled is True}
    if stage == "E0_baseline_freeze":
        return not enabled
    if stage == "E1_private_user_asset_foundation":
        return enabled == {"user_asset_store"}
    if stage == "E2_ths_shadow_and_migration_review":
        return enabled == {"user_asset_store", "ths_shadow_sync"}
    if stage == "E3_stock_pool_layers_shadow":
        return enabled == {"user_asset_store", "ths_shadow_sync", "stock_pool_projection"}
    if stage == "E4_market_environment_facts_shadow":
        return enabled == {"user_asset_store", "ths_shadow_sync", "stock_pool_projection", "market_environment"}
    if stage == "E5_environment_state_style_cross_market_g5_shadow":
        return enabled == {
            "user_asset_store", "ths_shadow_sync", "stock_pool_projection", "market_environment",
            "style_and_cross_market_mapping", "environment_state_machine", "g5_environment_gate",
        }
    if stage == "E6_decision_cases_g0_g7_shadow":
        return enabled == {
            "user_asset_store", "ths_shadow_sync", "stock_pool_projection", "market_environment",
            "style_and_cross_market_mapping", "environment_state_machine", "g5_environment_gate",
            "decision_cases", "page_projection",
        }
    if stage == "E7_replay_learning_parallel_acceptance_shadow":
        return enabled == {
            "user_asset_store", "ths_shadow_sync", "stock_pool_projection", "market_environment",
            "style_and_cross_market_mapping", "environment_state_machine", "g5_environment_gate",
            "decision_cases", "page_projection", "replay_learning", "candidate_model_evaluation",
        }
    if stage == "S1_shadow_trigger_quote_and_replay_closure":
        return enabled == {
            "user_asset_store", "ths_shadow_sync", "stock_pool_projection", "market_environment",
            "style_and_cross_market_mapping", "environment_state_machine", "g5_environment_gate",
            "decision_cases", "page_projection", "replay_learning", "candidate_model_evaluation",
            "time_semantics_gate", "trigger_quote_capture", "outcome_price_backfill",
        }
    if stage == "S2_intraday_shadow_capture_and_current_facts":
        return enabled == {
            "user_asset_store", "ths_shadow_sync", "stock_pool_projection", "market_environment",
            "style_and_cross_market_mapping", "environment_state_machine", "g5_environment_gate",
            "decision_cases", "page_projection", "replay_learning", "candidate_model_evaluation",
            "time_semantics_gate", "trigger_quote_capture", "outcome_price_backfill",
            "market_fact_refresh", "intraday_shadow_checkpoints",
        }
    return False


class V22BaselineBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.project_root = self.root.parent.parent

    def build(self) -> dict[str, Any]:
        rollout = load_json(self.root / "config/v2-rollout.json")
        flags = load_json(self.root / "config/v2-v22-feature-flags.json")
        registry = load_json(self.root / "config/v2-model-registry.json")
        policy = PublishPolicy.load(self.root / "config/v2-publish-policy.json")
        v1 = v1_fingerprint(rollout)
        registered = [
            item for item in registry.get("registered_candidates") or []
            if isinstance(item, dict) and item.get("version") == "decision-v2.2-shadow"
        ]
        v22_rollout = rollout.get("v2_2") if isinstance(rollout.get("v2_2"), dict) else {}
        stage = str(v22_rollout.get("stage") or "")
        operation = rollout.get("operation_strategy") if isinstance(rollout.get("operation_strategy"), dict) else {}
        checks = [
            self._check("v1_protected_fingerprint", bool(v1.get("passed")), "V1受保护文件与冻结提交一致。"),
            self._check("v1_production_primary", operation.get("v1_role") == "production_primary", "V1继续作为生产主入口。"),
            self._check("v2_shadow_only", (rollout.get("v2") or {}).get("mode") == "shadow_only", "V2继续以影子模式运行。"),
            self._check("v22_stage_shadow_only", stage in {"E0_baseline_freeze", "E1_private_user_asset_foundation", "E2_ths_shadow_and_migration_review", "E3_stock_pool_layers_shadow", "E4_market_environment_facts_shadow", "E5_environment_state_style_cross_market_g5_shadow", "E6_decision_cases_g0_g7_shadow", "E7_replay_learning_parallel_acceptance_shadow", "S1_shadow_trigger_quote_and_replay_closure", "S2_intraday_shadow_capture_and_current_facts"} and v22_rollout.get("mode") == "shadow_only" and v22_rollout.get("production_behavior_changed") is False, "V2.2阶段推进不改变生产行为。"),
            self._check("v22_feature_scope", feature_scope_matches_stage(stage, flags.get("features")), "只有当前阶段获准的基础能力可以开启。"),
            self._check("immutable_boundaries", all_false(flags.get("immutable_boundaries")), "自动交易、用户资产修改、模型晋升和V1停用均关闭。"),
            self._check("candidate_registered_offline_only", len(registered) == 1 and registered[0].get("status") == "offline_shadow_evaluation" and registered[0].get("evaluation_enabled") is True and registered[0].get("automatic_promotion") is False and not registry.get("candidates"), "V2.2候选只进入离线影子评价，不进入生产候选。"),
            self._check("automatic_model_promotion_disabled", (registry.get("promotion_policy") or {}).get("automatic_live_promotion") is False, "模型不得自动晋升。"),
            self._check("private_paths_hard_blocked", policy.hard_blocks_path(".v2_private/user-assets.sqlite3") and policy.hard_blocks_path("data/v2/raw-sync/ths.json"), "私有域和同步原始数据受发布硬阻断。"),
            self._check("sensitive_keys_hard_blocked", {"user_note", "account_id"}.issubset(set(policy.sensitive_json_keys)), "用户备注与账号标识受发布内容阻断。"),
        ]
        fingerprints = source_fingerprints(self.root, self.project_root)
        stable_identity = {
            "v2_head": git_text(self.root, "rev-parse", "HEAD"),
            "v1_manifest_hash": v1.get("current_manifest_hash"),
            "source_hashes": fingerprints,
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "baseline_id": f"v22_e0_{sha256_bytes(canonical_json(stable_identity)).split(':', 1)[1][:20]}",
            "generated_at": now_iso(),
            "stage": stage,
            "status": "passed" if all(item["passed"] for item in checks) else "failed",
            "scope": {
                "business_data_migrated": False,
                "user_asset_values_read": False,
                "user_assets_modified": False,
                "ths_sync_modified": False,
                "stock_pool_modified": False,
                "page_logic_modified": False,
                "production_automation_tasks_modified": False,
                "shadow_automation_task_added": stage == "S2_intraday_shadow_capture_and_current_facts",
                "shadow_page_projection_modified": stage in {"E3_stock_pool_layers_shadow", "E4_market_environment_facts_shadow", "E5_environment_state_style_cross_market_g5_shadow", "E6_decision_cases_g0_g7_shadow", "E7_replay_learning_parallel_acceptance_shadow", "S1_shadow_trigger_quote_and_replay_closure", "S2_intraday_shadow_capture_and_current_facts"},
                "shadow_market_environment_generated": stage in {"E4_market_environment_facts_shadow", "E5_environment_state_style_cross_market_g5_shadow", "E6_decision_cases_g0_g7_shadow", "E7_replay_learning_parallel_acceptance_shadow", "S1_shadow_trigger_quote_and_replay_closure", "S2_intraday_shadow_capture_and_current_facts"},
                "shadow_environment_decision_generated": stage in {"E5_environment_state_style_cross_market_g5_shadow", "E6_decision_cases_g0_g7_shadow", "E7_replay_learning_parallel_acceptance_shadow", "S1_shadow_trigger_quote_and_replay_closure", "S2_intraday_shadow_capture_and_current_facts"},
                "shadow_decision_cases_generated": stage in {"E6_decision_cases_g0_g7_shadow", "E7_replay_learning_parallel_acceptance_shadow", "S1_shadow_trigger_quote_and_replay_closure", "S2_intraday_shadow_capture_and_current_facts"},
            },
            "worktree": worktree_state(self.root),
            "v1_fingerprint": v1,
            "source_fingerprints": fingerprints,
            "evidence_counts": evidence_counts(self.root),
            "private_domain": {
                "exists": (self.root / ".v2_private").exists(),
                "values_read": False,
                "publish_hard_blocked": policy.hard_blocks_path(".v2_private/user-assets.sqlite3"),
            },
            "checks": checks,
        }

    def write(self, path: Path | None = None) -> dict[str, Any]:
        payload = self.build()
        output = path or self.root / SELF_OUTPUT
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload

    @staticmethod
    def _check(check_id: str, passed: bool, detail: str) -> dict[str, Any]:
        return {"id": check_id, "passed": bool(passed), "detail": detail}

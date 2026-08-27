from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from v2_platform.publishing import PublishPolicy, V2Publisher
from v2_platform.v22_baseline import DESIGN_DOCUMENTS, V22BaselineBuilder, generated_runtime_artifact


ROOT = Path(__file__).resolve().parents[1]


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return proc.stdout.strip()


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / "data/v2/raw-sync").mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "V2 Test")
    (repo / "data/base.json").write_text('{"value":1}\n', encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    return repo


def guarded_policy() -> PublishPolicy:
    return PublishPolicy(
        name="guarded",
        version="e0-test",
        include_globs=("data/*.json", "data/**/*.json"),
        exclude_globs=(),
        target_remote="origin",
        target_branch="main",
        max_push_attempts=1,
        deny_globs=(".v2_private/**", "data/v2/raw-sync/**"),
        sensitive_json_keys=("user_note", "account_id"),
    )


class V22E0ConfigTests(unittest.TestCase):
    def test_rollout_keeps_v1_production_and_v2_shadow(self) -> None:
        rollout = json.loads((ROOT / "config/v2-rollout.json").read_text(encoding="utf-8"))
        self.assertEqual(rollout["operation_strategy"]["v1_role"], "production_primary")
        self.assertEqual(rollout["v2"]["mode"], "shadow_only")
        self.assertEqual(rollout["v2_2"]["stage"], "S2_intraday_shadow_capture_and_current_facts")
        self.assertEqual(rollout["v2_2"]["mode"], "shadow_only")
        self.assertFalse(rollout["v2_2"]["production_behavior_changed"])
        self.assertFalse(rollout["v2_2"]["user_asset_write_api_enabled"])
        self.assertFalse(rollout["v2_2"]["real_user_asset_imported"])
        self.assertFalse(rollout["v2_2"]["ths_shadow_task_installed"])
        self.assertFalse(rollout["v2_2"]["watchlist_migration_apply_enabled"])

    def test_only_s2_v22_shadow_features_are_enabled(self) -> None:
        flags = json.loads((ROOT / "config/v2-v22-feature-flags.json").read_text(encoding="utf-8"))
        enabled = {key for key, value in flags["features"].items() if value is True}
        self.assertEqual(enabled, {
            "user_asset_store", "ths_shadow_sync", "stock_pool_projection", "market_environment",
            "style_and_cross_market_mapping", "environment_state_machine", "g5_environment_gate",
            "decision_cases", "page_projection",
            "replay_learning", "candidate_model_evaluation",
            "time_semantics_gate", "trigger_quote_capture", "outcome_price_backfill",
            "market_fact_refresh", "intraday_shadow_checkpoints",
        })
        self.assertTrue(flags["immutable_boundaries"])
        self.assertTrue(all(value is False for value in flags["immutable_boundaries"].values()))

    def test_v22_candidate_is_registered_but_not_evaluated_or_promoted(self) -> None:
        registry = json.loads((ROOT / "config/v2-model-registry.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["baseline"]["version"], "decision-v2.0-baseline-1")
        self.assertEqual(registry["baseline"]["status"], "active_shadow")
        self.assertEqual(registry["candidates"], [])
        candidate = next(item for item in registry["registered_candidates"] if item["version"] == "decision-v2.2-shadow")
        self.assertEqual(candidate["status"], "offline_shadow_evaluation")
        self.assertTrue(candidate["evaluation_enabled"])
        self.assertFalse(candidate["automatic_promotion"])
        self.assertFalse(registry["promotion_policy"]["automatic_live_promotion"])


class V22E0PublishingTests(unittest.TestCase):
    def test_workspace_policy_hard_blocks_private_and_raw_sync_paths(self) -> None:
        policy = PublishPolicy.load(ROOT / "config/v2-publish-policy.json")
        self.assertTrue(policy.hard_blocks_path(".v2_private/user-assets.sqlite3"))
        self.assertTrue(policy.hard_blocks_path("data/v2/raw-sync/ths.json"))
        self.assertFalse(policy.allows(".v2_private/user-assets.sqlite3"))
        self.assertFalse(policy.allows("data/v2/raw-sync/ths.json"))

    def test_sensitive_user_note_blocks_publish_even_under_included_path(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            (repo / "data/public.json").write_text('{"user_note":"private"}\n', encoding="utf-8")
            publisher = V2Publisher(repo, guarded_policy(), ledger_path=root / "ledger.jsonl", lock_path=root / "publisher.lock")
            result = publisher.run(mode="shadow")
            self.assertEqual(result.state, "blocked_sensitive_scope")
            self.assertEqual(result.scope.hard_blocked_paths, ("data/public.json",))
            self.assertEqual(git(repo, "diff", "--cached", "--name-only"), "")

    def test_raw_sync_path_blocks_publish_without_staging(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            (repo / "data/v2/raw-sync/ths.json").write_text('{"items":[]}\n', encoding="utf-8")
            publisher = V2Publisher(repo, guarded_policy(), ledger_path=root / "ledger.jsonl", lock_path=root / "publisher.lock")
            result = publisher.run(mode="shadow")
            self.assertEqual(result.state, "blocked_sensitive_scope")
            self.assertEqual(result.scope.hard_blocked_paths, ("data/v2/raw-sync/ths.json",))
            self.assertEqual(git(repo, "diff", "--cached", "--name-only"), "")

    def test_sensitive_key_in_non_publishable_config_does_not_block_public_data(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            (repo / "config").mkdir()
            (repo / "config/rollout.json").write_text('{"user_note":"local metadata"}\n', encoding="utf-8")
            (repo / "data/public.json").write_text('{"value":2}\n', encoding="utf-8")
            publisher = V2Publisher(repo, guarded_policy(), ledger_path=root / "ledger.jsonl", lock_path=root / "publisher.lock")
            result = publisher.run(mode="shadow")
            self.assertEqual(result.state, "shadow_ready")
            self.assertEqual(result.scope.hard_blocked_paths, ())
            self.assertIn("config/rollout.json", result.scope.blocked_paths)
            self.assertIn("data/public.json", result.scope.allowed_paths)
            self.assertEqual(git(repo, "diff", "--cached", "--name-only"), "")


class V22E0BaselineTests(unittest.TestCase):
    def test_v1_fingerprint_ignores_generated_python_cache(self) -> None:
        self.assertTrue(generated_runtime_artifact("scripts/__pycache__/worker.cpython-312.pyc"))
        self.assertFalse(generated_runtime_artifact("scripts/worker.py"))

    def test_baseline_passes_and_v1_fingerprint_matches(self) -> None:
        report = V22BaselineBuilder(ROOT).build()
        rollout = json.loads((ROOT / "config/v2-rollout.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            report["v1_fingerprint"]["baseline_commit"],
            rollout["production_v1"]["baseline_commit"],
        )
        self.assertTrue(report["v1_fingerprint"]["entry_exists"])
        self.assertTrue(report["v1_fingerprint"]["manifest_equal"])
        self.assertEqual(report["v1_fingerprint"]["changed_protected_paths"], [])

    def test_design_documents_are_present_and_hashed(self) -> None:
        report = V22BaselineBuilder(ROOT).build()
        documents = report["source_fingerprints"]["design_documents"]
        self.assertEqual(len(documents), len(DESIGN_DOCUMENTS))
        self.assertTrue(all(item["exists"] and str(item["content_hash"]).startswith("sha256:") for item in documents))

    def test_every_dirty_worktree_file_is_frozen_with_a_hash(self) -> None:
        report = V22BaselineBuilder(ROOT).build()
        entries = report["worktree"]["entries"]
        self.assertTrue(entries)
        self.assertTrue(all(item["path"] and str(item["content_hash"]).startswith("sha256:") for item in entries))
        self.assertNotIn("data/v2/v22/baseline-audit.json", {item["path"] for item in entries})

    def test_check_mode_does_not_modify_business_inputs(self) -> None:
        protected = [
            ROOT / "config/watchlist.json",
            ROOT / "data/v2/stock-pool.json",
            ROOT / "data/v2/decision-system.json",
        ]
        before = {str(path): file_hash(path) for path in protected}
        proc = subprocess.run(
            [sys.executable, "scripts/audit_v22_baseline.py", "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        after = {str(path): file_hash(path) for path in protected}
        self.assertEqual(after, before)

    def test_private_domain_is_only_checked_for_existence(self) -> None:
        report = V22BaselineBuilder(ROOT).build()
        self.assertFalse(report["scope"]["user_asset_values_read"])
        self.assertFalse(report["scope"]["user_assets_modified"])
        self.assertFalse(report["private_domain"]["values_read"])
        self.assertTrue(report["private_domain"]["publish_hard_blocked"])


if __name__ == "__main__":
    unittest.main()

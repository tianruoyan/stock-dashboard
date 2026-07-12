from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from v2_platform.publishing import PublishPolicy, V2Publisher


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return proc.stdout.strip()


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "V2 Test")
    (repo / "data").mkdir()
    (repo / "scripts").mkdir()
    (repo / "data" / "market.json").write_text('{"value":1}\n', encoding="utf-8")
    (repo / "scripts" / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / ".gitignore").write_text("logs/\n.v2-publish.lock\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    return repo


def policy() -> PublishPolicy:
    return PublishPolicy(
        name="generated-data",
        version="test-1",
        include_globs=("data/*.json", "data/**/*.json"),
        exclude_globs=("data/**/*.tmp",),
        target_remote="origin",
        target_branch="main",
        max_push_attempts=2,
    )


def publisher(repo: Path, root: Path) -> V2Publisher:
    return V2Publisher(
        repo,
        policy(),
        ledger_path=root / "audit" / "ledger.jsonl",
        lock_path=root / "audit" / "publisher.lock",
    )


class PublishPolicyTests(unittest.TestCase):
    def test_policy_allows_only_generated_data(self) -> None:
        value = policy()
        self.assertTrue(value.allows("data/market.json"))
        self.assertTrue(value.allows("data/archive/market.json"))
        self.assertFalse(value.allows("scripts/tool.py"))
        self.assertFalse(value.allows("data/archive/file.tmp"))


class V2PublisherTests(unittest.TestCase):
    def test_shadow_mode_freezes_artifact_without_git_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            (repo / "data" / "market.json").write_text('{"value":2}\n', encoding="utf-8")
            before = git(repo, "rev-parse", "HEAD")
            result = publisher(repo, root).run(mode="shadow")
            self.assertEqual(result.state, "shadow_ready")
            self.assertIsNotNone(result.artifact)
            self.assertEqual(git(repo, "rev-parse", "HEAD"), before)
            self.assertEqual(git(repo, "diff", "--cached", "--name-only"), "")

    def test_artifact_identity_is_stable_without_regeneration(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            (repo / "data" / "market.json").write_text('{"value":2}\n', encoding="utf-8")
            one = publisher(repo, root).run(mode="shadow").artifact
            two = publisher(repo, root).run(mode="shadow").artifact
            self.assertEqual(one.artifact_id, two.artifact_id)
            self.assertEqual(one.generation_key, two.generation_key)

    def test_commit_includes_data_but_leaves_source_change_unstaged(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            (repo / "data" / "market.json").write_text('{"value":2}\n', encoding="utf-8")
            (repo / "scripts" / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
            result = publisher(repo, root).run(mode="commit")
            self.assertEqual(result.state, "committed")
            committed = git(repo, "show", "--pretty=format:", "--name-only", "HEAD").splitlines()
            self.assertEqual(committed, ["data/market.json"])
            status = git(repo, "status", "--short")
            self.assertIn("scripts/tool.py", status)
            self.assertNotIn("data/market.json", status)

    def test_pre_staged_changes_block_automated_commit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            (repo / "data" / "market.json").write_text('{"value":2}\n', encoding="utf-8")
            git(repo, "add", "data/market.json")
            before = git(repo, "rev-parse", "HEAD")
            result = publisher(repo, root).run(mode="commit")
            self.assertEqual(result.state, "blocked_pre_staged")
            self.assertEqual(git(repo, "rev-parse", "HEAD"), before)

    def test_only_source_changes_produce_scope_warning(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            (repo / "scripts" / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
            result = publisher(repo, root).run(mode="commit")
            self.assertEqual(result.state, "scope_warning")
            self.assertEqual(result.scope.allowed_paths, ())
            self.assertEqual(result.scope.blocked_paths, ("scripts/tool.py",))

    def test_no_changes_do_not_create_commit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            before = git(repo, "rev-parse", "HEAD")
            result = publisher(repo, root).run(mode="commit")
            self.assertEqual(result.state, "no_change")
            self.assertEqual(git(repo, "rev-parse", "HEAD"), before)

    def test_build_runs_once_and_artifact_uses_built_content(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            counter = root / "counter.txt"
            code = (
                "from pathlib import Path; "
                f"c=Path({str(counter)!r}); "
                "n=int(c.read_text()) if c.exists() else 0; c.write_text(str(n+1)); "
                "Path('data/market.json').write_text('{\"value\":2}\\n')"
            )
            result = publisher(repo, root).run(mode="shadow", build_command=[sys.executable, "-c", code])
            self.assertEqual(result.state, "shadow_ready")
            self.assertEqual(counter.read_text(), "1")
            self.assertEqual(result.build["returncode"], 0)

    def test_failed_build_stages_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            result = publisher(repo, root).run(
                mode="commit", build_command=[sys.executable, "-c", "raise SystemExit(7)"]
            )
            self.assertEqual(result.state, "build_failed")
            self.assertEqual(git(repo, "diff", "--cached", "--name-only"), "")


if __name__ == "__main__":
    unittest.main()

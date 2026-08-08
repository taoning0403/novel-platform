"""Git reference and change-routing regression tests for the verifier."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from repository_changes import changed_files
from repository_snapshot import comparison_revision


def git_command(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def initialized_repository(root: Path) -> None:
    git_command(root, "init", "--quiet")
    git_command(root, "config", "user.email", "verification@example.invalid")
    git_command(root, "config", "user.name", "Verification Selftest")


def commit_file(root: Path, relative: str, content: str, message: str) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git_command(root, "add", relative)
    git_command(root, "commit", "--quiet", "-m", message)
    return git_command(root, "rev-parse", "HEAD")


def set_tracking_upstream(root: Path) -> None:
    branch = git_command(root, "branch", "--show-current")
    git_command(root, "update-ref", f"refs/remotes/origin/{branch}", "HEAD")
    git_command(root, "config", f"branch.{branch}.remote", "origin")
    git_command(root, "config", f"branch.{branch}.merge", f"refs/heads/{branch}")


def write_push_event(root: Path, commits: list[str], size: int | None = None) -> Path:
    event = root / "event.json"
    event.write_text(
        json.dumps(
            {
                "before": "0" * 40,
                "after": commits[-1],
                "size": len(commits) if size is None else size,
                "commits": [{"id": commit} for commit in commits],
            }
        ),
        encoding="utf-8",
    )
    return event


class GitRoutingTests(unittest.TestCase):
    def test_deleted_worktree_file_is_routed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            commit_file(root, "apps/server/deleted.py", "VALUE = 1\n", "initial")
            set_tracking_upstream(root)
            (root / "apps/server/deleted.py").unlink()
            paths, _reference = changed_files(root, None, {})
        self.assertIn("apps/server/deleted.py", paths)

    def test_github_event_before_is_trusted_push_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            before = commit_file(root, "one.txt", "one\n", "one")
            commit_file(root, "two.txt", "two\n", "two")
            event = root / "event.json"
            event.write_text(json.dumps({"before": before}), encoding="utf-8")
            actual = comparison_revision(
                root,
                None,
                {"GITHUB_EVENT_PATH": str(event)},
            )
        self.assertEqual(before, actual)

    def test_clean_committed_change_uses_parent_as_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            parent = commit_file(root, "one.txt", "one\n", "one")
            set_tracking_upstream(root)
            commit_file(root, "two.txt", "two\n", "two")
            paths, reference = changed_files(root, None, {})
        self.assertEqual(parent, reference)
        self.assertIn("two.txt", paths)

    def test_zero_before_new_branch_uses_oldest_pushed_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            parent = commit_file(root, "one.txt", "one\n", "one")
            head = commit_file(root, "two.txt", "two\n", "two")
            event = write_push_event(root, [head])
            actual = comparison_revision(
                root,
                None,
                {
                    "GITHUB_EVENT_NAME": "push",
                    "GITHUB_EVENT_PATH": str(event),
                },
            )
        self.assertEqual(parent, actual)

    def test_multi_commit_zero_before_uses_pre_push_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            base = commit_file(root, "base.txt", "base\n", "base")
            first = commit_file(root, "one.txt", "one\n", "one")
            head = commit_file(root, "two.txt", "two\n", "two")
            event = write_push_event(root, [first, head])
            actual = comparison_revision(
                root,
                None,
                {
                    "GITHUB_EVENT_NAME": "push",
                    "GITHUB_EVENT_PATH": str(event),
                },
            )
        self.assertEqual(base, actual)

    def test_truncated_zero_before_event_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            commit_file(root, "base.txt", "base\n", "base")
            head = commit_file(root, "one.txt", "one\n", "one")
            event = write_push_event(root, [head], size=2)
            with self.assertRaises(RuntimeError):
                comparison_revision(
                    root,
                    None,
                    {
                        "GITHUB_EVENT_NAME": "push",
                        "GITHUB_EVENT_PATH": str(event),
                    },
                )

    def test_initial_commit_without_base_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            head = commit_file(root, "one.txt", "one\n", "one")
            with self.assertRaises(RuntimeError):
                comparison_revision(root, None, {})
            event = write_push_event(root, [head])
            environments = (
                {"GITHUB_EVENT_BEFORE": "0" * 40},
                {
                    "GITHUB_EVENT_NAME": "push",
                    "GITHUB_EVENT_PATH": str(event),
                },
            )
            for environment in environments:
                with self.subTest(environment=environment):
                    with self.assertRaises(RuntimeError):
                        comparison_revision(root, None, environment)

    def test_clean_worktree_without_upstream_requires_explicit_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            commit_file(root, "one.txt", "one\n", "one")
            commit_file(root, "two.txt", "two\n", "two")
            with self.assertRaises(RuntimeError):
                comparison_revision(root, None, {})

    def test_dirty_worktree_uses_head_as_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            head = commit_file(root, "one.txt", "one\n", "one")
            set_tracking_upstream(root)
            (root / "one.txt").write_text("changed\n", encoding="utf-8")
            actual = comparison_revision(root, None, {})
        self.assertEqual(head, actual)

    def test_dirty_ahead_worktree_routes_committed_and_uncommitted_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            base = commit_file(root, "base.txt", "base\n", "base")
            set_tracking_upstream(root)
            commit_file(root, "apps/server/committed.py", "VALUE = 1\n", "committed")
            dirty = root / "apps/web/dirty.ts"
            dirty.parent.mkdir(parents=True)
            dirty.write_text("export const value = 1\n", encoding="utf-8")
            paths, reference = changed_files(root, None, {})
        self.assertEqual(base, reference)
        self.assertIn("apps/server/committed.py", paths)
        self.assertIn("apps/web/dirty.ts", paths)

    def test_dirty_worktree_without_upstream_requires_explicit_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            commit_file(root, "one.txt", "one\n", "one")
            (root / "one.txt").write_text("changed\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                comparison_revision(root, None, {})

    def test_new_branch_event_must_match_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            base = commit_file(root, "base.txt", "base\n", "base")
            head = commit_file(root, "one.txt", "one\n", "one")
            event = write_push_event(root, [head])
            payload = json.loads(event.read_text(encoding="utf-8"))
            payload["after"] = base
            event.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                comparison_revision(
                    root,
                    None,
                    {
                        "GITHUB_EVENT_NAME": "push",
                        "GITHUB_EVENT_PATH": str(event),
                    },
                )

    def test_untracked_path_with_newline_is_not_split(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            commit_file(root, "base.txt", "base\n", "base")
            set_tracking_upstream(root)
            relative = "apps/server/line\nbreak.py"
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text("VALUE = 1\n", encoding="utf-8")
            paths, _reference = changed_files(root, None, {})
        self.assertIn(relative, paths)

    def test_committed_cross_surface_rename_routes_both_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            commit_file(root, "apps/server/sample.py", "VALUE = 1\n", "one")
            set_tracking_upstream(root)
            (root / "apps/web").mkdir(parents=True)
            git_command(root, "mv", "apps/server/sample.py", "apps/web/sample.ts")
            git_command(root, "commit", "--quiet", "-m", "rename")
            paths, _reference = changed_files(root, None, {})
        self.assertIn("apps/server/sample.py", paths)
        self.assertIn("apps/web/sample.ts", paths)

    def test_worktree_cross_surface_rename_routes_both_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialized_repository(root)
            commit_file(root, "apps/server/sample.py", "VALUE = 1\n", "one")
            set_tracking_upstream(root)
            (root / "apps/web").mkdir(parents=True)
            git_command(root, "mv", "apps/server/sample.py", "apps/web/sample.ts")
            paths, _reference = changed_files(root, None, {})
        self.assertIn("apps/server/sample.py", paths)
        self.assertIn("apps/web/sample.ts", paths)

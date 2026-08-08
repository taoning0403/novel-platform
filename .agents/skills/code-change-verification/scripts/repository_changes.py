"""Resolve change paths, including deleted files, against the trusted revision."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from repository_snapshot import commit_sha, comparison_revision, git_result


def decoded_path(value: bytes) -> str:
    return value.decode("utf-8", errors="surrogateescape").replace("\\", "/")


def parsed_change_paths(output: bytes) -> list[str]:
    fields = [field for field in output.split(b"\0") if field]
    paths: list[str] = []
    index = 0
    while index < len(fields):
        status = fields[index].decode("ascii", errors="replace")
        index += 1
        path_count = 2 if status.startswith(("R", "C")) else 1
        if index + path_count > len(fields):
            raise RuntimeError("git returned malformed name-status output")
        paths.extend(decoded_path(value) for value in fields[index : index + path_count])
        index += path_count
    return paths


def diff_change_paths(root: Path, arguments: list[str]) -> list[str]:
    result = git_result(
        root,
        [
            "diff",
            "--name-status",
            "-z",
            "-M",
            "-C",
            "--find-copies-harder",
            *arguments,
        ],
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or "git diff --name-status failed")
    return parsed_change_paths(result.stdout)


def changed_files(
    root: Path,
    explicit_base: str | None,
    environment: Mapping[str, str] | None = None,
) -> tuple[list[str], str]:
    reference = comparison_revision(root, explicit_base, environment)
    changed = set(commit_changes(root, reference))
    changed.update(worktree_changes(root))
    return sorted(changed), commit_sha(root, reference)


def commit_changes(root: Path, reference: str) -> list[str]:
    head = commit_sha(root, "HEAD")
    if reference == head:
        return []
    return diff_change_paths(root, [f"{reference}..HEAD"])


def worktree_changes(root: Path) -> list[str]:
    changed = diff_change_paths(root, ["HEAD"])
    untracked = git_result(
        root,
        ["ls-files", "--others", "--exclude-standard", "-z"],
    )
    if untracked.returncode == 0:
        changed.extend(decoded_path(value) for value in untracked.stdout.split(b"\0") if value)
    return changed

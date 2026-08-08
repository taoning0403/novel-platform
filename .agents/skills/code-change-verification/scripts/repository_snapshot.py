"""Read current and committed repository source snapshots through Git."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping
from itertools import pairwise
from pathlib import Path

COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
IGNORED_PARTS = {".git", ".venv", "node_modules", "dist", "__pycache__"}


def repository_root(start: Path) -> Path:
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "apps/server/pyproject.toml").is_file() and (
            candidate / "apps/web/package.json"
        ).is_file():
            return candidate
    raise ValueError("could not locate novel-platform repository root")


def git_result(
    root: Path, arguments: list[str], *, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def git_text(root: Path, arguments: list[str]) -> str:
    result = git_result(root, arguments)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"git {' '.join(arguments)} failed")
    return result.stdout.decode("utf-8")


def valid_revision(root: Path, revision: str) -> bool:
    return (
        git_result(root, ["rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"]).returncode
        == 0
    )


def commit_sha(root: Path, revision: str) -> str:
    value = git_text(root, ["rev-parse", f"{revision}^{{commit}}"]).strip()
    if not COMMIT_PATTERN.fullmatch(value):
        raise RuntimeError(f"Git returned an invalid commit for {revision}")
    return value.lower()


def commit_date(root: Path, revision: str) -> str:
    value = git_text(root, ["show", "-s", "--format=%cI", revision]).strip()
    if not value:
        raise RuntimeError(f"Git returned no commit date for {revision}")
    return value


def merge_base(root: Path, revision: str) -> str:
    if not valid_revision(root, revision):
        raise RuntimeError(f"base revision does not exist: {revision}")
    value = git_text(root, ["merge-base", "HEAD", revision]).strip()
    return commit_sha(root, value or revision)


def is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = git_result(root, ["merge-base", "--is-ancestor", ancestor, descendant])
    if result.returncode in {0, 1}:
        return result.returncode == 0
    detail = result.stderr.decode("utf-8", errors="replace").strip()
    raise RuntimeError(detail or "could not compare Git commit ancestry")


def github_event_payload(environment: Mapping[str, str]) -> dict[str, object] | None:
    event_path = environment.get("GITHUB_EVENT_PATH")
    if not event_path:
        return None
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def github_before_value(environment: Mapping[str, str]) -> object | None:
    if "GITHUB_EVENT_BEFORE" in environment:
        return environment.get("GITHUB_EVENT_BEFORE")
    payload = github_event_payload(environment)
    return payload.get("before") if payload is not None else None


def usable_before(root: Path, value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(COMMIT_PATTERN.fullmatch(value))
        and set(value) != {"0"}
        and valid_revision(root, value)
    )


def zero_before(value: object) -> bool:
    return isinstance(value, str) and bool(COMMIT_PATTERN.fullmatch(value)) and set(value) == {"0"}


def complete_push_commits(payload: dict[str, object]) -> list[object]:
    commits = payload.get("commits")
    size = payload.get("size")
    if not isinstance(commits, list) or not commits:
        raise RuntimeError("new-branch push commit list is missing; provide --base")
    if not isinstance(size, int) or size != len(commits):
        raise RuntimeError("new-branch push commit list is truncated; provide --base")
    return commits


def pushed_commit_id(entry: object) -> str:
    commit_id = entry.get("id") if isinstance(entry, dict) else None
    if not isinstance(commit_id, str) or not COMMIT_PATTERN.fullmatch(commit_id):
        raise RuntimeError("new-branch push contains an invalid commit; provide --base")
    return commit_id.lower()


def pushed_commit_parent(root: Path, commit_id: str) -> str:
    if not valid_revision(root, commit_id):
        raise RuntimeError("new-branch pushed commit is unavailable; provide --base")
    parent = f"{commit_id}^"
    if not valid_revision(root, parent):
        raise RuntimeError("new-branch push parent cannot be proven; provide --base")
    return commit_sha(root, parent)


def pushed_head(root: Path, payload: dict[str, object], commits: list[str]) -> str:
    after = payload.get("after")
    if not isinstance(after, str) or not COMMIT_PATTERN.fullmatch(after):
        raise RuntimeError("new-branch push has no valid after revision; provide --base")
    head = commit_sha(root, "HEAD")
    if after.lower() != head or commits[-1] != head:
        raise RuntimeError("new-branch push event does not match HEAD; provide --base")
    return head


def validate_pushed_history(root: Path, commits: list[str], head: str) -> str:
    if len(commits) != len(set(commits)):
        raise RuntimeError("new-branch push contains duplicate commits; provide --base")
    for commit in commits:
        if not valid_revision(root, commit) or not is_ancestor(root, commit, head):
            raise RuntimeError("new-branch pushed commit is not in HEAD history; provide --base")
    for previous, current in pairwise(commits):
        if not is_ancestor(root, previous, current):
            raise RuntimeError("new-branch push commit sequence is inconsistent; provide --base")
    parent = pushed_commit_parent(root, commits[0])
    if not is_ancestor(root, parent, head):
        raise RuntimeError("new-branch push parent is not in HEAD history; provide --base")
    return parent


def new_branch_push_revision(
    root: Path,
    environment: Mapping[str, str],
) -> str:
    payload = github_event_payload(environment)
    if payload is None:
        raise RuntimeError("new-branch push has no complete event payload; provide --base")
    commits = [pushed_commit_id(entry) for entry in complete_push_commits(payload)]
    return validate_pushed_history(root, commits, pushed_head(root, payload, commits))


def github_push_revision(
    root: Path,
    environment: Mapping[str, str],
) -> str | None:
    before = github_before_value(environment)
    is_push = environment.get("GITHUB_EVENT_NAME") == "push" or before is not None
    if not is_push:
        return None
    if zero_before(before):
        return new_branch_push_revision(root, environment)
    if usable_before(root, before):
        return commit_sha(root, str(before))
    raise RuntimeError("GitHub push event has no valid before revision")


def local_tracking_revision(root: Path) -> str:
    branch = git_text(root, ["symbolic-ref", "--quiet", "--short", "HEAD"]).strip()
    remote_result = git_result(root, ["config", "--get", f"branch.{branch}.remote"])
    merge_result = git_result(root, ["config", "--get", f"branch.{branch}.merge"])
    if remote_result.returncode or merge_result.returncode:
        raise RuntimeError("local worktree has no trusted upstream; provide --base")
    remote = remote_result.stdout.decode("utf-8").strip()
    merge_ref = merge_result.stdout.decode("utf-8").strip()
    branch_prefix = "refs/heads/"
    if not remote or not merge_ref.startswith(branch_prefix):
        raise RuntimeError("local worktree has no trusted upstream; provide --base")
    upstream = (
        merge_ref
        if remote == "."
        else f"refs/remotes/{remote}/{merge_ref.removeprefix(branch_prefix)}"
    )
    if not valid_revision(root, upstream):
        raise RuntimeError("local worktree upstream revision is unavailable; provide --base")
    return merge_base(root, upstream)


def comparison_revision(
    root: Path,
    explicit: str | None,
    environment: Mapping[str, str] | None = None,
) -> str:
    env = os.environ if environment is None else environment
    if explicit:
        if not valid_revision(root, explicit):
            raise RuntimeError(f"base revision does not exist: {explicit}")
        return commit_sha(root, explicit)
    github_base = env.get("GITHUB_BASE_REF")
    if github_base:
        for candidate in (f"origin/{github_base}", github_base):
            if valid_revision(root, candidate):
                return merge_base(root, candidate)
        raise RuntimeError(f"GitHub base revision is unavailable: {github_base}")
    push_revision = github_push_revision(root, env)
    if push_revision:
        return push_revision
    return local_tracking_revision(root)


def current_paths(root: Path) -> list[str]:
    result = git_result(root, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    if result.returncode == 0:
        return sorted(
            item.decode("utf-8").replace("\\", "/")
            for item in result.stdout.split(b"\0")
            if item and (root / item.decode("utf-8")).is_file()
        )
    return fallback_paths(root)


def fallback_paths(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not IGNORED_PARTS.intersection(path.relative_to(root).parts)
    )


def revision_paths(root: Path, revision: str) -> list[str]:
    output = git_result(root, ["ls-tree", "-r", "--name-only", "-z", revision])
    if output.returncode:
        detail = output.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"could not list revision {revision}")
    return sorted(
        item.decode("utf-8").replace("\\", "/") for item in output.stdout.split(b"\0") if item
    )


def is_python_metric_path(path: str) -> bool:
    server = path.startswith("apps/server/") and path.endswith(".py")
    skill = path.startswith(".agents/skills/") and "/scripts/" in path and path.endswith(".py")
    return server or skill


def is_typescript_metric_path(path: str) -> bool:
    owned = path.startswith("apps/web/") or path.startswith("packages/api-client/")
    return owned and (path.endswith(".ts") or path.endswith(".tsx"))


def scoped_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    return (
        [path for path in paths if is_python_metric_path(path)],
        [path for path in paths if is_typescript_metric_path(path)],
    )


def current_sources(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    python_paths, typescript_paths = scoped_paths(current_paths(root))
    return read_worktree(root, python_paths), read_worktree(root, typescript_paths)


def revision_sources(root: Path, revision: str) -> tuple[dict[str, str], dict[str, str]]:
    python_paths, typescript_paths = scoped_paths(revision_paths(root, revision))
    return read_revision(root, revision, python_paths), read_revision(
        root, revision, typescript_paths
    )


def read_worktree(root: Path, paths: list[str]) -> dict[str, str]:
    return {path: (root / path).read_text(encoding="utf-8") for path in paths}


def read_revision(root: Path, revision: str, paths: list[str]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for path in paths:
        result = git_result(root, ["show", f"{revision}:{path}"])
        if result.returncode:
            raise RuntimeError(f"could not read {path} from comparison revision")
        sources[path] = result.stdout.decode("utf-8")
    return sources

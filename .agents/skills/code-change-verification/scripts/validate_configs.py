#!/usr/bin/env python3
"""Run deterministic checks for changed repository configuration files."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from repository_snapshot import commit_sha, repository_root
from verification_routing import (
    is_compose_path,
    is_dockerfile_path,
    is_root_compose_overlay,
    is_workflow_path,
)

BOOLEAN_TAG = "tag:yaml.org,2002:bool"


class WorkflowLoader(yaml.SafeLoader):
    """Keep GitHub's unquoted `on` key as a string under PyYAML's YAML 1.1 rules."""


WorkflowLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in resolvers if tag != BOOLEAN_TAG]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--base", required=True)
    parser.add_argument("--paths", nargs="*", default=[])
    return parser.parse_args()


def diff_check(root: Path, base: str) -> list[str]:
    errors: list[str] = []
    head = commit_sha(root, "HEAD")
    commands = [["diff", "--check", "HEAD"]]
    if head != base:
        commands.insert(0, ["diff", "--check", f"{base}..HEAD"])
    for arguments in commands:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            detail = (result.stdout or result.stderr).strip()
            errors.append(detail or f"git {' '.join(arguments)} failed")
    return errors


def generic_errors(path: Path, text: str) -> list[str]:
    errors: list[str] = []
    if not text.strip():
        errors.append(f"{path}: configuration file is empty")
    if "\t" in text:
        errors.append(f"{path}: tab characters are not allowed")
    if any(marker in text for marker in ("<<<<<<<", "=======", ">>>>>>>")):
        errors.append(f"{path}: unresolved merge marker")
    return errors


def yaml_mapping(
    relative: str,
    text: str,
    loader: type[yaml.SafeLoader],
) -> tuple[Mapping[Any, Any] | None, list[str]]:
    try:
        loaded = yaml.load(text, Loader=loader)
    except yaml.MarkedYAMLError as error:
        line = error.problem_mark.line + 1 if error.problem_mark else "unknown"
        return None, [f"{relative}: invalid YAML at line {line}"]
    except yaml.YAMLError:
        return None, [f"{relative}: invalid YAML"]
    if not isinstance(loaded, Mapping):
        return None, [f"{relative}: YAML root must be a mapping"]
    return loaded, []


def compose_errors(relative: str, text: str) -> list[str]:
    document, errors = yaml_mapping(relative, text, yaml.SafeLoader)
    if errors or document is None:
        return errors
    services = document.get("services")
    if not isinstance(services, Mapping) or not services:
        return [f"{relative}: services must be a non-empty mapping"]
    return []


def workflow_errors(relative: str, text: str) -> list[str]:
    document, errors = yaml_mapping(relative, text, WorkflowLoader)
    if errors or document is None:
        return errors
    if "on" not in document:
        errors.append(f"{relative}: missing top-level on trigger")
    jobs = document.get("jobs")
    if not isinstance(jobs, Mapping) or not jobs:
        errors.append(f"{relative}: jobs must be a non-empty mapping")
    return errors


def content_errors(relative: str, text: str) -> list[str]:
    errors: list[str] = []
    if relative == "package.json":
        try:
            json.loads(text)
        except json.JSONDecodeError as error:
            errors.append(f"{relative}: invalid JSON at line {error.lineno}")
    if is_compose_path(relative):
        errors.extend(compose_errors(relative, text))
    if is_dockerfile_path(relative) and not re.search(r"(?mi)^\s*FROM\s+", text):
        errors.append(f"{relative}: missing FROM instruction")
    if is_workflow_path(relative):
        errors.extend(workflow_errors(relative, text))
    return errors


def compose_cli_available(root: Path) -> bool:
    if not shutil.which("docker"):
        return False
    result = subprocess.run(
        ["docker", "compose", "version"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def compose_cli_errors(root: Path, paths: list[str]) -> list[str]:
    if not compose_cli_available(root):
        return []
    errors: list[str] = []
    for relative in sorted(set(paths)):
        if not is_compose_path(relative) or not (root / relative).is_file():
            continue
        compose_files = [relative]
        if is_root_compose_overlay(relative) and (root / "compose.yaml").is_file():
            compose_files.insert(0, "compose.yaml")
        command = ["docker", "compose"]
        for compose_file in compose_files:
            command.extend(["-f", compose_file])
        command.extend(["config", "--quiet", "--no-interpolate"])
        result = subprocess.run(
            command,
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode:
            errors.append(f"{relative}: Docker Compose validation failed")
    return errors


def validate_paths(root: Path, paths: list[str]) -> list[str]:
    errors: list[str] = []
    for relative in sorted(set(paths)):
        path = root / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            errors.append(f"{relative}: cannot read configuration: {error}")
            continue
        errors.extend(generic_errors(Path(relative), text))
        errors.extend(content_errors(relative, text))
    return errors


def main() -> int:
    args = parse_args()
    root = (args.repo_root or repository_root(Path(__file__).parent)).resolve()
    errors = [
        *diff_check(root, args.base),
        *validate_paths(root, args.paths),
        *compose_cli_errors(root, args.paths),
    ]
    if errors:
        for error in errors:
            print(f"[FAIL] configuration: {error}")
        return 1
    print(f"[PASS] configuration: checked Git whitespace and {len(args.paths)} routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

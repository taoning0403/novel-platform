#!/usr/bin/env python3
"""Validate repository-local Skill structure without third-party packages."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_PATTERN = re.compile(r"\[[^\]]+\]\((?!https?://|#)([^)]+)\)")


def repository_root(start: Path) -> Path:
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / ".agents/skills").is_dir() and (candidate / "AGENTS.md").is_file():
            return candidate
    raise ValueError("could not locate repository root")


def frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    closing = text.find("\n---\n", 4)
    if closing < 0:
        raise ValueError("SKILL.md frontmatter is not closed")
    header = text[4:closing]
    values: dict[str, str] = {}
    for line in header.splitlines():
        if not line.strip() or line.startswith((" ", "\t")) or ":" not in line:
            raise ValueError("frontmatter must use one-line top-level key/value pairs")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if not key or not value:
            raise ValueError("frontmatter keys and values must be non-empty")
        if key in values:
            raise ValueError(f"duplicate frontmatter key: {key}")
        values[key] = value
    return values, text[closing + 5 :]


def metadata_errors(
    skill: Path,
    skill_file: Path,
    text: str,
    metadata: dict[str, str],
    body: str,
) -> list[str]:
    errors: list[str] = []
    if set(metadata) != {"name", "description"}:
        errors.append(f"{skill_file}: frontmatter must contain only name and description")
    name = metadata.get("name", "")
    if name != skill.name:
        errors.append(f"{skill_file}: name must match folder {skill.name!r}")
    if not NAME_PATTERN.fullmatch(name):
        errors.append(f"{skill_file}: invalid lowercase hyphenated name")
    description = metadata.get("description", "")
    if len(description) < 40:
        errors.append(f"{skill_file}: description is too short to explain use triggers")
    if "TODO" in text:
        errors.append(f"{skill_file}: unresolved TODO placeholder")
    if not body.strip():
        errors.append(f"{skill_file}: instructions body is empty")
    return errors


def link_errors(skill: Path, skill_file: Path, body: str) -> list[str]:
    errors: list[str] = []
    for raw_target in LINK_PATTERN.findall(body):
        target = raw_target.split("#", 1)[0].strip("<>")
        if target and not (skill / target).exists():
            errors.append(f"{skill_file}: missing linked resource {target}")
    return errors


def agent_errors(skill: Path, name: str) -> list[str]:
    errors: list[str] = []
    agent_file = skill / "agents/openai.yaml"
    if not agent_file.is_file():
        errors.append(f"{skill}: missing recommended agents/openai.yaml")
    else:
        agent_text = agent_file.read_text(encoding="utf-8")
        for field in ("display_name:", "short_description:", "default_prompt:"):
            if field not in agent_text:
                errors.append(f"{agent_file}: missing {field.removesuffix(':')}")
        if f"${name}" not in agent_text:
            errors.append(f"{agent_file}: default_prompt must invoke ${name}")
    return errors


def python_script_errors(skill: Path) -> list[str]:
    scripts = skill / "scripts"
    errors: list[str] = []
    for script in sorted(scripts.glob("*.py")) if scripts.is_dir() else []:
        try:
            compile(script.read_text(encoding="utf-8"), str(script), "exec")
        except (OSError, UnicodeError, SyntaxError) as error:
            errors.append(f"{script}: Python syntax failure: {error}")
    return errors


def node_script_errors(skill: Path) -> list[str]:
    scripts = skill / "scripts"
    errors: list[str] = []
    for script in sorted(scripts.glob("*.mjs")) if scripts.is_dir() else []:
        result = subprocess.run(
            ["node", "--check", str(script)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            errors.append(f"{script}: Node syntax failure: {result.stderr.strip()}")
    return errors


def validate_skill(skill: Path) -> list[str]:
    skill_file = skill / "SKILL.md"
    if not skill_file.is_file():
        return [f"{skill}: missing SKILL.md"]
    try:
        text = skill_file.read_text(encoding="utf-8")
        metadata, body = frontmatter(text)
    except (OSError, UnicodeError, ValueError) as error:
        return [f"{skill_file}: {error}"]
    errors = metadata_errors(skill, skill_file, text, metadata, body)
    errors.extend(link_errors(skill, skill_file, body))
    errors.extend(agent_errors(skill, metadata.get("name", "")))
    errors.extend(python_script_errors(skill))
    errors.extend(node_script_errors(skill))
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skills", nargs="*", type=Path, help="Skill directories; defaults to all.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = repository_root(Path(__file__).parent)
    skills = args.skills or sorted(
        path for path in (root / ".agents/skills").iterdir() if path.is_dir()
    )
    resolved = [path if path.is_absolute() else root / path for path in skills]
    errors = [error for skill in resolved for error in validate_skill(skill)]
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    print(f"[PASS] validated {len(resolved)} repository Skill directories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

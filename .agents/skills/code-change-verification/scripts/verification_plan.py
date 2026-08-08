"""Build the executable verification plan for selected repository surfaces."""

from __future__ import annotations

import sys
from pathlib import Path

from verification_routing import Selection, config_paths
from verification_runner import Gate
from verification_safety import database_prerequisite


def local_script(name: str) -> str:
    return str(Path(__file__).with_name(name))


def quality_gate(root: Path, reference: str, selected: bool) -> Gate:
    return Gate(
        "quality",
        [
            sys.executable,
            local_script("quality_guard.py"),
            "--repo-root",
            str(root),
            "--base",
            reference,
        ],
        root,
        selected,
        "no Python, TypeScript, or verification tooling change",
        blocked_exit_codes=(2,),
        neutral_marker="[BASELINE FAILURE]",
    )


def tooling_gates(
    root: Path,
    reference: str,
    paths: list[str],
    selection: Selection,
) -> list[Gate]:
    configs = config_paths(paths)
    return [
        quality_gate(root, reference, selection.quality),
        Gate(
            "project-skills",
            [sys.executable, local_script("validate_skills.py")],
            root,
            selection.project_skills,
            "repository Skills not changed",
        ),
        Gate(
            "verification-selftest",
            [sys.executable, local_script("selftest.py")],
            root,
            selection.tooling_selftest,
            "verification tooling not changed",
        ),
        Gate(
            "configuration",
            [
                sys.executable,
                local_script("validate_configs.py"),
                "--repo-root",
                str(root),
                "--base",
                reference,
                "--paths",
                *configs,
            ],
            root,
            selection.config,
            "repository configuration not changed",
            blocked_exit_codes=(2,),
        ),
    ]


def server_gates(root: Path, selection: Selection) -> list[Gate]:
    server = root / "apps/server"
    selected = selection.server
    reason = "server not changed"
    return [
        Gate("server-ruff", ["uv", "run", "ruff", "check", "."], server, selected, reason),
        Gate(
            "server-format",
            ["uv", "run", "ruff", "format", "--check", "."],
            server,
            selected,
            reason,
        ),
        Gate("server-mypy", ["uv", "run", "mypy"], server, selected, reason),
        Gate(
            "server-unit",
            ["uv", "run", "pytest", "tests/unit"],
            server,
            selected,
            reason,
        ),
    ]


def web_gates(root: Path, selection: Selection) -> list[Gate]:
    selected = selection.web
    reason = "Web/client not changed"
    return [
        Gate("api-contract", ["pnpm", "api:check"], root, selection.api, "API unchanged"),
        Gate("web-lint", ["pnpm", "lint"], root, selected, reason),
        Gate("web-test", ["pnpm", "test"], root, selected, reason),
        Gate("web-build", ["pnpm", "build"], root, selected, reason),
    ]


def database_gates(root: Path, selection: Selection) -> list[Gate]:
    server = root / "apps/server"
    return [
        Gate(
            "postgres-integration",
            [
                "uv",
                "run",
                "pytest",
                "tests/integration",
                "--ignore=tests/integration/test_migrations.py",
            ],
            server,
            selection.integration,
            "PostgreSQL integration surface not changed",
            prerequisite=database_prerequisite,
        ),
        Gate(
            "migration-integration",
            ["uv", "run", "pytest", "tests/integration/test_migrations.py"],
            server,
            selection.migration,
            "migration surface not changed",
            prerequisite=database_prerequisite,
        ),
    ]


def build_plan(
    root: Path,
    reference: str,
    paths: list[str],
    selection: Selection,
) -> list[Gate]:
    gates = tooling_gates(root, reference, paths, selection)
    gates.extend(server_gates(root, selection))
    gates.extend(web_gates(root, selection))
    gates.extend(database_gates(root, selection))
    gates.append(
        Gate(
            "acceptance",
            ["pnpm", "acceptance"],
            root,
            selection.acceptance,
            "no user-visible surface selected",
        )
    )
    return gates

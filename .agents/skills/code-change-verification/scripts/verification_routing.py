"""Map changed paths to deterministic verification surfaces."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PurePosixPath


@dataclass(frozen=True)
class Selection:
    quality: bool
    project_skills: bool
    tooling_selftest: bool
    config: bool
    web: bool
    server: bool
    api: bool
    integration: bool
    migration: bool
    acceptance: bool


def any_prefix(paths: list[str], *prefixes: str) -> bool:
    return any(path.startswith(prefixes) for path in paths)


def any_suffix(paths: list[str], *suffixes: str) -> bool:
    return any(path.endswith(suffixes) for path in paths)


def is_compose_path(path: str) -> bool:
    candidate = PurePosixPath(path)
    name = candidate.name
    root_compose = (
        candidate.parent == PurePosixPath(".")
        and name.startswith("compose")
        and candidate.suffix in {".yml", ".yaml"}
    )
    acceptance_support = candidate.parent == PurePosixPath(
        "scripts/acceptance/support"
    ) and candidate.suffix in {".yml", ".yaml"}
    return root_compose or acceptance_support


def is_root_compose_overlay(path: str) -> bool:
    candidate = PurePosixPath(path)
    return (
        candidate.parent == PurePosixPath(".")
        and candidate.name != "compose.yaml"
        and candidate.name.startswith("compose")
        and candidate.suffix in {".yml", ".yaml"}
    )


def is_dockerfile_path(path: str) -> bool:
    return PurePosixPath(path).name.startswith("Dockerfile")


def is_workflow_path(path: str) -> bool:
    return path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))


def is_root_config(path: str) -> bool:
    return path in {"package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"}


def is_config_path(path: str) -> bool:
    return (
        is_compose_path(path)
        or is_dockerfile_path(path)
        or is_workflow_path(path)
        or is_root_config(path)
    )


def config_paths(paths: list[str]) -> list[str]:
    return sorted(path for path in paths if is_config_path(path))


def quality_selected(paths: list[str], all_selected: bool) -> bool:
    source = any_suffix(paths, ".py", ".ts", ".tsx")
    tooling = any_prefix(paths, ".agents/skills/code-change-verification/")
    return all_selected or source or tooling


def web_selected(paths: list[str], all_selected: bool) -> bool:
    workspace = any_prefix(paths, "apps/web/", "packages/api-client/")
    return all_selected or workspace or any(is_root_config(path) for path in paths)


def server_selected(paths: list[str], all_selected: bool) -> bool:
    python = any(path.startswith("apps/server/") and path.endswith(".py") for path in paths)
    environment = any(
        path in {"apps/server/pyproject.toml", "apps/server/uv.lock"} for path in paths
    )
    return all_selected or python or environment


def api_selected(paths: list[str], all_selected: bool) -> bool:
    adapters = any_prefix(
        paths,
        "apps/server/src/novel_platform/api/",
        "packages/api-client/",
    )
    entrypoints = any(
        path
        in {
            "apps/server/src/novel_platform/main.py",
            "apps/server/scripts/export_openapi.py",
        }
        for path in paths
    )
    return all_selected or adapters or entrypoints


def integration_selected(paths: list[str], all_selected: bool) -> bool:
    return all_selected or any_prefix(
        paths,
        "apps/server/src/novel_platform/application/",
        "apps/server/src/novel_platform/domain/",
        "apps/server/src/novel_platform/infrastructure/",
        "apps/server/src/novel_platform/api/",
        "apps/server/tests/integration/",
    )


def migration_selected(paths: list[str], all_selected: bool) -> bool:
    migration_path = any_prefix(paths, "apps/server/migrations/")
    exact = any(
        path
        in {
            "apps/server/alembic.ini",
            "apps/server/src/novel_platform/infrastructure/database/models.py",
            "apps/server/tests/integration/conftest.py",
            "apps/server/tests/integration/test_migrations.py",
        }
        for path in paths
    )
    return all_selected or migration_path or exact


def acceptance_selected(paths: list[str], all_selected: bool, user_visible: bool) -> bool:
    web = any_prefix(paths, "apps/web/src/", "scripts/acceptance/")
    compose = any(is_compose_path(path) for path in paths)
    return all_selected or user_visible or web or compose


def select_surfaces(
    paths: list[str],
    *,
    all_selected: bool,
    quality_only: bool,
    user_visible: bool,
    config_only: bool = False,
) -> Selection:
    selection = Selection(
        quality=quality_selected(paths, all_selected),
        project_skills=all_selected or any_prefix(paths, ".agents/skills/"),
        tooling_selftest=all_selected
        or any_prefix(paths, ".agents/skills/code-change-verification/"),
        config=all_selected or bool(config_paths(paths)),
        web=web_selected(paths, all_selected),
        server=server_selected(paths, all_selected),
        api=api_selected(paths, all_selected),
        integration=integration_selected(paths, all_selected),
        migration=migration_selected(paths, all_selected),
        acceptance=acceptance_selected(paths, all_selected, user_visible),
    )
    if config_only:
        return replace(
            selection,
            quality=False,
            project_skills=False,
            tooling_selftest=False,
            config=True,
            web=False,
            server=False,
            api=False,
            integration=False,
            migration=False,
            acceptance=False,
        )
    if not quality_only:
        return selection
    return replace(
        selection,
        quality=True,
        project_skills=True,
        tooling_selftest=True,
        config=False,
        web=False,
        server=False,
        api=False,
        integration=False,
        migration=False,
        acceptance=False,
    )

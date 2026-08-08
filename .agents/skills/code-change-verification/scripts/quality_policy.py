"""Fixed quality thresholds and architecture policy."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 2
EXIT_FAIL = 1
EXIT_BLOCKED = 2

THRESHOLDS: dict[str, dict[str, int]] = {
    "python": {
        "file_effective_lines": 400,
        "function_effective_lines": 60,
        "cyclomatic_complexity": 10,
        "nesting_depth": 4,
    },
    "typescript": {
        "file_effective_lines": 300,
        "function_effective_lines": 60,
        "cyclomatic_complexity": 10,
        "nesting_depth": 4,
    },
}

EXCLUSIONS: list[dict[str, Any]] = [
    {
        "path": "apps/server/migrations/versions/*.py",
        "metrics": list(THRESHOLDS["python"]),
        "reason": "Alembic revisions are linear, reviewable migration records.",
    },
    {
        "path": "packages/api-client/src/schema.d.ts",
        "metrics": list(THRESHOLDS["typescript"]),
        "reason": "Generated from the checked OpenAPI contract.",
    },
    {
        "path": "apps/server/src/novel_platform/infrastructure/database/models.py",
        "metrics": ["file_effective_lines"],
        "reason": "Declarative SQLAlchemy mappings; function metrics remain enforced.",
    },
    {
        "path": "apps/server/src/novel_platform/api/schemas.py",
        "metrics": ["file_effective_lines"],
        "reason": "Declarative Pydantic contracts; function metrics remain enforced.",
    },
]

ALLOWED_EDGES: list[dict[str, str]] = [
    {
        "from": "novel_platform.infrastructure.storage.local",
        "to": "novel_platform.application.library.storage",
        "reason": "The local infrastructure adapter implements the application-owned storage port.",
    }
]

REVERSE_EDGE_NAMES = (
    "application_to_infrastructure",
    "api_to_infrastructure",
)


@dataclass(frozen=True)
class Metric:
    language: str
    path: str
    symbol: str
    metric: str
    value: int
    threshold: int

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.symbol, self.metric)


def in_layer(module: str, prefix: str) -> bool:
    """Return true for a layer root or one of its descendants."""
    return module == prefix or module.startswith(f"{prefix}.")


def is_excluded(metric: Metric) -> bool:
    return any(
        fnmatch.fnmatch(metric.path, exclusion["path"]) and metric.metric in exclusion["metrics"]
        for exclusion in EXCLUSIONS
    )


def violation_map(metrics: list[Metric]) -> dict[tuple[str, str, str], Metric]:
    return {
        metric.key: metric
        for metric in metrics
        if metric.value > metric.threshold and not is_excluded(metric)
    }

"""Compose language metrics with dependency and boundary analysis."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dependency_graph import (
    cycle_failures,
    python_boundary_failures,
    python_import_graph,
    reverse_edges,
    skill_script_import_graph,
    strongly_connected_components,
    typescript_import_graph,
)
from python_metrics import python_metrics
from quality_policy import Metric, violation_map
from typescript_metrics import typescript_metrics


@dataclass
class Analysis:
    metrics: list[Metric]
    violations: dict[tuple[str, str, str], Metric]
    reverse_edges: dict[str, list[dict[str, str]]]
    failures: list[str]
    python_cycles: int
    typescript_cycles: int
    boundary_failures: int


def empty_reverse_edges() -> dict[str, list[dict[str, str]]]:
    return {
        "application_to_infrastructure": [],
        "api_to_infrastructure": [],
    }


def typescript_parse_failures(files: list[dict[str, object]]) -> list[str]:
    return [
        f"TypeScript parse failure: {file['path']}: {diagnostic}"
        for file in files
        for diagnostic in file.get("diagnostics", [])
    ]


def analyze_sources(
    root: Path,
    python_sources: Mapping[str, str],
    typescript_sources: Mapping[str, str],
    languages: set[str],
) -> Analysis:
    metrics: list[Metric] = []
    failures: list[str] = []
    edges = empty_reverse_edges()
    python_cycle_count = 0
    typescript_cycle_count = 0
    boundary_count = 0

    if "python" in languages:
        python_result, trees, parse_failures = python_metrics(python_sources)
        metrics.extend(python_result)
        failures.extend(f"python parse failure: {item}" for item in parse_failures)
        graph = python_import_graph(trees)
        skill_graph = skill_script_import_graph(trees)
        cycles = [
            *strongly_connected_components(graph),
            *strongly_connected_components(skill_graph),
        ]
        boundaries = python_boundary_failures(graph)
        python_cycle_count = len(cycles)
        boundary_count = len(boundaries)
        failures.extend(cycle_failures("python", graph))
        failures.extend(cycle_failures("Python Skill", skill_graph))
        failures.extend(boundaries)
        edges = reverse_edges(graph)

    if "typescript" in languages:
        typescript_result, files = typescript_metrics(root, typescript_sources)
        metrics.extend(typescript_result)
        graph = typescript_import_graph(files)
        cycles = strongly_connected_components(graph)
        typescript_cycle_count = len(cycles)
        failures.extend(typescript_parse_failures(files))
        failures.extend(cycle_failures("TypeScript", graph))

    return Analysis(
        metrics=metrics,
        violations=violation_map(metrics),
        reverse_edges=edges,
        failures=sorted(failures),
        python_cycles=python_cycle_count,
        typescript_cycles=typescript_cycle_count,
        boundary_failures=boundary_count,
    )

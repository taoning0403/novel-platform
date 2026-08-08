"""Validate, compare, and write the reviewable quality baseline."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from quality_analysis import Analysis
from quality_policy import (
    ALLOWED_EDGES,
    EXCLUSIONS,
    REVERSE_EDGE_NAMES,
    SCHEMA_VERSION,
    THRESHOLDS,
    Metric,
)

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MetricKey = tuple[str, str, str]
Edge = tuple[str, str]


def baseline_payload(
    reference: str,
    reference_date: str,
    analysis: Analysis,
) -> dict[str, Any]:
    violations = sorted(
        analysis.violations.values(),
        key=lambda item: (item.path, item.symbol, item.metric),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_from": {
            "commit": reference,
            "date": reference_date,
        },
        "thresholds": THRESHOLDS,
        "exclusions": EXCLUSIONS,
        "violations": [asdict(metric) for metric in violations],
        "dependency_baseline": {
            "python_cycles": 0,
            "typescript_cycles": 0,
            "python_reverse_edges": analysis.reverse_edges,
            "allowed_edges": ALLOWED_EDGES,
        },
    }


def write_baseline(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_baseline(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("quality baseline root must be an object")
    return value


def valid_provenance(generated: dict[str, Any]) -> bool:
    commit = generated.get("commit")
    date = generated.get("date")
    return (
        set(generated) == {"commit", "date"}
        and isinstance(commit, str)
        and bool(COMMIT_PATTERN.fullmatch(commit))
        and isinstance(date, str)
        and bool(date)
    )


def metadata_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if data.get("thresholds") != THRESHOLDS:
        errors.append("thresholds do not match the enforced constants")
    if data.get("exclusions") != EXCLUSIONS:
        errors.append("exclusions do not match the enforced metric-scoped list")
    generated = data.get("generated_from")
    if not isinstance(generated, dict) or not valid_provenance(generated):
        errors.append("generated_from must contain a full commit and non-empty date")
    return errors


def metric_from_entry(entry: dict[str, Any]) -> Metric:
    return Metric(
        language=str(entry["language"]),
        path=str(entry["path"]),
        symbol=str(entry["symbol"]),
        metric=str(entry["metric"]),
        value=int(entry["value"]),
        threshold=int(entry["threshold"]),
    )


def baseline_metrics(data: dict[str, Any]) -> tuple[dict[MetricKey, Metric], list[str]]:
    raw = data.get("violations")
    if not isinstance(raw, list):
        return {}, ["violations must be a list"]
    metrics: dict[MetricKey, Metric] = {}
    errors: list[str] = []
    for entry in raw:
        try:
            metric = metric_from_entry(entry)
        except (KeyError, TypeError, ValueError):
            errors.append(f"malformed baseline metric: {entry!r}")
            continue
        if metric.key in metrics:
            errors.append(f"duplicate baseline key: {' | '.join(metric.key)}")
        metrics[metric.key] = metric
    return metrics, errors


def edge_tuple(record: dict[str, str]) -> Edge:
    return (record["from"], record["to"])


def edge_list(value: Any, name: str) -> tuple[list[dict[str, str]], list[str]]:
    if not isinstance(value, list):
        return [], [f"{name} reverse edges must be a list"]
    records: list[dict[str, str]] = []
    errors: list[str] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"from", "to"}:
            errors.append(f"{name} contains a malformed edge")
            continue
        records.append({"from": str(item["from"]), "to": str(item["to"])})
    if records != sorted(records, key=edge_tuple):
        errors.append(f"{name} reverse edges must be sorted")
    if len(records) != len({edge_tuple(item) for item in records}):
        errors.append(f"{name} reverse edges must be unique")
    return records, errors


def dependency_data(
    data: dict[str, Any],
) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    dependency = data.get("dependency_baseline")
    if not isinstance(dependency, dict):
        return {}, ["dependency_baseline must be an object"]
    errors = dependency_metadata_errors(dependency)
    raw_edges = dependency.get("python_reverse_edges")
    if not isinstance(raw_edges, dict) or set(raw_edges) != set(REVERSE_EDGE_NAMES):
        return {}, [*errors, "dependency baseline must record both reverse-edge sets"]
    edges: dict[str, list[dict[str, str]]] = {}
    for name in REVERSE_EDGE_NAMES:
        edges[name], edge_errors = edge_list(raw_edges[name], name)
        errors.extend(edge_errors)
    return edges, errors


def dependency_metadata_errors(dependency: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if dependency.get("python_cycles") != 0:
        errors.append("dependency baseline must contain zero Python cycles")
    if dependency.get("typescript_cycles") != 0:
        errors.append("dependency baseline must contain zero TypeScript cycles")
    if dependency.get("allowed_edges") != ALLOWED_EDGES:
        errors.append("dependency baseline has an unreviewed allowed edge")
    return errors


def trusted_provenance_errors(
    data: dict[str, Any],
    trusted_reference: str | None,
    commit_exists: Callable[[str], bool] | None,
    commit_date: Callable[[str], str] | None,
    commit_is_ancestor: Callable[[str, str], bool] | None,
) -> list[str]:
    configured = (
        trusted_reference is not None,
        commit_exists is not None,
        commit_date is not None,
        commit_is_ancestor is not None,
    )
    if not any(configured):
        return []
    if not all(configured):
        return ["trusted provenance validation is incompletely configured"]
    assert trusted_reference is not None
    assert commit_exists is not None
    assert commit_date is not None
    assert commit_is_ancestor is not None
    generated = data.get("generated_from")
    if not isinstance(generated, dict) or not valid_provenance(generated):
        return []
    commit = str(generated["commit"])
    errors: list[str] = []
    if not commit_exists(commit):
        return ["generated_from commit does not exist"]
    if not commit_is_ancestor(commit, trusted_reference):
        errors.append("generated_from commit must be an ancestor of the trusted reference")
    if generated["date"] != commit_date(commit):
        errors.append("generated_from date must equal its commit date")
    return errors


def validate_baseline(
    data: dict[str, Any],
    *,
    trusted_reference: str | None = None,
    commit_exists: Callable[[str], bool] | None = None,
    commit_date: Callable[[str], str] | None = None,
    commit_is_ancestor: Callable[[str, str], bool] | None = None,
) -> tuple[dict[MetricKey, Metric], dict[str, list[dict[str, str]]], list[str]]:
    metrics, metric_errors = baseline_metrics(data)
    edges, dependency_errors = dependency_data(data)
    provenance_errors = trusted_provenance_errors(
        data,
        trusted_reference,
        commit_exists,
        commit_date,
        commit_is_ancestor,
    )
    errors = [
        *metadata_errors(data),
        *provenance_errors,
        *metric_errors,
        *dependency_errors,
    ]
    return metrics, edges, errors


def selected_metrics(
    metrics: dict[MetricKey, Metric], languages: set[str]
) -> dict[MetricKey, Metric]:
    return {key: metric for key, metric in metrics.items() if metric.language in languages}


def metric_regressions(
    current: dict[MetricKey, Metric], reference: dict[MetricKey, Metric]
) -> list[str]:
    failures: list[str] = []
    for key, metric in sorted(current.items()):
        old = reference.get(key)
        label = " | ".join(key)
        if old is None:
            failures.append(f"new violation against comparison revision: {label}")
        elif metric.value > old.value:
            failures.append(
                f"worsened against comparison revision: {label} {old.value} -> {metric.value}"
            )
    return failures


def baseline_integrity_failures(
    stored: dict[MetricKey, Metric], reference: dict[MetricKey, Metric]
) -> list[str]:
    failures: list[str] = []
    for key, metric in sorted(stored.items()):
        old = reference.get(key)
        label = " | ".join(key)
        if old is None:
            failures.append(f"baseline contains untrusted key: {label}")
        elif metric.language != old.language or metric.threshold != old.threshold:
            failures.append(f"baseline metadata differs from reference: {label}")
        elif metric.value > old.value:
            failures.append(f"baseline loosens reference: {label} {old.value} -> {metric.value}")
    return failures


def baseline_freshness_failures(
    current: dict[MetricKey, Metric], stored: dict[MetricKey, Metric]
) -> list[str]:
    failures: list[str] = []
    for key, metric in sorted(current.items()):
        old = stored.get(key)
        label = " | ".join(key)
        if old is None:
            failures.append(f"baseline missing current violation: {label}")
        elif metric.value > old.value:
            failures.append(
                f"current violation exceeds baseline: {label} {old.value} -> {metric.value}"
            )
        elif metric.value < old.value:
            failures.append(f"TIGHTEN baseline: {label} {old.value} -> {metric.value}")
    for key in sorted(set(stored) - set(current)):
        failures.append(f"CLEANUP baseline: {' | '.join(key)}")
    return failures


def edge_set(records: list[dict[str, str]]) -> set[Edge]:
    return {edge_tuple(record) for record in records}


def describe_edges(name: str, edges: set[Edge], problem: str) -> list[str]:
    return [f"{problem}: {name}: {source} -> {target}" for source, target in sorted(edges)]


def edge_failures(
    current: dict[str, list[dict[str, str]]],
    stored: dict[str, list[dict[str, str]]],
    reference: dict[str, list[dict[str, str]]],
) -> list[str]:
    failures: list[str] = []
    for name in REVERSE_EDGE_NAMES:
        current_set = edge_set(current[name])
        stored_set = edge_set(stored[name])
        reference_set = edge_set(reference[name])
        failures.extend(
            describe_edges(
                name,
                current_set - reference_set,
                "new edge against comparison revision",
            )
        )
        failures.extend(describe_edges(name, stored_set - reference_set, "untrusted baseline edge"))
        failures.extend(
            describe_edges(name, current_set - stored_set, "baseline missing current edge")
        )
        failures.extend(
            describe_edges(name, stored_set - current_set, "TIGHTEN baseline stale edge")
        )
    return failures


def comparison_failures(
    current: Analysis,
    reference: Analysis,
    stored_metrics: dict[MetricKey, Metric],
    stored_edges: dict[str, list[dict[str, str]]],
    languages: set[str],
) -> list[str]:
    current_metrics = selected_metrics(current.violations, languages)
    reference_metrics = selected_metrics(reference.violations, languages)
    selected_stored = selected_metrics(stored_metrics, languages)
    failures = metric_regressions(current_metrics, reference_metrics)
    failures.extend(baseline_integrity_failures(selected_stored, reference_metrics))
    failures.extend(baseline_freshness_failures(current_metrics, selected_stored))
    if "python" in languages:
        failures.extend(edge_failures(current.reverse_edges, stored_edges, reference.reverse_edges))
    return failures


def write_regressions(current: Analysis, reference: Analysis, languages: set[str]) -> list[str]:
    current_metrics = selected_metrics(current.violations, languages)
    reference_metrics = selected_metrics(reference.violations, languages)
    failures = metric_regressions(current_metrics, reference_metrics)
    if "python" in languages:
        for name in REVERSE_EDGE_NAMES:
            current_set = edge_set(current.reverse_edges[name])
            reference_set = edge_set(reference.reverse_edges[name])
            failures.extend(
                describe_edges(
                    name,
                    current_set - reference_set,
                    "new edge against comparison revision",
                )
            )
    return failures

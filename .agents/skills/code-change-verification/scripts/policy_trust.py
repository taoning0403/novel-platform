"""Keep quality-policy changes anchored to a trusted Git revision."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from quality_policy import (
    ALLOWED_EDGES,
    EXCLUSIONS,
    REVERSE_EDGE_NAMES,
    SCHEMA_VERSION,
    THRESHOLDS,
)
from repository_snapshot import git_result

BASELINE_RELATIVE = ".agents/skills/code-change-verification/references/quality-baseline.json"
BOOTSTRAP_REFERENCE = "3a379001e9091e92eb858286d9f3331657aaf767"
BOOTSTRAP_POLICY_DIGEST = "e6336cb95058d66070238214d6a4669ebc6ba0b641a25a1faef49a476f17d4ad"
Policy = dict[str, Any]


def runtime_policy() -> Policy:
    return {
        "schema_version": SCHEMA_VERSION,
        "thresholds": THRESHOLDS,
        "exclusions": EXCLUSIONS,
        "allowed_edges": ALLOWED_EDGES,
        "reverse_edge_names": list(REVERSE_EDGE_NAMES),
    }


def baseline_policy(data: dict[str, Any]) -> Policy:
    dependency = data.get("dependency_baseline")
    if not isinstance(dependency, dict):
        raise ValueError("trusted quality baseline has no dependency policy")
    reverse_edges = dependency.get("python_reverse_edges")
    if not isinstance(reverse_edges, dict):
        raise ValueError("trusted quality baseline has no reverse-edge policy")
    return {
        "schema_version": data.get("schema_version"),
        "thresholds": data.get("thresholds"),
        "exclusions": data.get("exclusions"),
        "allowed_edges": dependency.get("allowed_edges"),
        "reverse_edge_names": sorted(reverse_edges),
    }


def policy_digest(policy: Policy) -> str:
    encoded = json.dumps(
        policy,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def revision_baseline(root: Path, reference: str) -> dict[str, Any] | None:
    result = git_result(root, ["show", f"{reference}:{BASELINE_RELATIVE}"])
    if result.returncode:
        return None
    data = json.loads(result.stdout.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("trusted quality baseline root must be an object")
    return data


def trusted_policy(root: Path, reference: str, current: Policy) -> Policy:
    data = revision_baseline(root, reference)
    if data is not None:
        return baseline_policy(data)
    if reference != BOOTSTRAP_REFERENCE:
        raise RuntimeError("trusted revision has no quality policy; provide a reviewed --base")
    if policy_digest(current) != BOOTSTRAP_POLICY_DIGEST:
        raise RuntimeError("bootstrap quality policy differs from its reviewed digest")
    return current


def record_set(value: object, label: str) -> tuple[set[str], list[str]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        return set(), [f"{label} must be a list of objects"]
    return {
        json.dumps(item, ensure_ascii=True, separators=(",", ":"), sort_keys=True) for item in value
    }, []


def language_threshold_regressions(
    language: str,
    current: object,
    trusted: object,
) -> list[str]:
    if not isinstance(current, dict) or not isinstance(trusted, dict):
        return [f"{language} thresholds must be objects"]
    if set(current) != set(trusted):
        return [f"{language} threshold metric set differs from the trusted policy"]
    failures: list[str] = []
    for metric in sorted(current):
        value = current[metric]
        trusted_value = trusted[metric]
        if not isinstance(value, int) or not isinstance(trusted_value, int):
            failures.append(f"{language} {metric} threshold must be an integer")
        elif value > trusted_value:
            failures.append(
                f"threshold loosens trusted policy: {language} {metric} {trusted_value} -> {value}"
            )
    return failures


def threshold_regressions(current: object, trusted: object) -> list[str]:
    if not isinstance(current, dict) or not isinstance(trusted, dict):
        return ["threshold policy must be an object"]
    if set(current) != set(trusted):
        return ["threshold language set differs from the trusted policy"]
    failures: list[str] = []
    for language in sorted(current):
        failures.extend(
            language_threshold_regressions(
                language,
                current[language],
                trusted[language],
            )
        )
    return failures


def added_record_regressions(
    current: object,
    trusted: object,
    label: str,
) -> list[str]:
    current_records, current_errors = record_set(current, label)
    trusted_records, trusted_errors = record_set(trusted, f"trusted {label}")
    failures = [*current_errors, *trusted_errors]
    if not failures and current_records - trusted_records:
        failures.append(f"{label} adds or changes a record relative to the trusted policy")
    return failures


def policy_regressions(current: Policy, trusted: Policy) -> list[str]:
    failures: list[str] = []
    if current.get("schema_version") != trusted.get("schema_version"):
        failures.append("quality-policy schema differs from the trusted policy")
    failures.extend(
        threshold_regressions(
            current.get("thresholds"),
            trusted.get("thresholds"),
        )
    )
    failures.extend(
        added_record_regressions(
            current.get("exclusions"),
            trusted.get("exclusions"),
            "quality exclusions",
        )
    )
    failures.extend(
        added_record_regressions(
            current.get("allowed_edges"),
            trusted.get("allowed_edges"),
            "allowed dependency edges",
        )
    )
    current_names = current.get("reverse_edge_names")
    trusted_names = trusted.get("reverse_edge_names")
    if (
        not isinstance(current_names, list)
        or not isinstance(trusted_names, list)
        or set(current_names) != set(trusted_names)
    ):
        failures.append("reverse-edge policy differs from the trusted policy")
    return failures

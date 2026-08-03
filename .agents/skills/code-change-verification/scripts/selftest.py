#!/usr/bin/env python3
"""Run stdlib regression tests for the repository verification tooling."""

from __future__ import annotations

import ast
import sys
import unittest
from copy import deepcopy
from pathlib import Path

import selftest_git
from baseline_policy import (
    baseline_payload,
    comparison_failures,
    validate_baseline,
    write_regressions,
)
from dependency_graph import (
    boundary_failure,
    skill_script_import_graph,
    strongly_connected_components,
)
from policy_trust import policy_regressions, runtime_policy
from quality_analysis import Analysis
from quality_policy import Metric, in_layer
from validate_configs import content_errors
from verification_routing import config_paths, select_surfaces
from verification_runner import (
    BASELINE_FAILURE,
    BLOCKED,
    Gate,
    exit_status,
    run_gate,
)
from verification_safety import database_prerequisite


def empty_edges() -> dict[str, list[dict[str, str]]]:
    return {
        "application_to_infrastructure": [],
        "api_to_infrastructure": [],
    }


def analysis(*metrics: Metric) -> Analysis:
    violations = {metric.key: metric for metric in metrics}
    return Analysis(
        metrics=list(metrics),
        violations=violations,
        reverse_edges=empty_edges(),
        failures=[],
        python_cycles=0,
        typescript_cycles=0,
        boundary_failures=0,
    )


def metric(path: str, value: int) -> Metric:
    return Metric("python", path, "sample", "function_effective_lines", value, 60)


class BaselinePolicyTests(unittest.TestCase):
    def test_rewritten_baseline_cannot_bless_worsening(self) -> None:
        old = metric("sample.py", 65)
        worsened = metric("sample.py", 70)
        failures = comparison_failures(
            analysis(worsened),
            analysis(old),
            {worsened.key: worsened},
            empty_edges(),
            {"python"},
        )
        self.assertTrue(any("worsened against comparison revision" in item for item in failures))
        self.assertTrue(write_regressions(analysis(worsened), analysis(old), {"python"}))

    def test_stale_baseline_demands_tighten_and_cleanup(self) -> None:
        current = metric("current.py", 65)
        stale = metric("current.py", 70)
        removed = metric("removed.py", 65)
        failures = comparison_failures(
            analysis(current),
            analysis(current),
            {stale.key: stale, removed.key: removed},
            empty_edges(),
            {"python"},
        )
        self.assertTrue(any("TIGHTEN" in item for item in failures))
        self.assertTrue(any("CLEANUP" in item for item in failures))

    def test_edge_replacement_cannot_offset_a_new_edge(self) -> None:
        current = analysis()
        reference = analysis()
        current.reverse_edges["api_to_infrastructure"] = [
            {"from": "api.new", "to": "infrastructure.new"}
        ]
        reference.reverse_edges["api_to_infrastructure"] = [
            {"from": "api.old", "to": "infrastructure.old"}
        ]
        failures = comparison_failures(
            current,
            reference,
            {},
            current.reverse_edges,
            {"python"},
        )
        self.assertTrue(any("new edge against comparison revision" in item for item in failures))

    def test_baseline_provenance_uses_supplied_commit_date(self) -> None:
        date = "2026-07-30T17:08:18+08:00"
        payload = baseline_payload("a" * 40, date, analysis())
        self.assertEqual(date, payload["generated_from"]["date"])

    def test_baseline_provenance_must_be_a_dated_trusted_ancestor(self) -> None:
        baseline_commit = "a" * 40
        trusted = "b" * 40
        date = "2026-07-30T17:08:18+08:00"
        payload = baseline_payload(baseline_commit, date, analysis())
        _metrics, _edges, errors = validate_baseline(
            payload,
            trusted_reference=trusted,
            commit_exists=lambda commit: commit == baseline_commit,
            commit_date=lambda commit: date if commit == baseline_commit else "",
            commit_is_ancestor=lambda commit, reference: (
                commit == baseline_commit and reference == trusted
            ),
        )
        self.assertEqual([], errors)
        for commit, recorded_date, is_ancestor, expected_error in (
            ("c" * 40, date, False, "does not exist"),
            (baseline_commit, "2026-07-29T00:00:00Z", True, "commit date"),
            (baseline_commit, date, False, "ancestor"),
        ):
            payload["generated_from"] = {"commit": commit, "date": recorded_date}
            ancestry_check = (
                (lambda _commit, _reference: True)
                if is_ancestor
                else (lambda _commit, _reference: False)
            )
            _metrics, _edges, errors = validate_baseline(
                payload,
                trusted_reference=trusted,
                commit_exists=lambda candidate: candidate != "c" * 40,
                commit_date=lambda _candidate: date,
                commit_is_ancestor=ancestry_check,
            )
            with self.subTest(
                commit=commit,
                date=recorded_date,
                is_ancestor=is_ancestor,
            ):
                self.assertTrue(any(expected_error in error for error in errors))


class DependencyPolicyTests(unittest.TestCase):
    def test_layer_root_has_boundary_membership(self) -> None:
        self.assertTrue(in_layer("novel_platform.domain", "novel_platform.domain"))
        failure = boundary_failure(
            "novel_platform.domain",
            "novel_platform.infrastructure",
        )
        self.assertIn("domain reverse dependency", failure or "")

    def test_skill_sibling_import_cycle_is_detected(self) -> None:
        prefix = ".agents/skills/example/scripts"
        trees = {
            f"{prefix}/alpha.py": ast.parse("import beta\n"),
            f"{prefix}/beta.py": ast.parse("import alpha\n"),
        }
        graph = skill_script_import_graph(trees)
        self.assertEqual(1, len(strongly_connected_components(graph)))


class PolicyTrustTests(unittest.TestCase):
    def test_threshold_loosening_is_rejected(self) -> None:
        trusted = runtime_policy()
        current = deepcopy(trusted)
        current["thresholds"]["python"]["cyclomatic_complexity"] = 11
        failures = policy_regressions(current, trusted)
        self.assertTrue(any("threshold loosens" in failure for failure in failures))

    def test_new_exclusion_is_rejected(self) -> None:
        trusted = runtime_policy()
        current = deepcopy(trusted)
        current["exclusions"].append(
            {
                "path": "apps/server/src/**",
                "metrics": ["cyclomatic_complexity"],
                "reason": "selftest",
            }
        )
        failures = policy_regressions(current, trusted)
        self.assertTrue(any("exclusions" in failure for failure in failures))

    def test_new_allowed_edge_is_rejected(self) -> None:
        trusted = runtime_policy()
        current = deepcopy(trusted)
        current["allowed_edges"].append(
            {
                "from": "novel_platform.infrastructure.example",
                "to": "novel_platform.api.example",
                "reason": "selftest",
            }
        )
        failures = policy_regressions(current, trusted)
        self.assertTrue(any("allowed dependency edges" in failure for failure in failures))

    def test_tighter_policy_is_allowed(self) -> None:
        trusted = runtime_policy()
        current = deepcopy(trusted)
        current["thresholds"]["python"]["cyclomatic_complexity"] = 9
        current["exclusions"].pop()
        current["allowed_edges"].clear()
        self.assertEqual([], policy_regressions(current, trusted))


class DatabaseSafetyTests(unittest.TestCase):
    def test_local_isolated_database_is_allowed(self) -> None:
        environment = {"TEST_DATABASE_URL": "postgresql://user:secret@localhost/app-test-db"}
        self.assertIsNone(database_prerequisite(environment))

    def test_database_name_requires_independent_test_segment(self) -> None:
        environment = {"TEST_DATABASE_URL": "postgresql://user:secret@localhost/latest"}
        self.assertIn("standalone test segment", database_prerequisite(environment) or "")

    def test_remote_database_requires_explicit_override(self) -> None:
        environment = {"TEST_DATABASE_URL": "postgresql://user:secret@db.example/app_test"}
        self.assertIn("ALLOW_REMOTE", database_prerequisite(environment) or "")
        environment["ALLOW_REMOTE_TEST_DATABASE"] = "1"
        self.assertIsNone(database_prerequisite(environment))

    def test_query_cannot_override_connection_target(self) -> None:
        queries = (
            "host=production.example",
            "HOSTADDR=203.0.113.1",
            "%64%62name=production",
            "database=production&database=app_test",
        )
        for query in queries:
            environment = {
                "TEST_DATABASE_URL": ("postgresql://user:secret@localhost/app_test?" + query)
            }
            with self.subTest(query=query):
                self.assertIn(
                    "connection target",
                    database_prerequisite(environment) or "",
                )

    def test_non_target_query_parameter_is_allowed(self) -> None:
        environment = {
            "TEST_DATABASE_URL": ("postgresql://user:secret@localhost/app_test?sslmode=disable")
        }
        self.assertIsNone(database_prerequisite(environment))


class StatusAndConfigTests(unittest.TestCase):
    def test_baseline_failure_is_neutral_but_not_pass(self) -> None:
        gate = Gate(
            "quality",
            [sys.executable, "-c", "print('[BASELINE FAILURE] debt')"],
            Path.cwd(),
            True,
            "",
            neutral_marker="[BASELINE FAILURE]",
        )
        result = run_gate(gate)
        self.assertEqual(BASELINE_FAILURE, result.status)
        self.assertEqual(0, exit_status([result]))

    def test_blocked_status_propagates_to_exit(self) -> None:
        gate = Gate(
            "database",
            [sys.executable, "-c", "raise SystemExit(0)"],
            Path.cwd(),
            True,
            "",
            prerequisite=lambda: "database unavailable",
        )
        result = run_gate(gate)
        self.assertEqual(BLOCKED, result.status)
        self.assertEqual(1, exit_status([result]))

    def test_configuration_routes_are_selected(self) -> None:
        paths = [
            "compose-dev.yaml",
            "Dockerfile.test",
            ".github/workflows/ci.yml",
            "scripts/acceptance/support/v090.database.yml",
        ]
        selection = select_surfaces(
            paths,
            all_selected=False,
            quality_only=False,
            user_visible=False,
        )
        self.assertTrue(selection.config)
        self.assertEqual(sorted(paths), config_paths(paths))

    def test_config_only_selects_no_runtime_gate(self) -> None:
        selection = select_surfaces(
            [],
            all_selected=False,
            quality_only=False,
            config_only=True,
            user_visible=False,
        )
        self.assertTrue(selection.config)
        self.assertFalse(selection.quality)
        self.assertFalse(selection.server)
        self.assertFalse(selection.web)

    def test_integration_fixture_selects_migration_and_integration(self) -> None:
        selection = select_surfaces(
            ["apps/server/tests/integration/conftest.py"],
            all_selected=False,
            quality_only=False,
            user_visible=False,
        )
        self.assertTrue(selection.integration)
        self.assertTrue(selection.migration)

    def test_malformed_compose_yaml_is_rejected(self) -> None:
        paths = (
            "compose.yaml",
            "scripts/acceptance/support/v090.database.yml",
        )
        for path in paths:
            with self.subTest(path=path):
                errors = content_errors(path, "services:\n  web: [\n")
                self.assertTrue(any("invalid YAML" in error for error in errors))

    def test_malformed_workflow_yaml_is_rejected(self) -> None:
        text = "on:\n  push:\njobs:\n  build: [\n"
        errors = content_errors(".github/workflows/ci.yml", text)
        self.assertTrue(any("invalid YAML" in error for error in errors))


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    _pattern: str | None,
) -> unittest.TestSuite:
    standard_tests.addTests(loader.loadTestsFromModule(selftest_git))
    return standard_tests


if __name__ == "__main__":
    unittest.main(verbosity=2)

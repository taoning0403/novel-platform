#!/usr/bin/env python3
"""Run the quality ratchet against the current tree and a trusted Git revision."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from baseline_policy import (
    baseline_payload,
    comparison_failures,
    load_baseline,
    validate_baseline,
    write_baseline,
    write_regressions,
)
from policy_trust import policy_regressions, runtime_policy, trusted_policy
from quality_analysis import Analysis, analyze_sources
from quality_policy import EXIT_BLOCKED, EXIT_FAIL
from repository_snapshot import (
    commit_date,
    comparison_revision,
    current_sources,
    is_ancestor,
    repository_root,
    revision_sources,
    valid_revision,
)


@dataclass
class RunContext:
    root: Path
    baseline: Path
    reference_sha: str
    languages: set[str]
    policy_failures: list[str]
    current: Analysis
    reference: Analysis


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    root = repository_root(Path(__file__).parent)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=root)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path(__file__).parent.parent / "references/quality-baseline.json",
    )
    parser.add_argument("--base", help="Trusted comparison revision.")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument(
        "--language",
        choices=("all", "python", "typescript"),
        default="all",
    )
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--"]:
        arguments.pop(0)
    return parser.parse_args(arguments)


def selected_languages(value: str) -> set[str]:
    return {"python", "typescript"} if value == "all" else {value}


def baseline_path(root: Path, configured: Path) -> Path:
    return configured if configured.is_absolute() else root / configured


def build_context(args: argparse.Namespace) -> RunContext:
    root = args.repo_root.resolve()
    reference_sha = comparison_revision(root, args.base)
    current_policy = runtime_policy()
    policy_failures = policy_regressions(
        current_policy,
        trusted_policy(root, reference_sha, current_policy),
    )
    current_python, current_typescript = current_sources(root)
    old_python, old_typescript = revision_sources(root, reference_sha)
    languages = selected_languages(args.language)
    current = analyze_sources(root, current_python, current_typescript, languages)
    reference = analyze_sources(root, old_python, old_typescript, languages)
    return RunContext(
        root=root,
        baseline=baseline_path(root, args.baseline),
        reference_sha=reference_sha,
        languages=languages,
        policy_failures=policy_failures,
        current=current,
        reference=reference,
    )


def report_analysis_failures(context: RunContext) -> int | None:
    if context.current.failures:
        for failure in context.current.failures:
            print(f"[FAIL] {failure}")
        return EXIT_FAIL
    if context.reference.failures:
        for failure in context.reference.failures:
            print(f"[BLOCKED] comparison revision analysis: {failure}")
        return EXIT_BLOCKED
    return None


def handle_write(context: RunContext) -> int:
    failures = write_regressions(context.current, context.reference, context.languages)
    if failures:
        for failure in failures:
            print(f"[FAIL] refusing baseline rewrite: {failure}")
        return EXIT_FAIL
    payload = baseline_payload(
        context.reference_sha,
        commit_date(context.root, context.reference_sha),
        context.current,
    )
    write_baseline(context.baseline, payload)
    print(
        f"[PASS] wrote {len(context.current.violations)} reviewed violations "
        f"against {context.reference_sha[:12]}"
    )
    return 0


def handle_check(context: RunContext) -> int:
    data = load_baseline(context.baseline)
    stored_metrics, stored_edges, errors = validate_baseline(
        data,
        trusted_reference=context.reference_sha,
        commit_exists=lambda revision: valid_revision(context.root, revision),
        commit_date=lambda revision: commit_date(context.root, revision),
        commit_is_ancestor=lambda ancestor, reference: is_ancestor(
            context.root,
            ancestor,
            reference,
        ),
    )
    if errors:
        for error in errors:
            print(f"[BLOCKED] invalid quality baseline: {error}")
        return EXIT_BLOCKED
    failures = comparison_failures(
        context.current,
        context.reference,
        stored_metrics,
        stored_edges,
        context.languages,
    )
    if failures:
        for failure in failures:
            print(f"[FAIL] quality ratchet: {failure}")
        return EXIT_FAIL
    return report_success(context)


def report_success(context: RunContext) -> int:
    historical = len(context.current.violations)
    if historical:
        print(
            f"[BASELINE FAILURE] {historical} reviewed historical metrics remain "
            "above their targets without worsening"
        )
    print(
        f"[PASS] quality ratchet: {len(context.current.metrics)} metrics, "
        f"{historical} historical violations, 0 Python cycles, "
        "0 TypeScript cycles, 0 boundary violations"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.write_baseline and args.language != "all":
        print("[BLOCKED] --write-baseline requires --language all")
        return EXIT_BLOCKED
    try:
        context = build_context(args)
        if context.policy_failures:
            for failure in context.policy_failures:
                print(f"[FAIL] quality policy: {failure}")
            return EXIT_FAIL
        analysis_status = report_analysis_failures(context)
        if analysis_status is not None:
            return analysis_status
        return handle_write(context) if args.write_baseline else handle_check(context)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"[BLOCKED] quality analysis unavailable: {error}")
        return EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())

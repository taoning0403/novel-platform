#!/usr/bin/env python3
"""Route novel-platform verification checks from the changed file set."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from repository_changes import changed_files
from repository_snapshot import current_paths, repository_root
from verification_plan import build_plan
from verification_routing import config_paths, select_surfaces
from verification_runner import BLOCKED, exit_status, print_summary, run_gates


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quality-only", action="store_true")
    mode.add_argument("--config-only", action="store_true")
    parser.add_argument("--user-visible", action="store_true")
    parser.add_argument("--base", help="Trusted comparison revision.")
    parser.add_argument("--show-paths", action="store_true")
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--"]:
        arguments.pop(0)
    return parser.parse_args(arguments)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = repository_root(Path(__file__).parent)
    try:
        paths, reference = changed_files(root, args.base)
    except RuntimeError as error:
        print(f"[{BLOCKED}] change detection: {error}")
        return 2
    if args.config_only:
        paths = sorted(set(config_paths(paths)).union(config_paths(current_paths(root))))
    if args.show_paths:
        print("\n".join(paths))
    selection = select_surfaces(
        paths,
        all_selected=args.all and not (args.quality_only or args.config_only),
        quality_only=args.quality_only,
        config_only=args.config_only,
        user_visible=args.user_visible,
    )
    results = run_gates(build_plan(root, reference, paths, selection))
    print_summary(results)
    return exit_status(results)


if __name__ == "__main__":
    raise SystemExit(main())

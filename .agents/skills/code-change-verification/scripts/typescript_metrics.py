"""Invoke the repository TypeScript parser and normalize its metrics."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from quality_policy import THRESHOLDS, Metric


def invoke_typescript_parser(root: Path, sources: Mapping[str, str]) -> list[dict[str, Any]]:
    script = Path(__file__).with_name("ts_metrics.mjs")
    request = json.dumps({"sources": sources})
    result = subprocess.run(
        ["node", str(script), "--repo-root", str(root)],
        input=request,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(detail or f"TypeScript parser exited {result.returncode}")
    payload = json.loads(result.stdout)
    files = payload.get("files")
    if not isinstance(files, list):
        raise RuntimeError("TypeScript parser returned an invalid files payload")
    return files


def function_metrics(path: str, function: dict[str, Any]) -> list[Metric]:
    thresholds = THRESHOLDS["typescript"]
    symbol = str(function["symbol"])
    values = {
        "function_effective_lines": int(function["effective_lines"]),
        "cyclomatic_complexity": int(function["cyclomatic_complexity"]),
        "nesting_depth": int(function["nesting_depth"]),
    }
    return [
        Metric("typescript", path, symbol, name, value, thresholds[name])
        for name, value in values.items()
    ]


def normalize_metrics(files: list[dict[str, Any]]) -> list[Metric]:
    metrics: list[Metric] = []
    threshold = THRESHOLDS["typescript"]["file_effective_lines"]
    for file in files:
        path = str(file["path"])
        metrics.append(
            Metric(
                "typescript",
                path,
                "<file>",
                "file_effective_lines",
                int(file["effective_lines"]),
                threshold,
            )
        )
        for function in file.get("functions", []):
            metrics.extend(function_metrics(path, function))
    return metrics


def typescript_metrics(
    root: Path, sources: Mapping[str, str]
) -> tuple[list[Metric], list[dict[str, Any]]]:
    files = invoke_typescript_parser(root, sources)
    return normalize_metrics(files), files

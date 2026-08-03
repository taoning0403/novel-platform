"""Execute selected verification gates and preserve their status semantics."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
SKIPPED = "SKIPPED"
BASELINE_FAILURE = "BASELINE FAILURE"
BLOCKED = "BLOCKED"
FAILING_STATUSES = {FAIL, BLOCKED}


@dataclass
class Gate:
    name: str
    command: list[str]
    cwd: Path
    selected: bool
    skip_reason: str
    prerequisite: Callable[[], str | None] | None = None
    blocked_exit_codes: tuple[int, ...] = ()
    neutral_marker: str | None = None


@dataclass(frozen=True)
class GateResult:
    name: str
    status: str
    detail: str


def command_missing(command: list[str]) -> str | None:
    executable = command[0]
    return None if shutil.which(executable) else f"required executable is unavailable: {executable}"


def emit_output(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")


def execute(gate: Gate) -> subprocess.CompletedProcess[str]:
    capture = gate.neutral_marker is not None
    return subprocess.run(
        gate.command,
        cwd=gate.cwd,
        text=True,
        capture_output=capture,
        check=False,
    )


def completed_status(gate: Gate, result: subprocess.CompletedProcess[str]) -> tuple[str, str]:
    if result.returncode in gate.blocked_exit_codes:
        return BLOCKED, f"command blocked with status {result.returncode}"
    if result.returncode:
        return FAIL, f"command exited with status {result.returncode}"
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    if gate.neutral_marker and gate.neutral_marker in output:
        return BASELINE_FAILURE, "completed with reviewed historical debt"
    return PASS, "completed"


def run_gate(gate: Gate) -> GateResult:
    if not gate.selected:
        return GateResult(gate.name, SKIPPED, gate.skip_reason)
    prerequisite = gate.prerequisite() if gate.prerequisite else None
    if prerequisite:
        return GateResult(gate.name, BLOCKED, prerequisite)
    missing = command_missing(gate.command)
    if missing:
        return GateResult(gate.name, BLOCKED, missing)
    print(f"\n--- {gate.name} ---", flush=True)
    result = execute(gate)
    if gate.neutral_marker:
        emit_output(result)
    status, detail = completed_status(gate, result)
    return GateResult(gate.name, status, detail)


def run_gates(gates: list[Gate]) -> list[GateResult]:
    return [run_gate(gate) for gate in gates]


def print_summary(results: list[GateResult]) -> None:
    print("\nVerification summary")
    for result in results:
        print(f"[{result.status}] {result.name}: {result.detail}")


def exit_status(results: list[GateResult]) -> int:
    return 1 if any(result.status in FAILING_STATUSES for result in results) else 0

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from python_inventory import build_python_inventory


@dataclass(frozen=True)
class AreaSpec:
    name: str
    relative_path: str
    extensions: tuple[str, ...]


@dataclass(frozen=True)
class FileRecord:
    area: str
    path: str
    lines: int
    bytes: int


AREA_SPECS = (
    AreaSpec("server-source", "apps/server/src", (".py",)),
    AreaSpec("server-tests", "apps/server/tests", (".py",)),
    AreaSpec("server-migrations", "apps/server/migrations", (".py",)),
    AreaSpec("web-source", "apps/web/src", (".ts", ".tsx", ".js", ".jsx", ".css")),
    AreaSpec("web-tests", "apps/web/tests", (".ts", ".tsx", ".js", ".jsx")),
    AreaSpec("api-contract", "packages/api-client", (".json", ".ts")),
    AreaSpec("repository-scripts", "scripts", (".py", ".js", ".mjs", ".sh")),
)

EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "artifacts",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
        "output",
    }
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(
        description="Read source files and print a deterministic Novel Platform inventory."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=default_root,
        help="repository root; defaults to the root containing this skill",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="number of largest files and longest Python functions to print",
    )
    return parser.parse_args(argv)


def validate_root(root: Path) -> Path:
    resolved = root.resolve()
    if not (resolved / "AGENTS.md").is_file() or not (resolved / "apps").is_dir():
        raise SystemExit(f"not a Novel Platform repository root: {resolved}")
    return resolved


def is_included(path: Path, extensions: tuple[str, ...]) -> bool:
    return path.suffix.lower() in extensions and not EXCLUDED_PARTS.intersection(path.parts)


def iter_area_files(root: Path, spec: AreaSpec) -> Iterable[Path]:
    area_root = root / spec.relative_path
    if not area_root.exists():
        return ()
    if area_root.is_file():
        return (area_root,) if is_included(area_root, spec.extensions) else ()
    return (
        path
        for path in sorted(area_root.rglob("*"))
        if path.is_file() and is_included(path.relative_to(root), spec.extensions)
    )


def physical_lines(content: bytes) -> int:
    if not content:
        return 0
    return content.count(b"\n") + (0 if content.endswith(b"\n") else 1)


def collect_files(root: Path) -> tuple[list[FileRecord], dict[Path, str]]:
    records: list[FileRecord] = []
    python_sources: dict[Path, str] = {}
    for spec in AREA_SPECS:
        for path in iter_area_files(root, spec):
            content = path.read_bytes()
            relative = path.relative_to(root).as_posix()
            records.append(
                FileRecord(
                    area=spec.name,
                    path=relative,
                    lines=physical_lines(content),
                    bytes=len(content),
                )
            )
            if spec.name == "server-source" and path.suffix == ".py":
                python_sources[path] = content.decode("utf-8")
    return sorted(records, key=lambda item: item.path), python_sources


def _area_counts(files: list[FileRecord]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for spec in AREA_SPECS:
        area_files = [record for record in files if record.area == spec.name]
        counts[spec.name] = {
            "files": len(area_files),
            "lines": sum(record.lines for record in area_files),
            "bytes": sum(record.bytes for record in area_files),
        }
    return counts


def build_inventory(root: Path) -> dict[str, object]:
    files, python_sources = collect_files(root)
    return {
        "repository": root.as_posix(),
        "areas": _area_counts(files),
        "files": [asdict(record) for record in files],
        "python": build_python_inventory(root, python_sources),
    }


def _print_areas(areas: object) -> None:
    assert isinstance(areas, dict)
    print("areas:")
    for name in sorted(areas):
        metrics = areas[name]
        assert isinstance(metrics, dict)
        print(
            f"  {name}: files={metrics['files']} lines={metrics['lines']} bytes={metrics['bytes']}"
        )


def _print_largest_files(files: object, top: int) -> None:
    assert isinstance(files, list)
    largest = sorted(files, key=lambda item: (-item["lines"], item["path"]))[:top]
    print(f"largest files (top {top}):")
    for item in largest:
        print(f"  {item['lines']:6}  {item['area']:20}  {item['path']}")


def _print_python_imports(python: object) -> None:
    assert isinstance(python, dict)
    print(
        "python imports: "
        f"modules={python['modules']} edges={python['import_edges']} "
        f"cycles={len(python['cycles'])}"
    )
    layer_edges = python["layer_edges"]
    assert isinstance(layer_edges, dict)
    for edge, count in sorted(layer_edges.items()):
        print(f"  {edge:32} {count:4}")
    for cycle in python["cycles"]:
        print(f"  cycle: {' -> '.join(cycle)}")


def _print_longest_functions(python: object, top: int) -> None:
    assert isinstance(python, dict)
    functions = python["functions"]
    assert isinstance(functions, list)
    longest = sorted(
        functions,
        key=lambda item: (
            -item["lines"],
            -item["decision_points"],
            item["path"],
            item["line"],
        ),
    )[:top]
    print(f"longest Python functions (top {top}):")
    for item in longest:
        print(
            f"  {item['lines']:4} lines  decisions={item['decision_points']:2}  "
            f"{item['path']}:{item['line']}  {item['name']}"
        )


def print_text(inventory: dict[str, object], top: int) -> None:
    print(f"repository: {inventory['repository']}")
    _print_areas(inventory["areas"])
    _print_largest_files(inventory["files"], top)
    _print_python_imports(inventory["python"])
    _print_longest_functions(inventory["python"], top)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.top < 1:
        raise SystemExit("--top must be at least 1")
    try:
        ast.parse("type _InventoryAlias = int")
    except SyntaxError:
        raise SystemExit(
            "source_inventory.py requires Python 3.12 or newer to parse the Server source; "
            "use the existing apps/server/.venv interpreter without installing dependencies"
        ) from None
    root = validate_root(args.root)
    inventory = build_inventory(root)
    if args.format == "json":
        print(json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_text(inventory, args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

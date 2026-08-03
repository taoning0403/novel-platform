from __future__ import annotations

import ast
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class FunctionRecord:
    path: str
    line: int
    name: str
    lines: int
    decision_points: int


class DecisionCounter(ast.NodeVisitor):
    """Count control-flow decisions without descending into nested functions."""

    def __init__(self) -> None:
        self.count = 1

    def visit_If(self, node: ast.If) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.count += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self.count += len(node.handlers)
        self.generic_visit(node)

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self.count += len(node.handlers)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.count += 1 + len(node.ifs)
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self.count += max(0, len(node.cases) - 1)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


def function_decision_points(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    counter = DecisionCounter()
    for statement in node.body:
        counter.visit(statement)
    return counter.count


def collect_functions(root: Path, python_sources: dict[Path, str]) -> list[FunctionRecord]:
    records: list[FunctionRecord] = []
    for path in sorted(python_sources):
        tree = ast.parse(python_sources[path], filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            end_line = node.end_lineno or node.lineno
            records.append(
                FunctionRecord(
                    path=path.relative_to(root).as_posix(),
                    line=node.lineno,
                    name=node.name,
                    lines=end_line - node.lineno + 1,
                    decision_points=function_decision_points(node),
                )
            )
    return sorted(records, key=lambda item: (item.path, item.line, item.name))


def module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root / "apps/server/src")
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def resolve_import(
    *,
    current_module: str,
    current_is_package: bool,
    imported_module: str | None,
    level: int,
    known_modules: set[str],
) -> str | None:
    if level:
        package = current_module.split(".")
        if not current_is_package:
            package.pop()
        ascend = level - 1
        if ascend > len(package):
            return None
        package = package[: len(package) - ascend]
        if imported_module:
            package.extend(imported_module.split("."))
        candidate = ".".join(package)
    else:
        candidate = imported_module or ""

    while candidate:
        if candidate in known_modules:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


def _from_import_candidate(node: ast.ImportFrom, alias: ast.alias) -> str | None:
    if alias.name == "*":
        return node.module
    if node.module:
        return f"{node.module}.{alias.name}"
    return alias.name


def _import_candidates(node: ast.AST) -> tuple[tuple[str | None, int], ...]:
    if isinstance(node, ast.Import):
        return tuple((alias.name, 0) for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return ()
    return tuple((_from_import_candidate(node, alias), node.level) for alias in node.names)


def _module_dependencies(
    *,
    path: Path,
    source: str,
    source_module: str,
    known_modules: set[str],
) -> set[str]:
    dependencies: set[str] = set()
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        for imported_module, level in _import_candidates(node):
            target = resolve_import(
                current_module=source_module,
                current_is_package=path.name == "__init__.py",
                imported_module=imported_module,
                level=level,
                known_modules=known_modules,
            )
            if target and target != source_module:
                dependencies.add(target)
    return dependencies


def python_import_graph(
    root: Path,
    python_sources: dict[Path, str],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    path_to_module = {path: module_name(root, path) for path in python_sources}
    module_to_path = {module: path for path, module in path_to_module.items()}
    known_modules = set(module_to_path)
    graph: dict[str, list[str]] = {}
    for path in sorted(python_sources):
        source_module = path_to_module[path]
        dependencies = _module_dependencies(
            path=path,
            source=python_sources[path],
            source_module=source_module,
            known_modules=known_modules,
        )
        graph[path.relative_to(root).as_posix()] = sorted(
            module_to_path[target].relative_to(root).as_posix() for target in dependencies
        )
    modules = {path.relative_to(root).as_posix(): module for path, module in path_to_module.items()}
    return graph, modules


class _ComponentFinder:
    def __init__(self, graph: dict[str, list[str]]) -> None:
        self.graph = graph
        self.index = 0
        self.stack: list[str] = []
        self.on_stack: set[str] = set()
        self.indices: dict[str, int] = {}
        self.low_links: dict[str, int] = {}
        self.components: list[list[str]] = []

    def find(self) -> list[list[str]]:
        for node in sorted(self.graph):
            if node not in self.indices:
                self._visit(node)
        return sorted(
            (component for component in self.components if len(component) > 1),
            key=lambda item: item[0],
        )

    def _visit(self, node: str) -> None:
        self.indices[node] = self.index
        self.low_links[node] = self.index
        self.index += 1
        self.stack.append(node)
        self.on_stack.add(node)
        for dependency in self.graph.get(node, []):
            if dependency not in self.graph:
                continue
            if dependency not in self.indices:
                self._visit(dependency)
                self.low_links[node] = min(self.low_links[node], self.low_links[dependency])
            elif dependency in self.on_stack:
                self.low_links[node] = min(self.low_links[node], self.indices[dependency])
        if self.low_links[node] == self.indices[node]:
            self._finish_component(node)

    def _finish_component(self, root: str) -> None:
        component: list[str] = []
        while True:
            member = self.stack.pop()
            self.on_stack.remove(member)
            component.append(member)
            if member == root:
                break
        self.components.append(sorted(component))


def strongly_connected_components(graph: dict[str, list[str]]) -> list[list[str]]:
    return _ComponentFinder(graph).find()


def module_layer(module: str) -> str:
    parts = module.split(".")
    if len(parts) > 1 and parts[1] in {
        "api",
        "application",
        "domain",
        "infrastructure",
        "worker",
    }:
        return parts[1]
    return "root"


def _layer_edges(graph: dict[str, list[str]], modules: dict[str, str]) -> dict[str, int]:
    edges: Counter[str] = Counter()
    for source, dependencies in graph.items():
        source_layer = module_layer(modules[source])
        for dependency in dependencies:
            target_layer = module_layer(modules[dependency])
            edges[f"{source_layer}->{target_layer}"] += 1
    return dict(sorted(edges.items()))


def build_python_inventory(root: Path, python_sources: dict[Path, str]) -> dict[str, object]:
    functions = collect_functions(root, python_sources)
    graph, modules = python_import_graph(root, python_sources)
    return {
        "modules": len(graph),
        "import_edges": sum(len(dependencies) for dependencies in graph.values()),
        "cycles": strongly_connected_components(graph),
        "layer_edges": _layer_edges(graph, modules),
        "functions": [asdict(record) for record in functions],
    }

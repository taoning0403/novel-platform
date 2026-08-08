"""Build local import graphs and enforce the modular-monolith boundaries."""

from __future__ import annotations

import ast
import importlib.util
import posixpath
from pathlib import PurePosixPath

from quality_policy import ALLOWED_EDGES, REVERSE_EDGE_NAMES, in_layer

SERVER_PREFIX = PurePosixPath("apps/server/src")
DOMAIN = "novel_platform.domain"
APPLICATION = "novel_platform.application"
INFRASTRUCTURE = "novel_platform.infrastructure"
API = "novel_platform.api"


def module_for_path(path: str) -> str:
    module_path = PurePosixPath(path).relative_to(SERVER_PREFIX).with_suffix("")
    parts = list(module_path.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def python_modules(trees: dict[str, ast.AST]) -> dict[str, str]:
    return {
        module_for_path(path): path
        for path in trees
        if path.startswith("apps/server/src/novel_platform/")
    }


def nearest_module(name: str, modules: set[str]) -> str | None:
    candidate = name
    while candidate:
        if candidate in modules:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


def current_package(path: str, module: str) -> str:
    return module if path.endswith("/__init__.py") else module.rpartition(".")[0]


def from_import_base(node: ast.ImportFrom, package: str) -> str | None:
    base = node.module or ""
    if not node.level:
        return base
    try:
        return importlib.util.resolve_name("." * node.level + base, package)
    except (ImportError, ValueError):
        return None


def from_import_candidates(node: ast.ImportFrom, package: str) -> list[str]:
    base = from_import_base(node, package)
    if base is None:
        return []
    candidates: list[str] = []
    for alias in node.names:
        if alias.name == "*":
            if base:
                candidates.append(base)
        else:
            candidates.append(f"{base}.{alias.name}" if base else alias.name)
    return candidates


def import_candidates(tree: ast.AST, package: str) -> list[str]:
    candidates: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            candidates.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            candidates.extend(from_import_candidates(node, package))
    return candidates


def python_import_graph(
    trees: dict[str, ast.AST],
) -> dict[str, set[str]]:
    modules_to_paths = python_modules(trees)
    module_names = set(modules_to_paths)
    graph: dict[str, set[str]] = {module: set() for module in module_names}
    for source, path in modules_to_paths.items():
        package = current_package(path, source)
        for candidate in import_candidates(trees[path], package):
            target = nearest_module(candidate, module_names)
            if target:
                graph[source].add(target)
    return graph


def skill_script_groups(trees: dict[str, ast.AST]) -> dict[str, dict[str, str]]:
    groups: dict[str, dict[str, str]] = {}
    for path in trees:
        if not path.startswith(".agents/skills/") or "/scripts/" not in path:
            continue
        parent = str(PurePosixPath(path).parent)
        groups.setdefault(parent, {})[PurePosixPath(path).stem] = path
    return groups


def skill_import_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.lstrip(".").split(".", 1)[0])
    return names


def skill_script_import_graph(trees: dict[str, ast.AST]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for modules in skill_script_groups(trees).values():
        graph.update({path: set() for path in modules.values()})
        for source_name, source_path in modules.items():
            for imported_name in skill_import_names(trees[source_path]):
                target = modules.get(imported_name)
                if target:
                    graph[source_path].add(target)
            if source_name == "__init__":
                graph.setdefault(source_path, set())
    return graph


def resolve_typescript_specifier(source: str, specifier: str, paths: set[str]) -> str | None:
    if specifier == "@novel-platform/api-client":
        base = "packages/api-client/src/index"
    elif specifier.startswith("@novel-platform/api-client/"):
        suffix = specifier.removeprefix("@novel-platform/api-client/")
        base = f"packages/api-client/src/{suffix}"
    elif specifier.startswith("."):
        base = posixpath.join(str(PurePosixPath(source).parent), specifier)
    else:
        return None
    normalized = posixpath.normpath(base)
    candidates = (
        normalized,
        f"{normalized}.ts",
        f"{normalized}.tsx",
        f"{normalized}.d.ts",
        f"{normalized}/index.ts",
        f"{normalized}/index.tsx",
    )
    return next((candidate for candidate in candidates if candidate in paths), None)


def typescript_import_graph(files: list[dict[str, object]]) -> dict[str, set[str]]:
    paths = {str(file["path"]) for file in files}
    graph: dict[str, set[str]] = {path: set() for path in paths}
    for file in files:
        source = str(file["path"])
        for specifier in file.get("imports", []):
            target = resolve_typescript_specifier(source, str(specifier), paths)
            if target:
                graph[source].add(target)
    return graph


def strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def connect(node: str) -> None:
        indexes[node] = len(indexes)
        lowlinks[node] = indexes[node]
        stack.append(node)
        on_stack.add(node)
        visit_targets(node)
        if lowlinks[node] == indexes[node]:
            finish_component(node)

    def visit_targets(node: str) -> None:
        for target in graph.get(node, set()):
            if target not in indexes:
                connect(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indexes[target])

    def finish_component(node: str) -> None:
        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        if len(component) > 1 or node in graph.get(node, set()):
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in indexes:
            connect(node)
    return sorted(components)


def boundary_failure(source: str, target: str) -> str | None:
    return (
        domain_boundary_failure(source, target)
        or infrastructure_boundary_failure(source, target)
        or application_boundary_failure(source, target)
    )


def domain_boundary_failure(source: str, target: str) -> str | None:
    if in_layer(source, DOMAIN) and not in_layer(target, DOMAIN):
        return f"domain reverse dependency: {source} -> {target}"
    return None


def infrastructure_boundary_failure(source: str, target: str) -> str | None:
    allowed = {(edge["from"], edge["to"]) for edge in ALLOWED_EDGES}
    if not in_layer(source, INFRASTRUCTURE):
        return None
    if in_layer(target, APPLICATION) and (source, target) not in allowed:
        return f"unapproved infrastructure-to-application edge: {source} -> {target}"
    if in_layer(target, API):
        return f"infrastructure-to-API edge: {source} -> {target}"
    return None


def application_boundary_failure(source: str, target: str) -> str | None:
    if in_layer(source, APPLICATION) and in_layer(target, API):
        return f"application-to-API edge: {source} -> {target}"
    return None


def python_boundary_failures(graph: dict[str, set[str]]) -> list[str]:
    failures = (
        boundary_failure(source, target) for source, targets in graph.items() for target in targets
    )
    return sorted(failure for failure in failures if failure)


def edge_records(
    graph: dict[str, set[str]], source_layer: str, target_layer: str
) -> list[dict[str, str]]:
    pairs = sorted(
        (source, target)
        for source, targets in graph.items()
        for target in targets
        if in_layer(source, source_layer) and in_layer(target, target_layer)
    )
    return [{"from": source, "to": target} for source, target in pairs]


def reverse_edges(graph: dict[str, set[str]]) -> dict[str, list[dict[str, str]]]:
    result = {
        "application_to_infrastructure": edge_records(graph, APPLICATION, INFRASTRUCTURE),
        "api_to_infrastructure": edge_records(graph, API, INFRASTRUCTURE),
    }
    assert set(result) == set(REVERSE_EDGE_NAMES)
    return result


def cycle_failures(label: str, graph: dict[str, set[str]]) -> list[str]:
    return [
        f"{label} import cycle: {' -> '.join(component)}"
        for component in strongly_connected_components(graph)
    ]

"""Collect Python size, complexity, and nesting metrics."""

from __future__ import annotations

import ast
import io
import tokenize
from collections.abc import Iterable, Mapping

from quality_policy import THRESHOLDS, Metric

IGNORED_TOKENS = {
    tokenize.ENCODING,
    tokenize.ENDMARKER,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.NEWLINE,
    tokenize.NL,
    tokenize.COMMENT,
}

NESTING_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.TryStar,
    ast.With,
    ast.AsyncWith,
    ast.Match,
)

FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


class PythonComplexity(ast.NodeVisitor):
    def __init__(self) -> None:
        self.value = 1

    def _branch(self, node: ast.AST, increment: int = 1) -> None:
        self.value += increment
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self._branch(node)

    def visit_For(self, node: ast.For) -> None:
        self._branch(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._branch(node)

    def visit_While(self, node: ast.While) -> None:
        self._branch(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._branch(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self._branch(node, max(0, len(node.values) - 1))

    def visit_Try(self, node: ast.Try) -> None:
        self._branch(node, len(node.handlers))

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self._branch(node, len(node.handlers))

    def visit_Match(self, node: ast.Match) -> None:
        self._branch(node, len(node.cases))

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self._branch(node, 1 + len(node.ifs))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


def token_lines(source: str) -> set[int]:
    lines: set[int] = set()
    tokens = tokenize.tokenize(io.BytesIO(source.encode("utf-8")).readline)
    for token in tokens:
        if token.type not in IGNORED_TOKENS:
            lines.update(range(token.start[0], token.end[0] + 1))
    return lines


def docstring_lines(tree: ast.AST) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if is_docstring(first):
            lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def is_docstring(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def code_lines(source: str, tree: ast.AST) -> set[int]:
    return token_lines(source) - docstring_lines(tree)


def function_nodes(
    tree: ast.AST,
) -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    def walk(
        node: ast.AST, scope: tuple[str, ...]
    ) -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from walk(child, (*scope, child.name))
            elif isinstance(child, FUNCTION_NODES):
                symbol = ".".join((*scope, child.name))
                yield symbol, child
                yield from walk(child, (*scope, child.name))
            else:
                yield from walk(child, scope)

    return walk(tree, ())


def function_complexity(function: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    visitor = PythonComplexity()
    for statement in function.body:
        visitor.visit(statement)
    return visitor.value


def function_nesting(function: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    maximum = 0

    def walk(node: ast.AST, depth: int) -> None:
        nonlocal maximum
        if isinstance(node, SCOPE_NODES):
            return
        child_depth = depth + 1 if isinstance(node, NESTING_NODES) else depth
        maximum = max(maximum, child_depth)
        for child in ast.iter_child_nodes(node):
            walk(child, child_depth)

    for statement in function.body:
        walk(statement, 0)
    return maximum


def function_metrics(
    path: str,
    symbol: str,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: set[int],
) -> list[Metric]:
    thresholds = THRESHOLDS["python"]
    end = function.end_lineno or function.lineno
    effective = sum(line in lines for line in range(function.lineno, end + 1))
    values = {
        "function_effective_lines": effective,
        "cyclomatic_complexity": function_complexity(function),
        "nesting_depth": function_nesting(function),
    }
    return [
        Metric("python", path, symbol, name, value, thresholds[name])
        for name, value in values.items()
    ]


def file_metrics(path: str, source: str) -> tuple[list[Metric], ast.AST]:
    tree = ast.parse(source, filename=path)
    lines = code_lines(source, tree)
    threshold = THRESHOLDS["python"]["file_effective_lines"]
    metrics = [Metric("python", path, "<file>", "file_effective_lines", len(lines), threshold)]
    for symbol, function in function_nodes(tree):
        metrics.extend(function_metrics(path, symbol, function, lines))
    return metrics, tree


def python_metrics(
    sources: Mapping[str, str],
) -> tuple[list[Metric], dict[str, ast.AST], list[str]]:
    metrics: list[Metric] = []
    trees: dict[str, ast.AST] = {}
    failures: list[str] = []
    for path, source in sorted(sources.items()):
        try:
            file_result, tree = file_metrics(path, source)
        except (SyntaxError, tokenize.TokenError) as error:
            failures.append(f"{path}: {error}")
            continue
        metrics.extend(file_result)
        trees[path] = tree
    return metrics, trees, failures

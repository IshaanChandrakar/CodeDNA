"""Shared safe integer arithmetic, fresh syntax cloning, and pass reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
from types import MappingProxyType
from typing import Literal, Mapping

from compiler import ast_nodes as ast
from compiler.diagnostics import SemanticError
from compiler.semantic import INT_MAX, INT_MIN, analyze


MAX_UNROLL_LIMIT = 1024
Status = Literal["applied", "not_applicable", "rejected"]


@dataclass(frozen=True, slots=True)
class Statistics:
    expressions_folded: int = 0
    references_propagated: int = 0
    loops_unrolled: int = 0
    iterations_expanded: int = 0
    changed_nodes: int = 0


@dataclass(frozen=True, slots=True)
class Decision:
    node_id: str
    code: str
    message: str
    status: Literal["not_applicable", "rejected"]
    span: ast.SourceSpan


@dataclass(frozen=True, slots=True)
class TransformationReport:
    name: str
    version: str
    status: Status
    parameters: tuple[tuple[str, int | str], ...]
    statistics: Statistics
    decisions: tuple[Decision, ...]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "parameters": dict(self.parameters),
            "statistics": asdict(self.statistics),
            "decisions": [asdict(decision) for decision in self.decisions],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True, slots=True)
class TransformationResult:
    program: ast.Program
    report: TransformationReport
    origins: Mapping[str, str]


class CloneFactory:
    """Rebuild every AST node, preserving IDs or allocating unique clone IDs.

    Keeping IDs for one-to-one rewrites makes stable repeated passes possible.
    Duplicated subtrees use fresh IDs; spans still refer to the input source.
    """

    def __init__(self, program: ast.Node) -> None:
        self._reserved = {node.node_id for node in ast.walk(program)}
        self._next_id = 0
        self.origins: dict[str, str] = {}

    def metadata(self, node: ast.Node, *, fresh_id: bool = False) -> dict:
        node_id = node.node_id
        if fresh_id:
            while f"u{self._next_id}" in self._reserved:
                self._next_id += 1
            node_id = f"u{self._next_id}"
            self._next_id += 1
            self._reserved.add(node_id)
        self.origins[node_id] = node.node_id
        return {"node_id": node_id, "span": node.span}

    def clone(self, node: ast.Node, *, fresh_ids: bool = False):
        def copy(value):
            if isinstance(value, ast.Node):
                return self.clone(value, fresh_ids=fresh_ids)
            if isinstance(value, tuple):
                return tuple(copy(item) for item in value)
            return value

        values = {field.name: copy(getattr(node, field.name)) for field in fields(node)
                  if field.name not in {"node_id", "span"}}
        return type(node)(**self.metadata(node, fresh_id=fresh_ids), **values)


def _in_range(value: int) -> bool:
    return type(value) is int and INT_MIN <= value <= INT_MAX


def evaluate_unary(operator: ast.UnaryOperator, value: int) -> int | None:
    """Return the defined signed-32 result, or None for an unsafe operation."""
    if not _in_range(value):
        return None
    if operator == ast.UnaryOperator.POSITIVE:
        return value
    if operator == ast.UnaryOperator.NEGATIVE:
        result = -value
        return result if _in_range(result) else None
    return None


def evaluate_binary(operator: ast.BinaryOperator, left: int, right: int) -> int | None:
    """Integer-only C division/remainder; never Python's signed floor division."""
    if not _in_range(left) or not _in_range(right):
        return None
    if operator in (ast.BinaryOperator.DIVIDE, ast.BinaryOperator.REMAINDER):
        if right == 0 or (left == INT_MIN and right == -1):
            return None
        quotient = abs(left) // abs(right)
        if (left < 0) != (right < 0):
            quotient = -quotient
        return quotient if operator == ast.BinaryOperator.DIVIDE else left - quotient * right
    if operator == ast.BinaryOperator.ADD:
        result = left + right
    elif operator == ast.BinaryOperator.SUBTRACT:
        result = left - right
    elif operator == ast.BinaryOperator.MULTIPLY:
        result = left * right
    elif operator == ast.BinaryOperator.LESS:
        result = int(left < right)
    elif operator == ast.BinaryOperator.LESS_EQUAL:
        result = int(left <= right)
    elif operator == ast.BinaryOperator.GREATER:
        result = int(left > right)
    elif operator == ast.BinaryOperator.GREATER_EQUAL:
        result = int(left >= right)
    elif operator == ast.BinaryOperator.EQUAL:
        result = int(left == right)
    elif operator == ast.BinaryOperator.NOT_EQUAL:
        result = int(left != right)
    else:
        return None
    return result if _in_range(result) else None


def evaluate_constant(expression: ast.Expression) -> int | None:
    """Evaluate only fully constant, defined expressions; never remove reads."""
    if isinstance(expression, ast.IntegerLiteral):
        return expression.value if _in_range(expression.value) else None
    if isinstance(expression, ast.UnaryExpression):
        operand = evaluate_constant(expression.operand)
        return None if operand is None else evaluate_unary(expression.operator, operand)
    if isinstance(expression, ast.BinaryExpression):
        left = evaluate_constant(expression.left)
        right = evaluate_constant(expression.right)
        return None if left is None or right is None else evaluate_binary(expression.operator, left, right)
    return None


def _retained_origins(program: ast.Program, origins: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType({node.node_id: origins.get(node.node_id, node.node_id) for node in ast.walk(program)})


def finish_result(
    original: ast.Program,
    candidate: ast.Program,
    *,
    name: str,
    statistics: Statistics,
    decisions: tuple[Decision, ...] = (),
    parameters: tuple[tuple[str, int | str], ...] = (),
    origins: Mapping[str, str] | None = None,
) -> TransformationResult:
    """Revalidate every candidate and commit only valid transformed syntax.

    Revalidation can expose undefined arithmetic hidden by conservative loop
    facts in the original. A failed candidate rolls the entire pass back to a
    fresh original, with zero committed-change statistics and a rejection.
    """
    decisions = tuple(decisions)
    try:
        analyze(candidate)
    except SemanticError as error:
        factory = CloneFactory(original)
        preserved = factory.clone(original)
        decision = Decision(
            original.node_id, "REVALIDATION_FAILED",
            f"Candidate rejected by semantic validation: {error.diagnostic.code}: {error.diagnostic.message}",
            "rejected", error.diagnostic.span,
        )
        report = TransformationReport(name, "1", "rejected", tuple(parameters), Statistics(), (*decisions, decision))
        return TransformationResult(preserved, report, _retained_origins(preserved, factory.origins))
    if candidate != original:
        status: Status = "applied"
    elif any(decision.status == "rejected" for decision in decisions):
        status = "rejected"
    else:
        status = "not_applicable"
        if not decisions:
            decisions = (Decision(
                original.node_id, "NO_APPLICABLE_CHANGE", "No eligible change was found for this pass",
                "not_applicable", original.span,
            ),)
    report = TransformationReport(name, "1", status, tuple(parameters), statistics, decisions)
    return TransformationResult(candidate, report, _retained_origins(candidate, origins or {}))

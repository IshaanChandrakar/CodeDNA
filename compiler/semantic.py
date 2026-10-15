"""Lexical binding and conservative semantic checks, without rewriting syntax.

Known constants support diagnostics only. They are not an optimization pass and
are deliberately forgotten at loop writes and disagreeing control-flow joins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from compiler.ast_nodes import (
    Assignment, BinaryExpression, BinaryOperator, Block, Declaration,
    EmptyStatement, Expression, For, Identifier, If, IntegerLiteral, Node,
    Program, Return, SourceSpan, Statement, UnaryExpression, UnaryOperator, walk,
)
from compiler.diagnostics import Diagnostic, SemanticError


INT_MIN = -(2**31)
INT_MAX = 2**31 - 1


@dataclass(frozen=True, slots=True)
class Symbol:
    symbol_id: str
    name: str
    declaration_id: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class SemanticAnalysis:
    symbols: tuple[Symbol, ...]
    bindings: Mapping[str, Symbol]
    diagnostics: tuple[Diagnostic, ...]
    unreachable_node_ids: frozenset[str]


def _error(code: str, message: str, node: Node) -> None:
    raise SemanticError(Diagnostic("semantic", code, message, node.span))


class _Binder:
    """Resolve every syntactic reference, including unreachable source."""

    def __init__(self) -> None:
        self.symbols: list[Symbol] = []
        self.bindings: dict[str, Symbol] = {}
        self.scopes: list[dict[str, Symbol]] = []
        self.declared_names: set[str] = set()

    def expression(self, node: Expression) -> None:
        if isinstance(node, Identifier):
            for scope in reversed(self.scopes):
                if node.name in scope:
                    self.bindings[node.node_id] = scope[node.name]
                    return
            _error("UNDECLARED_VARIABLE", f"Variable {node.name!r} is undeclared or outside its scope", node)
        elif isinstance(node, UnaryExpression):
            self.expression(node.operand)
        elif isinstance(node, BinaryExpression):
            self.expression(node.left)
            self.expression(node.right)

    def statement(self, node: Declaration | Statement) -> None:
        if isinstance(node, Block):
            self.scopes.append({})
            for item in node.items:
                self.statement(item)
            self.scopes.pop()
        elif isinstance(node, Declaration):
            if node.name in self.declared_names:
                _error("DUPLICATE_DECLARATION", f"Variable {node.name!r} is already declared in main; shadowing is unsupported", node)
            symbol = Symbol(f"s{len(self.symbols)}", node.name, node.node_id, node.span)
            self.symbols.append(symbol)
            self.declared_names.add(node.name)
            self.scopes[-1][node.name] = symbol
            self.bindings[node.node_id] = symbol
            if node.initializer is not None:
                self.expression(node.initializer)
        elif isinstance(node, Assignment):
            self.expression(node.target)
            self.expression(node.value)
        elif isinstance(node, Return):
            self.expression(node.value)
        elif isinstance(node, If):
            self.expression(node.condition)
            self.statement(node.then_branch)
            if node.else_branch is not None:
                self.statement(node.else_branch)
        elif isinstance(node, For):
            self.scopes.append({})
            self.statement(node.initializer)
            self.expression(node.condition)
            # Header references cannot see declarations in the loop body.
            self.statement(node.update)
            self.statement(node.body)
            self.scopes.pop()


@dataclass(slots=True)
class _State:
    initialized: set[str] = field(default_factory=set)
    constants: dict[str, int] = field(default_factory=dict)

    def copy(self) -> _State:
        return _State(self.initialized.copy(), self.constants.copy())


@dataclass(slots=True)
class _Flow:
    state: _State
    falls_through: bool = True


class _Checker:
    def __init__(self, bindings: Mapping[str, Symbol]) -> None:
        self.bindings = bindings
        self.diagnostics: list[Diagnostic] = []
        self.unreachable: set[str] = set()

    def dead(self, node: Node) -> None:
        self.unreachable.update(child.node_id for child in walk(node))
        self.diagnostics.append(Diagnostic(
            "semantic", "UNREACHABLE_STATEMENT", "Statement cannot be reached after an unconditional return",
            node.span, "warning",
        ))

    def checked_integer(self, value: int, node: Node) -> int:
        if not INT_MIN <= value <= INT_MAX:
            _error("INTEGER_OVERFLOW", "Statically known arithmetic exceeds the signed 32-bit int range", node)
        return value

    def expression(self, node: Expression, state: _State) -> int | None:
        if isinstance(node, IntegerLiteral):
            return self.checked_integer(node.value, node)
        if isinstance(node, Identifier):
            symbol = self.bindings[node.node_id]
            if symbol.symbol_id not in state.initialized:
                _error("UNINITIALIZED_VARIABLE", f"Variable {symbol.name!r} is not definitely initialized before this read", node)
            return state.constants.get(symbol.symbol_id)
        if isinstance(node, UnaryExpression):
            operand = self.expression(node.operand, state)
            if operand is None:
                return None
            return self.checked_integer(-operand if node.operator == UnaryOperator.NEGATIVE else operand, node)
        if not isinstance(node, BinaryExpression):
            raise TypeError(f"Unsupported expression node: {type(node).__name__}")
        left = self.expression(node.left, state)
        right = self.expression(node.right, state)
        operator = node.operator
        if right == 0 and operator in (BinaryOperator.DIVIDE, BinaryOperator.REMAINDER):
            code = "DIVISION_BY_ZERO" if operator == BinaryOperator.DIVIDE else "MODULO_BY_ZERO"
            _error(code, "Division or remainder by a statically known zero is undefined", node.right)
        if left is None or right is None:
            return None
        if operator in (BinaryOperator.DIVIDE, BinaryOperator.REMAINDER):
            if left == INT_MIN and right == -1:
                _error("INTEGER_OVERFLOW", "INT_MIN divided by -1 has an unrepresentable quotient (also undefined for remainder)", node)
            # Integer-only truncation toward zero; never Python floor division
            # on signed operands and never a potentially rounded float quotient.
            quotient = abs(left) // abs(right)
            if (left < 0) != (right < 0):
                quotient = -quotient
            return quotient if operator == BinaryOperator.DIVIDE else left - quotient * right
        if operator == BinaryOperator.ADD:
            result = left + right
        elif operator == BinaryOperator.SUBTRACT:
            result = left - right
        elif operator == BinaryOperator.MULTIPLY:
            result = left * right
        elif operator == BinaryOperator.LESS:
            result = int(left < right)
        elif operator == BinaryOperator.LESS_EQUAL:
            result = int(left <= right)
        elif operator == BinaryOperator.GREATER:
            result = int(left > right)
        elif operator == BinaryOperator.GREATER_EQUAL:
            result = int(left >= right)
        elif operator == BinaryOperator.EQUAL:
            result = int(left == right)
        elif operator == BinaryOperator.NOT_EQUAL:
            result = int(left != right)
        else:
            raise TypeError(f"Unsupported binary operator: {operator!r}")
        return self.checked_integer(result, node)

    def store(self, node: Declaration | Assignment, state: _State) -> None:
        target = node if isinstance(node, Declaration) else node.target
        value = node.initializer if isinstance(node, Declaration) else node.value
        symbol_id = self.bindings[target.node_id].symbol_id
        if value is None:
            return
        constant = self.expression(value, state)
        state.initialized.add(symbol_id)
        if constant is None:
            state.constants.pop(symbol_id, None)
        else:
            state.constants[symbol_id] = constant

    @staticmethod
    def join(left: _Flow, right: _Flow) -> _Flow:
        if not left.falls_through:
            return right
        if not right.falls_through:
            return left
        initialized = left.state.initialized & right.state.initialized
        constants = {
            symbol_id: value for symbol_id, value in left.state.constants.items()
            if symbol_id in initialized and right.state.constants.get(symbol_id) == value
        }
        return _Flow(_State(initialized, constants))

    def statement(self, node: Declaration | Statement, state: _State) -> _Flow:
        if isinstance(node, (Declaration, Assignment)):
            self.store(node, state)
            return _Flow(state)
        if isinstance(node, Return):
            self.expression(node.value, state)
            return _Flow(state, False)
        if isinstance(node, EmptyStatement):
            return _Flow(state)
        if isinstance(node, Block):
            flow = _Flow(state)
            local_ids = {self.bindings[item.node_id].symbol_id for item in node.items if isinstance(item, Declaration)}
            for item in node.items:
                if flow.falls_through:
                    flow = self.statement(item, flow.state)
                else:
                    self.dead(item)
            flow.state.initialized.difference_update(local_ids)
            for symbol_id in local_ids:
                flow.state.constants.pop(symbol_id, None)
            return flow
        if isinstance(node, If):
            self.expression(node.condition, state)
            then_flow = self.statement(node.then_branch, state.copy())
            else_flow = self.statement(node.else_branch, state.copy()) if node.else_branch is not None else _Flow(state.copy())
            return self.join(then_flow, else_flow)
        if isinstance(node, For):
            self.store(node.initializer, state)
            # A variable written anywhere in the loop may have a different value
            # at a later iteration. Forget it before the first diagnostic scan,
            # otherwise entry constants could produce false zero/overflow errors.
            written = {
                self.bindings[item.target.node_id].symbol_id
                for part in (node.body, node.update)
                for item in walk(part) if isinstance(item, Assignment)
            }
            loop_state = state.copy()
            for symbol_id in written:
                loop_state.constants.pop(symbol_id, None)
            self.expression(node.condition, loop_state)
            body_flow = self.statement(node.body, loop_state)
            if body_flow.falls_through:
                self.store(node.update, body_flow.state)
            else:
                self.dead(node.update)
            # The condition may be false immediately: only initialization in the
            # initializer is guaranteed outside the loop, never body/update facts.
            for symbol_id in written:
                state.constants.pop(symbol_id, None)
            if isinstance(node.initializer, Declaration):
                local_id = self.bindings[node.initializer.node_id].symbol_id
                state.initialized.discard(local_id)
                state.constants.pop(local_id, None)
            return _Flow(state)
        raise TypeError(f"Unsupported statement node: {type(node).__name__}")


def analyze(program: Program) -> SemanticAnalysis:
    """Validate the documented subset and return immutable separate annotations.

    Both alternatives of an if are considered possible and every loop may run
    zero times, even for literal conditions. Dead code receives warnings; its
    names must still be legal, but unevaluated reads/arithmetic are not checked.
    The first semantic error raises :class:`SemanticError` with a source span.
    """
    binder = _Binder()
    binder.statement(program.function.body)
    checker = _Checker(binder.bindings)
    flow = checker.statement(program.function.body, _State())
    if flow.falls_through:
        _error("MISSING_RETURN", "Every reachable exit from main requires an explicit return value", program.function.body)
    return SemanticAnalysis(
        tuple(binder.symbols), MappingProxyType(binder.bindings),
        tuple(sorted(checker.diagnostics, key=lambda diagnostic: diagnostic.span.start_offset)),
        frozenset(checker.unreachable),
    )


def validate(program: Program) -> None:
    """Check semantics, discarding annotations and nonfatal warnings."""
    analyze(program)

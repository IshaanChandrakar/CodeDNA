"""Shared syntax nodes: no evaluation, symbol resolution, CFG, or IR here."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Iterator, Literal, TypeAlias


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """One-based positions and zero-based offsets; the end is exclusive."""

    start_line: int
    start_column: int
    end_line: int
    end_column: int
    start_offset: int
    end_offset: int


class UnaryOperator(StrEnum):
    POSITIVE = "+"
    NEGATIVE = "-"


class BinaryOperator(StrEnum):
    ADD = "+"
    SUBTRACT = "-"
    MULTIPLY = "*"
    DIVIDE = "/"
    REMAINDER = "%"
    LESS = "<"
    LESS_EQUAL = "<="
    GREATER = ">"
    GREATER_EQUAL = ">="
    EQUAL = "=="
    NOT_EQUAL = "!="


@dataclass(frozen=True, slots=True, kw_only=True)
class Node:
    node_id: str
    span: SourceSpan


@dataclass(frozen=True, slots=True, kw_only=True)
class IntegerLiteral(Node):
    value: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Identifier(Node):
    name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class UnaryExpression(Node):
    operator: UnaryOperator
    operand: Expression


@dataclass(frozen=True, slots=True, kw_only=True)
class BinaryExpression(Node):
    operator: BinaryOperator
    left: Expression
    right: Expression


Expression: TypeAlias = IntegerLiteral | Identifier | UnaryExpression | BinaryExpression


@dataclass(frozen=True, slots=True, kw_only=True)
class Declaration(Node):
    name: str
    initializer: Expression | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Assignment(Node):
    target: Identifier
    value: Expression


@dataclass(frozen=True, slots=True, kw_only=True)
class Return(Node):
    value: Expression


@dataclass(frozen=True, slots=True, kw_only=True)
class EmptyStatement(Node):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Block(Node):
    items: tuple[Declaration | Statement, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class If(Node):
    condition: Expression
    then_branch: Statement
    else_branch: Statement | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class For(Node):
    initializer: Declaration | Assignment
    condition: Expression
    update: Assignment
    body: Statement


Statement: TypeAlias = Assignment | Return | EmptyStatement | Block | If | For


@dataclass(frozen=True, slots=True, kw_only=True)
class Function(Node):
    name: str
    body: Block
    return_type: Literal["int"] = "int"


@dataclass(frozen=True, slots=True, kw_only=True)
class Program(Node):
    function: Function
    schema_version: int = 1


def iter_child_nodes(node: Node) -> Iterator[Node]:
    """Yield immediate syntax children in dataclass field/source order."""
    for field in fields(node):
        value = getattr(node, field.name)
        if isinstance(value, Node):
            yield value
        elif isinstance(value, tuple):
            yield from (item for item in value if isinstance(item, Node))


def walk(node: Node) -> Iterator[Node]:
    """Preorder traversal without Python recursion, including the supplied root."""
    pending = [node]
    while pending:
        current = pending.pop()
        yield current
        pending.extend(reversed(tuple(iter_child_nodes(current))))


def ast_to_dict(node: Node) -> dict:
    """Serialize typed syntax, spans, and enums without exposing PLY internals."""
    def encode(value):
        if isinstance(value, Node):
            return {"kind": type(value).__name__, **{
                field.name: encode(getattr(value, field.name)) for field in fields(value)
            }}
        if isinstance(value, SourceSpan):
            return {field.name: getattr(value, field.name) for field in fields(value)}
        if isinstance(value, StrEnum):
            return value.value
        if isinstance(value, tuple):
            return [encode(item) for item in value]
        return value

    return encode(node)


def ast_to_json(node: Node, *, indent: int | None = 2) -> str:
    """Return deterministic, inspectable JSON for an AST or subtree."""
    return json.dumps(ast_to_dict(node), indent=indent, ensure_ascii=False)

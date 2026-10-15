"""Typed non-SSA three-address code lowered from the validated shared AST.

This module does not optimize or execute programs. Semantic constant facts never
replace source expressions: operations and conditional edges remain explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from compiler import ast_nodes as ast
from compiler.diagnostics import Diagnostic
from compiler.semantic import SemanticAnalysis, Symbol, analyze, validate


@dataclass(frozen=True, slots=True)
class Constant:
    value: int


@dataclass(frozen=True, slots=True)
class SymbolRef:
    symbol_id: str
    name: str


@dataclass(frozen=True, slots=True)
class TempRef:
    name: str


Operand: TypeAlias = Constant | SymbolRef | TempRef
Destination: TypeAlias = SymbolRef | TempRef


@dataclass(frozen=True, slots=True, kw_only=True)
class Instruction:
    node_id: str
    span: ast.SourceSpan


@dataclass(frozen=True, slots=True, kw_only=True)
class Label(Instruction):
    name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Copy(Instruction):
    destination: Destination
    operand: Operand


@dataclass(frozen=True, slots=True, kw_only=True)
class Unary(Instruction):
    destination: Destination
    operator: ast.UnaryOperator
    operand: Operand


@dataclass(frozen=True, slots=True, kw_only=True)
class Binary(Instruction):
    destination: Destination
    operator: ast.BinaryOperator
    left: Operand
    right: Operand


@dataclass(frozen=True, slots=True, kw_only=True)
class Branch(Instruction):
    condition: Operand
    true_label: str
    false_label: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Jump(Instruction):
    label: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Return(Instruction):
    operand: Operand


@dataclass(frozen=True, slots=True)
class IRProgram:
    instructions: tuple[Instruction, ...]
    symbols: tuple[Symbol, ...] = ()
    schema_version: int = 1
    diagnostics: tuple[Diagnostic, ...] = ()


def format_operand(operand: Operand) -> str:
    if isinstance(operand, Constant):
        return str(operand.value)
    if isinstance(operand, SymbolRef):
        return operand.name
    if isinstance(operand, TempRef):
        # '%' cannot occur in C identifiers: user t0 cannot collide with temp %t0.
        return f"%{operand.name}"
    raise TypeError(f"Unsupported IR operand: {type(operand).__name__}")


def format_instruction(instruction: Instruction) -> str:
    operand = format_operand
    if isinstance(instruction, Label):
        return f"{instruction.name}:"
    if isinstance(instruction, Copy):
        return f"{operand(instruction.destination)} = {operand(instruction.operand)}"
    if isinstance(instruction, Unary):
        return f"{operand(instruction.destination)} = {instruction.operator.value}{operand(instruction.operand)}"
    if isinstance(instruction, Binary):
        return (
            f"{operand(instruction.destination)} = {operand(instruction.left)} "
            f"{instruction.operator.value} {operand(instruction.right)}"
        )
    if isinstance(instruction, Branch):
        return (
            f"if {operand(instruction.condition)} goto {instruction.true_label} "
            f"else goto {instruction.false_label}"
        )
    if isinstance(instruction, Jump):
        return f"goto {instruction.label}"
    if isinstance(instruction, Return):
        return f"return {operand(instruction.operand)}"
    raise TypeError(f"Unsupported IR instruction: {type(instruction).__name__}")


def format_ir(program: IRProgram) -> str:
    """Deterministic TAC with source names, explicit temporaries and labels."""
    return "\n".join(format_instruction(instruction) for instruction in program.instructions)


class _Lowerer:
    def __init__(self, analysis: SemanticAnalysis) -> None:
        self.analysis = analysis
        self.instructions: list[Instruction] = []
        self._temp_number = 0
        self._label_number = 0

    def _temp(self) -> TempRef:
        result = TempRef(f"t{self._temp_number}")
        self._temp_number += 1
        return result

    def _label(self) -> str:
        result = f"L{self._label_number}"
        self._label_number += 1
        return result

    def _emit(self, instruction_type, node: ast.Node, **fields) -> None:
        self.instructions.append(instruction_type(node_id=node.node_id, span=node.span, **fields))

    def _symbol(self, node: ast.Declaration | ast.Identifier) -> SymbolRef:
        symbol = self.analysis.bindings[node.node_id]
        return SymbolRef(symbol.symbol_id, symbol.name)

    def expression(self, node: ast.Expression) -> Operand:
        if isinstance(node, ast.IntegerLiteral):
            return Constant(node.value)
        if isinstance(node, ast.Identifier):
            return self._symbol(node)
        if isinstance(node, ast.UnaryExpression):
            operand = self.expression(node.operand)
            destination = self._temp()
            self._emit(Unary, node, destination=destination, operator=node.operator, operand=operand)
            return destination
        if isinstance(node, ast.BinaryExpression):
            left = self.expression(node.left)
            right = self.expression(node.right)
            destination = self._temp()
            self._emit(Binary, node, destination=destination, operator=node.operator, left=left, right=right)
            return destination
        raise TypeError(f"Unsupported AST expression: {type(node).__name__}")

    def statement(self, node: ast.Declaration | ast.Statement) -> bool:
        """Emit syntax in source order, returning whether control can fall through."""
        if isinstance(node, ast.Block):
            falls_through = True
            for item in node.items:
                if not falls_through:
                    # Analysis retained source-located warnings for this dead syntax.
                    break
                falls_through = self.statement(item)
            return falls_through
        if isinstance(node, ast.Declaration):
            if node.initializer is not None:
                value = self.expression(node.initializer)
                self._emit(Copy, node, destination=self._symbol(node), operand=value)
            return True
        if isinstance(node, ast.Assignment):
            value = self.expression(node.value)
            self._emit(Copy, node, destination=self._symbol(node.target), operand=value)
            return True
        if isinstance(node, ast.EmptyStatement):
            return True
        if isinstance(node, ast.Return):
            value = self.expression(node.value)
            self._emit(Return, node, operand=value)
            return False
        if isinstance(node, ast.If):
            return self._if(node)
        if isinstance(node, ast.For):
            return self._for(node)
        raise TypeError(f"Unsupported AST statement: {type(node).__name__}")

    def _if(self, node: ast.If) -> bool:
        condition = self.expression(node.condition)
        then_label = self._label()
        false_label = self._label()
        end_label = self._label() if node.else_branch is not None else false_label
        self._emit(Branch, node, condition=condition, true_label=then_label, false_label=false_label)
        self._emit(Label, node.then_branch, name=then_label)
        then_falls = self.statement(node.then_branch)
        if node.else_branch is None:
            self._emit(Label, node, name=end_label)
            return True
        if then_falls:
            self._emit(Jump, node.then_branch, label=end_label)
        self._emit(Label, node.else_branch, name=false_label)
        else_falls = self.statement(node.else_branch)
        if then_falls or else_falls:
            self._emit(Label, node, name=end_label)
        return then_falls or else_falls

    def _for(self, node: ast.For) -> bool:
        self.statement(node.initializer)
        condition_label, body_label, update_label, exit_label = (self._label() for _ in range(4))
        self._emit(Label, node, name=condition_label)
        condition = self.expression(node.condition)
        self._emit(Branch, node, condition=condition, true_label=body_label, false_label=exit_label)
        self._emit(Label, node.body, name=body_label)
        if self.statement(node.body):
            self._emit(Label, node.update, name=update_label)
            self.statement(node.update)
            self._emit(Jump, node, label=condition_label)
        self._emit(Label, node, name=exit_label)
        # Even a body with a return can execute zero times in this conservative model.
        return True


def lower_ir(program: ast.Program) -> IRProgram:
    """Validate then lower an AST; preserve the source tree and all operations."""
    analysis = analyze(program)
    lowerer = _Lowerer(analysis)
    lowerer.statement(program.function.body)
    return IRProgram(tuple(lowerer.instructions), analysis.symbols, diagnostics=analysis.diagnostics)

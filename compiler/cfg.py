"""Basic blocks and control-flow edges derived only from the shared TAC.

Entry and exit are synthetic graph nodes, not instruction-bearing blocks.  A
back edge is the actual jump to an earlier block; no source-level loop guessing
or optimization is needed to construct the graph.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from enum import StrEnum

from compiler.ast_nodes import BinaryOperator, SourceSpan, UnaryOperator
from compiler.ir import (
    Binary,
    Branch,
    Constant,
    Copy,
    Instruction,
    IRProgram,
    Jump,
    Label,
    Return,
    SymbolRef,
    TempRef,
    Unary,
    format_instruction,
)


class EdgeKind(StrEnum):
    ENTRY = "entry"
    TRUE = "true"
    FALSE = "false"
    JUMP = "jump"
    FALLTHROUGH = "fallthrough"
    RETURN = "return"


@dataclass(frozen=True, slots=True)
class BasicBlock:
    block_id: str
    instructions: tuple[Instruction, ...]
    reachable: bool


@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    target: str
    kind: EdgeKind


@dataclass(frozen=True, slots=True)
class ControlFlowGraph:
    blocks: tuple[BasicBlock, ...]
    edges: tuple[Edge, ...]
    entry: str = "entry"
    exit: str = "exit"


_TERMINATORS = (Branch, Jump, Return)
_INSTRUCTIONS = (Label, Copy, Unary, Binary, Branch, Jump, Return)


def _name(value: object, description: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{description} must be a nonempty string")


def _operand(value: object, description: str, *, destination: bool = False) -> None:
    if isinstance(value, Constant) and not destination:
        if type(value.value) is not int:
            raise ValueError(f"{description} constant must contain an integer")
    elif isinstance(value, SymbolRef):
        _name(value.symbol_id, f"{description} symbol ID")
        _name(value.name, f"{description} symbol name")
    elif isinstance(value, TempRef):
        _name(value.name, f"{description} temporary name")
    else:
        expected = "SymbolRef or TempRef" if destination else "a typed IR operand"
        raise ValueError(f"{description} must be {expected}")


def _validate_ir(program: IRProgram) -> None:
    """Refuse malformed hand-built TAC before deriving misleading edges."""
    if not isinstance(program, IRProgram):
        raise ValueError("CFG construction requires an IRProgram")
    if not isinstance(program.instructions, tuple):
        raise ValueError("IRProgram instructions must be a tuple")
    labels: set[str] = set()
    references: list[tuple[int, str]] = []
    for index, instruction in enumerate(program.instructions):
        prefix = f"Instruction {index}"
        if not isinstance(instruction, _INSTRUCTIONS):
            raise ValueError(f"{prefix} has unsupported type {type(instruction).__name__}")
        _name(instruction.node_id, f"{prefix} source node ID")
        if not isinstance(instruction.span, SourceSpan):
            raise ValueError(f"{prefix} must carry a SourceSpan")
        if isinstance(instruction, Label):
            _name(instruction.name, f"{prefix} label name")
            if instruction.name in labels:
                raise ValueError(f"Duplicate IR label {instruction.name!r}")
            labels.add(instruction.name)
        elif isinstance(instruction, (Copy, Unary, Binary)):
            _operand(instruction.destination, f"{prefix} destination", destination=True)
            if isinstance(instruction, Binary):
                if not isinstance(instruction.operator, BinaryOperator):
                    raise ValueError(f"{prefix} requires a BinaryOperator")
                _operand(instruction.left, f"{prefix} left operand")
                _operand(instruction.right, f"{prefix} right operand")
            else:
                _operand(instruction.operand, f"{prefix} operand")
                if isinstance(instruction, Unary) and not isinstance(instruction.operator, UnaryOperator):
                    raise ValueError(f"{prefix} requires a UnaryOperator")
        elif isinstance(instruction, Branch):
            _operand(instruction.condition, f"{prefix} branch condition")
            for label in (instruction.true_label, instruction.false_label):
                _name(label, f"{prefix} branch target")
                references.append((index, label))
        elif isinstance(instruction, Jump):
            _name(instruction.label, f"{prefix} jump target")
            references.append((index, instruction.label))
        elif isinstance(instruction, Return):
            _operand(instruction.operand, f"{prefix} return operand")
    for index, label in references:
        if label not in labels:
            raise ValueError(f"Instruction {index} refers to undefined IR label {label!r}")


def build_cfg(program: IRProgram) -> ControlFlowGraph:
    """Partition TAC at leaders and connect its actual control transfers.

    The first instruction, every label, and the instruction following a
    terminator are leaders.  Keeping post-terminator instructions in their own
    blocks exposes dead code without ever adding a fallthrough from a return or
    jump.  Manual IR may fall through the final block to the synthetic exit;
    semantic validation enforces explicit returns for source programs.
    """
    _validate_ir(program)
    instructions = program.instructions
    if not instructions:
        return ControlFlowGraph((), (Edge("entry", "exit", EdgeKind.ENTRY),))

    leaders = {0}
    for index, instruction in enumerate(instructions):
        if isinstance(instruction, Label):
            leaders.add(index)
        if isinstance(instruction, _TERMINATORS) and index + 1 < len(instructions):
            leaders.add(index + 1)
    starts = sorted(leaders)
    ends = [*starts[1:], len(instructions)]
    blocks = tuple(
        BasicBlock(f"B{index}", instructions[start:end], reachable=False)
        for index, (start, end) in enumerate(zip(starts, ends))
    )
    label_blocks = {
        instruction.name: block.block_id
        for block in blocks
        for instruction in block.instructions
        if isinstance(instruction, Label)
    }
    edges = [Edge("entry", blocks[0].block_id, EdgeKind.ENTRY)]
    for index, block in enumerate(blocks):
        last = block.instructions[-1]
        if isinstance(last, Branch):
            edges.extend((
                Edge(block.block_id, label_blocks[last.true_label], EdgeKind.TRUE),
                Edge(block.block_id, label_blocks[last.false_label], EdgeKind.FALSE),
            ))
        elif isinstance(last, Jump):
            edges.append(Edge(block.block_id, label_blocks[last.label], EdgeKind.JUMP))
        elif isinstance(last, Return):
            edges.append(Edge(block.block_id, "exit", EdgeKind.RETURN))
        else:
            target = blocks[index + 1].block_id if index + 1 < len(blocks) else "exit"
            edges.append(Edge(block.block_id, target, EdgeKind.FALLTHROUGH))

    successors: dict[str, list[str]] = {}
    for edge in edges:
        successors.setdefault(edge.source, []).append(edge.target)
    reachable = {"entry"}
    pending = deque(["entry"])
    while pending:
        for target in successors.get(pending.popleft(), ()):
            if target not in reachable:
                reachable.add(target)
                pending.append(target)
    return ControlFlowGraph(
        tuple(replace(block, reachable=block.block_id in reachable) for block in blocks),
        tuple(edges),
    )


def format_cfg(cfg: ControlFlowGraph) -> str:
    """Return stable, readable blocks, reachability, and typed graph edges."""
    lines = [f"entry: {cfg.entry}", f"exit: {cfg.exit}"]
    for block in cfg.blocks:
        status = "" if block.reachable else " (unreachable)"
        lines.append(f"{block.block_id}{status}:")
        lines.extend(f"  {format_instruction(instruction)}" for instruction in block.instructions)
    lines.append("edges:")
    lines.extend(f"  {edge.source} -> {edge.target} [{edge.kind.value}]" for edge in cfg.edges)
    return "\n".join(lines)

"""Control-flow behavior, TAC boundaries, and malformed-input diagnostics."""

from dataclasses import replace

import pytest

from compiler.ast_nodes import BinaryOperator, UnaryOperator
from compiler.cfg import Edge, EdgeKind, build_cfg, format_cfg
from compiler.diagnostics import SourceMap
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
    lower_ir,
)
from compiler.parser import parse


SPAN = SourceMap("int main() { return 0; }").span(0, 24)
META = {"node_id": "n0", "span": SPAN}
X = SymbolRef("s0", "x")
TEMP = TempRef("t0")


def instruction(cls, **fields):
    return cls(**META, **fields)


def label(name):
    return instruction(Label, name=name)


def returned(value=0):
    return instruction(Return, operand=Constant(value))


def jump(target):
    return instruction(Jump, label=target)


def branch(true="yes", false="no"):
    return instruction(Branch, condition=X, true_label=true, false_label=false)


def block_for_label(cfg, name):
    return next(
        block for block in cfg.blocks
        if any(isinstance(item, Label) and item.name == name for item in block.instructions)
    )


def outgoing(cfg, block_id):
    return tuple(edge for edge in cfg.edges if edge.source == block_id)


def check_structure(cfg, ir):
    """No TAC is lost, no block runs through a terminator, all edges resolve."""
    assert tuple(item for block in cfg.blocks for item in block.instructions) == ir.instructions
    node_ids = {cfg.entry, cfg.exit, *(block.block_id for block in cfg.blocks)}
    for edge in cfg.edges:
        assert edge.source in node_ids
        assert edge.target in node_ids
    for block in cfg.blocks:
        assert not any(isinstance(item, (Branch, Jump, Return)) for item in block.instructions[:-1])
        if isinstance(block.instructions[-1], Return):
            assert outgoing(cfg, block.block_id) == (Edge(block.block_id, cfg.exit, EdgeKind.RETURN),)
        if isinstance(block.instructions[-1], Branch):
            assert {edge.kind for edge in outgoing(cfg, block.block_id)} == {EdgeKind.TRUE, EdgeKind.FALSE}


def test_empty_ir_connects_synthetic_entry_and_exit():
    cfg = build_cfg(IRProgram(()))
    assert cfg.blocks == ()
    assert cfg.edges == (Edge("entry", "exit", EdgeKind.ENTRY),)
    assert format_cfg(cfg) == "entry: entry\nexit: exit\nedges:\n  entry -> exit [entry]"


def test_straight_line_instructions_stay_together_until_return():
    ir = IRProgram((
        instruction(Copy, destination=X, operand=Constant(4)),
        instruction(Binary, destination=TEMP, operator=BinaryOperator.ADD, left=X, right=Constant(3)),
        instruction(Return, operand=TEMP),
    ))
    cfg = build_cfg(ir)
    assert len(cfg.blocks) == 1
    assert cfg.blocks[0].reachable
    assert cfg.edges == (Edge("entry", "B0", EdgeKind.ENTRY), Edge("B0", "exit", EdgeKind.RETURN))
    check_structure(cfg, ir)


def test_labels_and_instructions_after_terminators_are_leaders():
    ir = IRProgram((jump("done"), returned(99), label("done"), returned(0)))
    cfg = build_cfg(ir)
    assert [len(block.instructions) for block in cfg.blocks] == [1, 1, 2]
    assert [block.reachable for block in cfg.blocks] == [True, False, True]
    assert outgoing(cfg, "B0") == (Edge("B0", "B2", EdgeKind.JUMP),)
    check_structure(cfg, ir)


def test_consecutive_labels_remain_resolvable_and_fall_through():
    ir = IRProgram((label("first"), label("second"), returned()))
    cfg = build_cfg(ir)
    first = block_for_label(cfg, "first")
    second = block_for_label(cfg, "second")
    assert first.block_id != second.block_id
    assert outgoing(cfg, first.block_id) == (Edge(first.block_id, second.block_id, EdgeKind.FALLTHROUGH),)
    assert all(block.reachable for block in cfg.blocks)
    check_structure(cfg, ir)


def test_manual_final_fallthrough_connects_to_exit():
    ir = IRProgram((instruction(Copy, destination=X, operand=Constant(1)),))
    cfg = build_cfg(ir)
    assert outgoing(cfg, "B0") == (Edge("B0", "exit", EdgeKind.FALLTHROUGH),)


def test_conditional_targets_and_join_follow_actual_tac():
    ir = IRProgram((
        branch(),
        label("yes"), instruction(Copy, destination=X, operand=Constant(1)), jump("join"),
        label("no"), instruction(Copy, destination=X, operand=Constant(2)),
        label("join"), instruction(Return, operand=X),
    ))
    cfg = build_cfg(ir)
    yes = block_for_label(cfg, "yes").block_id
    no = block_for_label(cfg, "no").block_id
    join = block_for_label(cfg, "join").block_id
    assert outgoing(cfg, "B0") == (Edge("B0", yes, EdgeKind.TRUE), Edge("B0", no, EdgeKind.FALSE))
    assert outgoing(cfg, yes) == (Edge(yes, join, EdgeKind.JUMP),)
    assert outgoing(cfg, no) == (Edge(no, join, EdgeKind.FALLTHROUGH),)
    assert all(block.reachable for block in cfg.blocks)
    check_structure(cfg, ir)


def test_same_conditional_target_preserves_both_edge_meanings():
    cfg = build_cfg(IRProgram((branch("end", "end"), label("end"), returned())))
    assert outgoing(cfg, "B0") == (Edge("B0", "B1", EdgeKind.TRUE), Edge("B0", "B1", EdgeKind.FALSE))


def test_return_cannot_fall_through_into_a_following_labeled_block():
    cfg = build_cfg(IRProgram((returned(1), label("dead"), returned(2))))
    dead = block_for_label(cfg, "dead")
    assert not dead.reachable
    assert outgoing(cfg, "B0") == (Edge("B0", "exit", EdgeKind.RETURN),)
    assert "B1 (unreachable):" in format_cfg(cfg)


def test_unreachable_cycle_does_not_become_reachable():
    cfg = build_cfg(IRProgram((returned(), label("a"), jump("b"), label("b"), jump("a"))))
    assert [block.reachable for block in cfg.blocks] == [True, False, False]
    assert not any(edge.source == "exit" for edge in cfg.edges)


def test_infinite_loop_has_no_invented_exit_edge():
    cfg = build_cfg(IRProgram((label("again"), jump("again"))))
    assert cfg.edges == (Edge("entry", "B0", EdgeKind.ENTRY), Edge("B0", "B0", EdgeKind.JUMP))
    assert cfg.blocks[0].reachable


@pytest.mark.parametrize("source", [
    "int main() { return 0; }",
    "int main() { int x = 1; if (x) x = 2; return x; }",
    "int main() { int x = 1; if (x) return 2; else return 3; }",
    "int main() { int x = 1; if (x) { if (x < 2) return 3; else x = 4; } else x = 5; return x; }",
    "int main() { int s = 0; for (int i = 0; i < 4; i = i + 1) s = s + i; return s; }",
    "int main() { for (int i = 0; i < 4; i = i + 1) { if (i == 2) return i; } return 9; }",
    "int main() { int s = 0; for (int i = 0; i < 2; i = i + 1) for (int j = 0; j < 3; j = j + 1) s = s + 1; return s; }",
])
def test_real_frontend_control_flow_preserves_ir_and_valid_connectivity(source):
    ir = lower_ir(parse(source))
    cfg = build_cfg(ir)
    check_structure(cfg, ir)
    assert cfg.edges[0] == Edge("entry", cfg.blocks[0].block_id, EdgeKind.ENTRY)
    assert any(edge.kind is EdgeKind.RETURN for edge in cfg.edges)


def test_loop_body_update_and_back_edge_order():
    ir = lower_ir(parse("int main() { int s = 0; for (int i = 0; i < 4; i = i + 1) s = s + i; return s; }"))
    cfg = build_cfg(ir)
    condition = next(block for block in cfg.blocks if isinstance(block.instructions[-1], Branch))
    branch_instruction = condition.instructions[-1]
    body = block_for_label(cfg, branch_instruction.true_label)
    done = block_for_label(cfg, branch_instruction.false_label)
    assert Edge(condition.block_id, body.block_id, EdgeKind.TRUE) in cfg.edges
    assert Edge(condition.block_id, done.block_id, EdgeKind.FALSE) in cfg.edges
    # Follow the straight body/update path until it jumps back to the condition.
    path = []
    block = body
    while block.block_id != condition.block_id:
        assert block.block_id not in path
        path.append(block.block_id)
        successors = outgoing(cfg, block.block_id)
        assert len(successors) == 1
        assert successors[0].kind in (EdgeKind.FALLTHROUGH, EdgeKind.JUMP)
        block = next(item for item in cfg.blocks if item.block_id == successors[0].target)
    path_instructions = [item for item in cfg.blocks if item.block_id in path]
    assignments = [
        item.destination.name for part in path_instructions for item in part.instructions
        if isinstance(item, Copy) and isinstance(item.destination, SymbolRef)
    ]
    assert assignments == ["s", "i"]
    assert cfg.blocks.index(condition) < cfg.blocks.index(body)
    check_structure(cfg, ir)


def test_repeated_builds_and_fresh_parses_have_identical_graphs_and_text():
    source = "int main() { int x = 2; if (x < 3) x = x + 1; else x = x - 1; return x; }"
    first = build_cfg(lower_ir(parse(source)))
    second = build_cfg(lower_ir(parse(source)))
    assert first == second
    assert format_cfg(first) == format_cfg(second)


@pytest.mark.parametrize("items, message", [
    ((label("x"), label("x")), "Duplicate IR label 'x'"),
    ((jump("missing"),), "undefined IR label 'missing'"),
    ((branch("yes", "missing"), label("yes"), returned()), "undefined IR label 'missing'"),
    ((returned(), jump("missing")), "undefined IR label 'missing'"),
    ((instruction(Label, name=""),), "label name"),
    ((instruction(Jump, label=0),), "jump target"),
    ((instruction(Branch, condition=X, true_label="", false_label="x"),), "branch target"),
    ((instruction(Copy, destination=Constant(0), operand=Constant(1)),), "destination"),
    ((instruction(Copy, destination=X, operand=3),), "operand"),
    ((instruction(Return, operand="x"),), "return operand"),
    ((instruction(Return, operand=Constant(True)),), "integer"),
    ((instruction(Return, operand=TempRef("")),), "temporary name"),
    ((instruction(Return, operand=SymbolRef("", "x")),), "symbol ID"),
    ((instruction(Return, operand=SymbolRef("s0", "")),), "symbol name"),
    ((instruction(Branch, condition=None, true_label="x", false_label="x"), label("x")), "branch condition"),
    ((instruction(Unary, destination=TEMP, operator="-", operand=X),), "UnaryOperator"),
    ((instruction(Binary, destination=TEMP, operator="+", left=X, right=X),), "BinaryOperator"),
    ((instruction(Binary, destination=TEMP, operator=BinaryOperator.ADD, left=None, right=X),), "left operand"),
    ((instruction(Binary, destination=TEMP, operator=BinaryOperator.ADD, left=X, right=None),), "right operand"),
    ((instruction(Instruction),), "unsupported type"),
    ((object(),), "unsupported type"),
])
def test_malformed_manual_ir_is_rejected_with_useful_error(items, message):
    with pytest.raises(ValueError, match=message):
        build_cfg(IRProgram(items))


@pytest.mark.parametrize("changes, message", [
    ({"node_id": ""}, "source node ID"),
    ({"span": None}, "SourceSpan"),
])
def test_invalid_instruction_metadata_is_rejected(changes, message):
    with pytest.raises(ValueError, match=message):
        build_cfg(IRProgram((replace(returned(), **changes),)))


def test_invalid_program_and_mutable_instruction_container_are_rejected():
    with pytest.raises(ValueError, match="IRProgram"):
        build_cfg(None)
    with pytest.raises(ValueError, match="tuple"):
        build_cfg(IRProgram([returned()]))


def test_supported_unary_instruction_is_retained():
    ir = IRProgram((instruction(Unary, destination=TEMP, operator=UnaryOperator.NEGATIVE, operand=Constant(3)), instruction(Return, operand=TEMP)))
    cfg = build_cfg(ir)
    check_structure(cfg, ir)
    assert cfg.blocks[0].instructions == ir.instructions

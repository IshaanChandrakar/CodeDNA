"""Ordered passes, committed reports, immutable syntax and original provenance."""

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from compiler import ast_nodes as ast
from compiler.cfg import build_cfg
from compiler.codegen import emit_c
from compiler.diagnostics import SemanticError
from compiler.ir import Branch, format_ir, lower_ir
from compiler.parser import parse
from compiler.semantic import analyze
from transformations import apply_transformations, propagate_and_fold, unroll_loops
from transformations.common import CloneFactory, evaluate_binary, evaluate_constant, evaluate_unary


ROOT = Path(__file__).resolve().parents[1]
SUM = "int main(){int total=0;int i;for(i=0;i<4;i=i+1)total=total+i;return total*10+i;}"


@pytest.mark.parametrize("sequence,statuses", [
    ((), ()),
    (("constants",), ("not_applicable",)),
    (("unroll",), ("applied",)),
    (("unroll", "constants"), ("applied", "applied")),
    (("constants", "unroll", "constants"), ("not_applicable", "applied", "applied")),
    (("unroll", "unroll"), ("applied", "not_applicable")),
    (("constants", "constants"), ("not_applicable", "not_applicable")),
    (("unroll", "constants", "constants"), ("applied", "applied", "not_applicable")),
])
def test_sequence_order_status_and_derived_sum_are_consistent(sequence, statuses):
    original = parse(SUM)
    before = ast.ast_to_json(original)
    result = apply_transformations(original, sequence)
    assert result.sequence == sequence
    assert tuple(report.status for report in result.reports) == statuses
    assert len(result.reports) == len(sequence)
    assert ast.ast_to_json(original) == before
    assert {id(node) for node in ast.walk(original)}.isdisjoint(id(node) for node in ast.walk(result.program))
    assert apply_transformations(original, sequence).program == result.program
    assert apply_transformations(original, sequence).to_json() == result.to_json()
    analyze(result.program)
    build_cfg(lower_ir(result.program))
    if "unroll" in sequence:
        assert not any(isinstance(node, ast.For) for node in ast.walk(result.program))
        # Independently derived: sum(0..3)=6 and the final i=4, hence 6*10+4=64.
        fully_folded = propagate_and_fold(result.program).program
        assert fully_folded.function.body.items[-1].value.value == 64
    else:
        assert any(isinstance(node, ast.For) for node in ast.walk(result.program))


def test_combined_example_is_revalidated_emitted_and_lowered_to_expected_values():
    original = parse((ROOT / "examples/transformations/combined.c").read_text())
    result = apply_transformations(original, ("constants", "unroll", "constants"))
    assert tuple(report.status for report in result.reports) == ("applied",) * 3
    # Source-defined cases i=2,3,4,5 sum to 14; final i=6, result 146.
    assert result.program.function.body.items[-1].value.value == 146
    ir = lower_ir(result.program)
    assert not any(isinstance(instruction, Branch) for instruction in ir.instructions)
    assert len(build_cfg(ir).blocks) == 1
    emitted = emit_c(result.program)
    round_trip = parse(emitted)
    analyze(round_trip)
    assert format_ir(lower_ir(round_trip)) == format_ir(ir)
    assert "return (146);" in emitted


def test_rejection_does_not_abort_later_passes_and_order_controls_applicability():
    program = parse((ROOT / "examples/transformations/combined.c").read_text())
    result = apply_transformations(program, ("unroll", "constants", "unroll", "constants"))
    assert tuple(report.status for report in result.reports) == ("rejected", "applied", "applied", "applied")
    assert result.reports[0].decisions[0].code == "NONCONSTANT_START"
    assert result.reports[0].statistics.loops_unrolled == 0
    assert result.reports[2].statistics.loops_unrolled == 1
    assert result.program.function.body.items[-1].value.value == 146


def test_revalidation_rollback_has_no_committed_edits_and_keeps_original_provenance():
    original = parse("int main(){int x=0;for(int i=0;i<2;i=i+1)x=1/i;return x;}")
    result = apply_transformations(original, ("unroll", "constants"))
    assert result.reports[0].status == "rejected"
    assert "REVALIDATION_FAILED" in [decision.code for decision in result.reports[0].decisions]
    assert result.reports[0].statistics.loops_unrolled == 0
    assert result.reports[0].statistics.iterations_expanded == 0
    assert result.reports[0].statistics.changed_nodes == 0
    assert result.program == original and result.program is not original
    assert all(node_id == origin_id for node_id, origin_id in result.origins.items())
    assert {id(node) for node in ast.walk(original)}.isdisjoint(id(node) for node in ast.walk(result.program))


def test_multi_pass_origins_resolve_to_initial_nodes_and_original_spans():
    original = parse(SUM)
    result = apply_transformations(original, ("unroll", "constants", "constants", "unroll"))
    input_nodes = {node.node_id: node for node in ast.walk(original)}
    final_nodes = tuple(ast.walk(result.program))
    assert len({node.node_id for node in final_nodes}) == len(final_nodes)
    assert set(result.origins) == {node.node_id for node in final_nodes}
    assert set(result.origins.values()) <= input_nodes.keys()
    for node in final_nodes:
        assert node.span == input_nodes[result.origins[node.node_id]].span
    with pytest.raises(TypeError):
        result.origins["new"] = "old"


def test_reports_serialize_committed_changes_without_timing_or_process_state():
    source = parse("int main(){int x=2+3*4;int y=x-4;return y/3;}")
    result = apply_transformations(source, ("constants", "unroll"))
    data = json.loads(result.to_json())
    assert data["sequence"] == ["constants", "unroll"]
    assert data["reports"][0]["statistics"] == {
        "expressions_folded": 4, "references_propagated": 2,
        "loops_unrolled": 0, "iterations_expanded": 0, "changed_nodes": 6,
    }
    assert data["reports"][1]["status"] == "not_applicable"
    assert data == result.to_dict()
    assert json.loads(result.reports[0].to_json()) == result.reports[0].to_dict()
    assert "\n" not in result.to_json(indent=None)
    with pytest.raises(FrozenInstanceError):
        result.reports[0].statistics.expressions_folded = 99
    data["reports"][0]["statistics"]["expressions_folded"] = 99
    assert result.reports[0].statistics.expressions_folded == 4


def test_individual_variants_retain_independent_fresh_baselines():
    original = parse("int main(){int x=2+3;for(int i=0;i<2;i=i+1)x=x+i;return x;}")
    before = ast.ast_to_json(original)
    constants = propagate_and_fold(original)
    unrolled = unroll_loops(original)
    assert any(isinstance(node, ast.For) for node in ast.walk(constants.program))
    assert not any(isinstance(node, ast.For) for node in ast.walk(unrolled.program))
    assert ast.ast_to_json(original) == before
    identities = [{id(node) for node in ast.walk(tree)} for tree in (original, constants.program, unrolled.program)]
    assert identities[0].isdisjoint(identities[1])
    assert identities[1].isdisjoint(identities[2])


def test_existing_generated_ids_cannot_collide_with_new_subtree_copies():
    original = replace(parse("int main(){return 1+2;}"), node_id="u0")
    factory = CloneFactory(original)
    clone = factory.clone(original, fresh_ids=True)
    original_ids = {node.node_id for node in ast.walk(original)}
    clones = tuple(ast.walk(clone))
    assert len({node.node_id for node in clones}) == len(clones)
    assert original_ids.isdisjoint(node.node_id for node in clones)
    assert set(factory.origins.values()) == original_ids


@pytest.mark.parametrize("sequence", [("unknown",), ("constants", "unknown"), (1,)])
def test_invalid_sequences_do_not_mutate_input(sequence):
    original = parse(SUM)
    before = ast.ast_to_json(original)
    with pytest.raises(ValueError):
        apply_transformations(original, sequence)
    assert ast.ast_to_json(original) == before


@pytest.mark.parametrize("maximum", [-1, 1025, True, 1.5, "32"])
def test_pipeline_rejects_invalid_expansion_configuration(maximum):
    with pytest.raises(ValueError, match="max_iterations"):
        apply_transformations(parse(SUM), max_iterations=maximum)


def test_single_pass_name_is_accepted_without_treating_it_as_character_sequence():
    assert apply_transformations(parse(SUM), "unroll").sequence == ("unroll",)


def test_semantically_invalid_input_stays_a_source_error():
    with pytest.raises(SemanticError) as caught:
        apply_transformations(parse("int main(){return missing;}"))
    assert caught.value.diagnostic.code == "UNDECLARED_VARIABLE"


@pytest.mark.parametrize("operation,left,right,expected", [
    (ast.BinaryOperator.DIVIDE, -7, 3, -2),
    (ast.BinaryOperator.REMAINDER, -7, 3, -1),
    (ast.BinaryOperator.DIVIDE, -(2**31), -1, None),
    (ast.BinaryOperator.REMAINDER, -(2**31), -1, None),
    (ast.BinaryOperator.MULTIPLY, 65536, 65536, None),
    (ast.BinaryOperator.DIVIDE, 1, 0, None),
])
def test_shared_arithmetic_preserves_defined_c_rules(operation, left, right, expected):
    assert evaluate_binary(operation, left, right) == expected


def test_shared_constant_evaluation_refuses_unknowns_and_undefined_intermediates():
    def expression(text):
        return parse(f"int main(){{return {text};}}").function.body.items[0].value
    assert evaluate_constant(expression("x*0")) is None
    assert evaluate_constant(expression("0*(1/0)")) is None
    assert evaluate_constant(expression("(-2147483647-1)/1")) == -(2**31)
    assert evaluate_unary(ast.UnaryOperator.NEGATIVE, -(2**31)) is None


@pytest.mark.parametrize("name,code", [
    ("rejected_induction.c", "INDUCTION_WRITE"),
    ("rejected_declaration.c", "DECLARATION_IN_BODY"),
    ("rejected_limit.c", "ITERATION_LIMIT"),
])
def test_real_rejection_examples_preserve_the_entire_program(name, code):
    original = parse((ROOT / "examples/transformations" / name).read_text())
    result = unroll_loops(original)
    assert result.report.status == "rejected"
    assert code in [decision.code for decision in result.report.decisions]
    assert result.program == original
    assert result.program is not original
    analyze(result.program)
    build_cfg(lower_ir(result.program))

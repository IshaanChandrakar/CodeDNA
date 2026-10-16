"""Full-unroll behavior, mathematical bounds, scopes, and safety decisions."""

import pytest

from compiler import ast_nodes as ast
from compiler.cfg import build_cfg
from compiler.diagnostics import SemanticError
from compiler.ir import Binary, Branch, Constant, Copy, Jump, Label, Return, Unary, lower_ir
from compiler.parser import parse
from compiler.semantic import analyze
from transformations.loop_unrolling import MAX_UNROLL_ITERATIONS, unroll_loops


def transform(body, maximum=32):
    original = parse(f"int main(){{{body}}}")
    return original, unroll_loops(original, max_iterations=maximum)


def loops(program):
    return tuple(node for node in ast.walk(program) if isinstance(node, ast.For))


def codes(result):
    return tuple(decision.code for decision in result.report.decisions)


def straight_line_return(program):
    """Test-only evaluation of loop-free TAC against hand-derived expected values."""
    values = {}

    def read(operand):
        return operand.value if isinstance(operand, Constant) else values[operand]

    for instruction in lower_ir(program).instructions:
        if isinstance(instruction, Copy):
            values[instruction.destination] = read(instruction.operand)
        elif isinstance(instruction, Unary):
            value = read(instruction.operand)
            values[instruction.destination] = value if instruction.operator == "+" else -value
        elif isinstance(instruction, Binary):
            left, right = read(instruction.left), read(instruction.right)
            if instruction.operator == "+":
                value = left + right
            elif instruction.operator == "-":
                value = left - right
            elif instruction.operator == "*":
                value = left * right
            else:
                raise AssertionError(f"Unexpected test arithmetic {instruction.operator}")
            assert -(2**31) <= value < 2**31
            values[instruction.destination] = value
        elif isinstance(instruction, Return):
            return read(instruction.operand)
        else:
            assert not isinstance(instruction, (Branch, Jump, Label)), "Expected genuinely unrolled straight-line TAC"
    raise AssertionError("Expected a return")


@pytest.mark.parametrize("header, expected, count", [
    ("i=0;i<0;i=i+1", 0, 0),
    ("i=5;i<4;i=i+1", 5, 0),
    ("i=0;i<1;i=i+1", 101, 1),
    ("i=0;i<4;i=i+1", 464, 4),
    ("i=0;i<=4;i=i+1", 605, 5),
    ("i=1;i<6;i=i+2", 397, 3),
    ("i=1;i<=5;i=i+2", 397, 3),
    ("i=1;i<6;i=i+8", 119, 1),
    ("i=4;i>0;i=i-1", 500, 4),
    ("i=4;i>=0;i=i-1", 599, 5),
    ("i=5;i>0;i=i-2", 389, 3),
    ("i=5;i>=1;i=i-2", 389, 3),
    ("i=0;i>0;i=i-1", 0, 0),
    ("i=-3;i<2;i=i+2", 273, 3),
    ("i=3;i>-2;i=i+-2", 327, 3),
    ("i=-2;i<=2;i=i-(-2)", 304, 3),
])
def test_counts_body_order_and_final_induction_values(header, expected, count):
    # s counts visits, sum observes induction values, and i observes the final
    # update.  Their weighted combination catches omitted or reordered updates.
    _, result = transform(f"int s=0;int sum=0;int i;for({header}){{s=s+1;sum=sum+i;}}return s*100+sum*10+i;")
    assert result.report.status == "applied"
    assert result.report.statistics.loops_unrolled == 1
    assert result.report.statistics.iterations_expanded == count
    assert not loops(result.program)
    assert straight_line_return(result.program) == expected
    assert len(build_cfg(lower_ir(result.program)).blocks) == 1


def test_constant_expression_start_bound_and_step_are_supported_without_folding_body():
    _, result = transform("int x=0;int i;for(i=1+1;i<(2*3);i=i+(4/2))x=x+i;return x*10+i;")
    assert result.report.status == "applied"
    assert result.report.statistics.iterations_expanded == 2
    # This pass preserves the actual expressions, including the constant divide.
    replacement = result.program.function.body.items[2]
    assert isinstance(replacement, ast.Block)
    assert isinstance(replacement.items[0].value, ast.BinaryExpression)
    assert replacement.items[2].value.right.operator == ast.BinaryOperator.DIVIDE
    assert result.report.statistics.expressions_folded == 0
    assert result.report.statistics.references_propagated == 0
    assert not loops(result.program)


def test_initializer_declaration_remains_scoped_inside_replacement_block():
    _, result = transform("int sum=0;for(int i=0;i<3;i=i+1)sum=sum+i;return sum;")
    replacement = result.program.function.body.items[1]
    assert isinstance(replacement, ast.Block)
    assert isinstance(replacement.items[0], ast.Declaration)
    assert replacement.items[0].name == "i"
    assert straight_line_return(result.program) == 3
    analyze(result.program)


def test_assignment_initializer_updates_existing_storage_and_keeps_final_value():
    _, result = transform("int i=99;int x=1;for(i=2;i<5;i=i+1)x=x*i;return x+i;")
    assert straight_line_return(result.program) == 29


@pytest.mark.parametrize("header, expected", [
    ("i=2147483646;i<2147483647;i=i+1", 2147483647),
    ("i=-2147483647;i>-2147483647-1;i=i-1", -2147483648),
    ("i=-2147483647-1;i<0;i=i-(-2147483647-1)", 0),
])
def test_defined_boundary_updates_remain_eligible(header, expected):
    _, result = transform(f"int i;for({header});return i;")
    assert result.report.status == "applied"
    assert result.report.statistics.iterations_expanded == 1
    assert straight_line_return(result.program) == expected


def test_zero_iterations_keep_initializer_side_effect_and_drop_body_and_update():
    original, result = transform("int i=99;int x=7;for(i=5;i<3;i=i+1)x=x+100;return i+x;", maximum=0)
    replacement = result.program.function.body.items[2]
    assert isinstance(replacement, ast.Block)
    assert len(replacement.items) == 1
    assert replacement.items[0] == loops(original)[0].initializer
    assert straight_line_return(result.program) == 12
    assert result.report.statistics.iterations_expanded == 0


def test_repeated_nested_blocks_and_empty_statements_are_safe():
    _, result = transform("int x=0;for(int i=0;i<2;i=i+1){{x=x+1;;}{x=x+2;}}return x;")
    assert straight_line_return(result.program) == 6


def test_body_and_update_copies_use_unique_ids_with_original_provenance():
    original, result = transform("int x=0;for(int i=0;i<3;i=i+1){x=x+i;}return x;")
    old_loop = loops(original)[0]
    replacement = result.program.function.body.items[1]
    original_ids = {node.node_id for node in ast.walk(original)}
    result_nodes = tuple(ast.walk(result.program))
    assert len({node.node_id for node in result_nodes}) == len(result_nodes)
    assert replacement.node_id == old_loop.node_id
    assert replacement.items[0].node_id == old_loop.initializer.node_id
    for index, copied in enumerate(replacement.items[1:]):
        source = old_loop.body if index % 2 == 0 else old_loop.update
        source_nodes, copied_nodes = tuple(ast.walk(source)), tuple(ast.walk(copied))
        assert len(source_nodes) == len(copied_nodes)
        for prior, fresh in zip(source_nodes, copied_nodes):
            assert fresh.node_id not in original_ids
            assert fresh.span == prior.span
            assert result.origins[fresh.node_id] == prior.node_id
    assert {id(node) for node in ast.walk(original)}.isdisjoint(id(node) for node in result_nodes)


def test_body_keeps_induction_references_instead_of_substituting_iteration_values():
    _, result = transform("int x=0;for(int i=0;i<2;i=i+1)x=x+i;return x;")
    replacement = result.program.function.body.items[1]
    for body in (replacement.items[1], replacement.items[3]):
        assert isinstance(body.value.right, ast.Identifier)
        assert body.value.right.name == "i"


@pytest.mark.parametrize("body, code", [
    ("int start=0;for(int i=start;i<2;i=i+1);return 0;", "NONCONSTANT_START"),
    ("int n=2;for(int i=0;i<n;i=i+1);return 0;", "NONCONSTANT_BOUND"),
    ("int step=1;for(int i=0;i<2;i=i+step);return 0;", "NONCONSTANT_STEP"),
    ("for(int i=0;2>i;i=i+1);return 0;", "NONCANONICAL_CONDITION"),
    ("for(int i=0;i!=2;i=i+1);return 0;", "NONCANONICAL_CONDITION"),
    ("int j=0;for(int i=0;j<2;i=i+1);return 0;", "NONCANONICAL_CONDITION"),
    ("for(int i=0;i<2;i=1+i);return 0;", "NONCANONICAL_UPDATE"),
    ("for(int i=1;i<4;i=i*2);return 0;", "NONCANONICAL_UPDATE"),
    ("int j=0;for(int i=0;i<2;j=j+1);return 0;", "NONCANONICAL_UPDATE"),
    ("int j=0;for(int i=0;i<2;i=j+1);return 0;", "NONCANONICAL_UPDATE"),
    ("for(int i=0;i<2;i=i+0);return 0;", "ZERO_STEP"),
    ("for(int i=0;i<2;i=i-1);return 0;", "STEP_DIRECTION"),
    ("for(int i=2;i>0;i=i+1);return 0;", "STEP_DIRECTION"),
    ("for(int i=0;i<2;i=i+1)i=i+1;return 0;", "INDUCTION_WRITE"),
    ("for(int i=0;i<2;i=i+1){{i=0;}}return 0;", "INDUCTION_WRITE"),
    ("for(int i=0;i<2;i=i+1){int x=i;}return 0;", "DECLARATION_IN_BODY"),
    ("for(int i=0;i<2;i=i+1){{int x=i;}}return 0;", "DECLARATION_IN_BODY"),
    ("for(int i=0;i<2;i=i+1)return i;return 0;", "RETURN_IN_BODY"),
    ("int x=0;for(int i=0;i<2;i=i+1)if(i)x=x+1;return x;", "CONDITIONAL_BODY"),
    ("for(int i=0;i<2147483647;i=i+1);return 0;", "ITERATION_LIMIT"),
    ("for(int i=2147483647;i<=2147483647;i=i+1);return 0;", "INDUCTION_OVERFLOW"),
    ("for(int i=2147483646;i<2147483647;i=i+2);return 0;", "INDUCTION_OVERFLOW"),
    ("for(int i=-2147483647-1;i>=-2147483647-1;i=i-1);return 0;", "INDUCTION_OVERFLOW"),
])
def test_ineligible_loops_remain_fresh_and_structurally_unchanged(body, code):
    original, result = transform(body)
    assert result.report.status == "rejected"
    assert code in codes(result)
    assert result.report.statistics.loops_unrolled == 0
    assert result.program == original
    assert result.program is not original
    assert loops(result.program)[0] is not loops(original)[0]


def test_nested_loops_and_inner_eligible_loop_are_both_preserved_and_reported():
    original, result = transform("int x=0;for(int i=0;i<2;i=i+1)for(int j=0;j<2;j=j+1)x=x+1;return x;")
    assert result.program == original
    assert result.report.status == "rejected"
    assert codes(result) == ("NESTED_LOOP_BODY", "NESTED_LOOP_CONTEXT")
    assert tuple(decision.node_id for decision in result.report.decisions) == tuple(node.node_id for node in loops(original))


def test_nested_context_is_reported_even_if_outer_header_is_ineligible():
    _, result = transform("int n=2;for(int i=0;i<n;i=i+1)for(int j=0;j<2;j=j+1);return 0;")
    assert codes(result) == ("NONCONSTANT_BOUND", "NESTED_LOOP_CONTEXT")
    assert len(loops(result.program)) == 2


def test_unreachable_loops_are_preserved_without_evaluating_dead_arithmetic():
    original, result = transform("return 0;for(int i=1/0;i<2;i=i+1);")
    assert result.program == original
    assert result.report.status == "not_applicable"
    assert codes(result) == ("UNREACHABLE_LOOP",)
    assert result.report.statistics.loops_unrolled == 0


def test_mixed_eligible_and_ineligible_loops_apply_only_safe_changes():
    _, result = transform("int x=0;for(int i=0;i<2;i=i+1)x=x+1;int n=3;for(int j=0;j<n;j=j+1)x=x+1;return x;")
    assert result.report.status == "applied"
    assert result.report.statistics.loops_unrolled == 1
    assert result.report.statistics.iterations_expanded == 2
    assert len(loops(result.program)) == 1
    assert codes(result) == ("NONCONSTANT_BOUND",)
    analyze(result.program)


def test_loop_inside_an_ordinary_if_can_be_unrolled_without_pruning_the_if():
    _, result = transform("int x=0;if(1)for(int i=0;i<2;i=i+1)x=x+1;return x;")
    assert result.report.status == "applied"
    assert not loops(result.program)
    assert isinstance(result.program.function.body.items[1], ast.If)
    assert isinstance(result.program.function.body.items[1].then_branch, ast.Block)
    analyze(result.program)


@pytest.mark.parametrize("maximum", [0, 1, 2, 31])
def test_configured_limit_rejects_a_loop_one_iteration_above_it(maximum):
    _, result = transform(f"for(int i=0;i<{maximum+1};i=i+1);return 0;", maximum=maximum)
    assert result.report.status == "rejected"
    assert codes(result) == ("ITERATION_LIMIT",)
    assert f"max_iterations={maximum}" in result.report.decisions[0].message


def test_largest_configured_limit_is_accepted():
    _, result = transform(f"int i;for(i=0;i<{MAX_UNROLL_ITERATIONS};i=i+1);return i;", maximum=MAX_UNROLL_ITERATIONS)
    assert result.report.status == "applied"
    assert result.report.statistics.iterations_expanded == 1024
    assert straight_line_return(result.program) == 1024


@pytest.mark.parametrize("maximum", [-1, 1025, True, False, 1.0, None, "32"])
def test_invalid_limits_are_configuration_errors(maximum):
    with pytest.raises(ValueError, match="max_iterations"):
        unroll_loops(parse("int main(){return 0;}"), max_iterations=maximum)


def test_no_loop_is_not_applicable_and_returns_a_fresh_tree():
    original, result = transform("int x=2;return x+1;")
    assert result.report.status == "not_applicable"
    assert result.program == original and result.program is not original
    assert result.report.statistics.loops_unrolled == 0


def test_original_immutability_determinism_and_stable_second_application():
    original = parse("int main(){int x=0;for(int i=0;i<3;i=i+1)x=x+i;return x;}")
    before = ast.ast_to_dict(original)
    first, second = unroll_loops(original), unroll_loops(original)
    assert ast.ast_to_dict(original) == before
    assert first == second
    repeated = unroll_loops(first.program)
    assert repeated.report.status == "not_applicable"
    assert repeated.program == first.program
    assert straight_line_return(repeated.program) == 3


def test_revalidation_rejects_newly_exposed_undefined_arithmetic_and_clears_stats():
    original, result = transform("int x=2147483647;for(int i=0;i<1;i=i+1)x=x+1;return x;")
    # Baseline checking deliberately invalidates loop-carried constants.  Once
    # expansion reveals definite overflow, the candidate must be rolled back.
    assert result.report.status == "rejected"
    assert result.program == original
    assert len(loops(result.program)) == 1
    assert result.report.statistics.loops_unrolled == 0
    assert result.report.statistics.iterations_expanded == 0


def test_invalid_original_source_is_rejected_before_transformation():
    with pytest.raises(SemanticError):
        unroll_loops(parse("int main(){for(int i=0;i<2;i=i+1)x=x+i;return 0;}"))

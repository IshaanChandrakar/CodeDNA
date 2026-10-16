"""Expected constant results, conservative control flow and safe refusals."""

import pytest

from compiler import ast_nodes as ast
from compiler.diagnostics import SemanticError
from compiler.ir import format_ir, lower_ir
from compiler.parser import parse
from compiler.semantic import analyze
from transformations.constant_folding import fold_expression, propagate_and_fold


def transformed(body):
    return propagate_and_fold(parse(f"int main(){{{body}}}"))


def expression(source):
    return parse(f"int main(){{return {source};}}").function.body.items[0].value


def final_value(result):
    node = result.program.function.body.items[-1]
    assert isinstance(node, ast.Return)
    assert isinstance(node.value, ast.IntegerLiteral)
    return node.value.value


@pytest.mark.parametrize("source,expected", [
    ("2+3*4", 14), ("(2+3)*4", 20), ("+7", 7),
    ("-7", -7), ("-(-7)", 7), ("9-12", -3), ("-6*-7", 42),
    ("-7/3", -2), ("7/-3", -2), ("-7/-3", 2), ("7/3", 2),
    ("-7%3", -1), ("7%-3", 1), ("-7%-3", -1), ("7%3", 1),
    ("1<2", 1), ("2<1", 0), ("2<=2", 1), ("3<=2", 0),
    ("3>2", 1), ("2>3", 0), ("3>=3", 1), ("2>=3", 0),
    ("2==2", 1), ("2==3", 0), ("2!=3", 1), ("3!=3", 0),
    ("2147483647+0", 2147483647), ("-2147483647-1", -2147483648),
    ("(-2147483647-1)/1", -2147483648), ("(-2147483647-1)%3", -2),
    ("(13%5)*7+(17/4)", 25), ("((-7/3)==-2)+((-7%3)==-1)", 2),
])
def test_literal_operations_have_independently_expected_signed_c_values(source, expected):
    original = expression(source)
    result = fold_expression(original)
    assert isinstance(result, ast.IntegerLiteral)
    assert result.value == expected
    assert result.node_id == original.node_id and result.span == original.span
    assert result is not original


@pytest.mark.parametrize("source", [
    "1/0", "1%0", "2147483647+1", "(-2147483647-1)-1", "65536*65536",
    "-(-2147483647-1)", "(-2147483647-1)/-1", "(-2147483647-1)%-1",
    "(2+3)/(1-1)", "(2+3)*(1/0)", "0*(1/0)", "(1/0)*0",
    "(2147483647+1)==(2+3)", "x/(1-1)", "x%(2-2)",
])
def test_undefined_raw_expressions_preserve_their_complete_original_structure(source):
    original = expression(source)
    result = fold_expression(original)
    assert ast.ast_to_json(result) == ast.ast_to_json(original)
    assert result is not original
    assert {id(node) for node in ast.walk(original)}.isdisjoint(id(node) for node in ast.walk(result))


@pytest.mark.parametrize("source", ["x*0", "0*x", "x-x", "x+0", "x/1", "x==x", "x*(1/0)"])
def test_unknown_expressions_are_not_replaced_by_algebraic_identities(source):
    original = expression(source)
    result = fold_expression(original)
    assert ast.ast_to_json(result) == ast.ast_to_json(original)


def test_safe_children_can_fold_while_a_parent_remains_nonconstant():
    result = fold_expression(expression("x+(2+3*4)"))
    assert isinstance(result, ast.BinaryExpression)
    assert isinstance(result.left, ast.Identifier)
    assert isinstance(result.right, ast.IntegerLiteral) and result.right.value == 14


def test_assignment_transfer_propagates_updated_values_and_reports_actual_changes():
    result = transformed("int x=2+3*4;int y=x-4;return y/3;")
    declarations = result.program.function.body.items[:2]
    assert [node.initializer.value for node in declarations] == [14, 10]
    assert final_value(result) == 3
    assert result.report.status == "applied"
    assert result.report.statistics.expressions_folded == 4
    assert result.report.statistics.references_propagated == 2
    assert result.report.statistics.changed_nodes == 6
    assert format_ir(lower_ir(result.program)) == "x = 14\ny = 10\nreturn 3"


def test_assignment_targets_stay_identifiers_while_reads_use_the_newest_value():
    result = transformed("int x=3;x=x+4;x=x*2;return x;")
    items = result.program.function.body.items
    assert isinstance(items[1].target, ast.Identifier) and items[1].target.name == "x"
    assert isinstance(items[2].target, ast.Identifier) and items[2].target.name == "x"
    assert [items[1].value.value, items[2].value.value, final_value(result)] == [7, 14, 14]


def test_uninitialized_declarations_can_become_known_after_an_assignment():
    result = transformed("int x;x=6;return x+1;")
    assert result.program.function.body.items[0].initializer is None
    assert final_value(result) == 7


@pytest.mark.parametrize("condition", ["0", "1", "2<3"])
def test_differing_conditional_assignments_invalidate_facts_even_for_constant_conditions(condition):
    result = transformed(f"int x=1;if({condition})x=3;else x=4;return x;")
    items = result.program.function.body.items
    assert isinstance(items[1], ast.If)
    assert items[1].else_branch is not None
    assert isinstance(items[-1].value, ast.Identifier) and items[-1].value.name == "x"


@pytest.mark.parametrize("body,expected", [
    ("int x=1;if(1)x=4;else x=2+2;return x;", 4),
    ("int x=1;if(1)x=1;return x;", 1),
    ("int x;if(1)return 0;else x=7;return x;", 7),
    ("int x;if(1)x=7;else return 0;return x;", 7),
    ("int x;if(1){if(0)x=7;else return 0;}else x=7;return x;", 7),
    ("int x=2;{int y=x+3;x=y;}return x;", 5),
])
def test_branch_joins_use_equal_facts_from_only_continuing_paths_and_respect_blocks(body, expected):
    assert final_value(transformed(body)) == expected


def test_no_else_preserves_the_unmodified_incoming_path_at_the_join():
    result = transformed("int x=1;if(1)x=4;return x;")
    assert isinstance(result.program.function.body.items[-1].value, ast.Identifier)


def test_uncertain_assignment_kills_an_earlier_constant():
    result = transformed("int x=1;int y=2;if(1)y=3;else y=4;x=y;return x;")
    assignment, returned = result.program.function.body.items[-2:]
    assert isinstance(assignment.value, ast.Identifier) and assignment.value.name == "y"
    assert isinstance(returned.value, ast.Identifier) and returned.value.name == "x"


def test_loop_carried_variables_stay_unknown_in_condition_body_update_and_after_loop():
    result = transformed("int x=0;for(int i=0;i<3;i=i+1){x=x+1;}return x;")
    loop = result.program.function.body.items[1]
    assert isinstance(loop.condition.left, ast.Identifier) and loop.condition.left.name == "i"
    assert isinstance(loop.body.items[0].value.left, ast.Identifier)
    assert isinstance(loop.update.value.left, ast.Identifier)
    assert isinstance(result.program.function.body.items[-1].value, ast.Identifier)


def test_read_only_outer_constants_propagate_through_a_loop_and_after_it():
    result = transformed("int bound=3;int x=0;for(int i=0;i<bound;i=i+1){x=x+bound;}return bound;")
    loop = result.program.function.body.items[2]
    assert loop.condition.right.value == 3
    assert loop.body.items[0].value.right.value == 3
    assert final_value(result) == 3


def test_constant_initializer_effects_survive_only_when_the_loop_does_not_write_them():
    result = transformed("int x;int i=0;for(x=5;i<3;i=i+1);return x;")
    assert final_value(result) == 5


def test_inner_loop_writes_also_invalidate_outer_loop_entry_facts():
    result = transformed("int x=0;for(int i=0;i<2;i=i+1){for(int j=0;j<2;j=j+1)x=x+1;}return x;")
    outer = result.program.function.body.items[1]
    inner = outer.body.items[0]
    assert isinstance(inner.body.value.left, ast.Identifier)
    assert isinstance(result.program.function.body.items[-1].value, ast.Identifier)


def test_body_assignments_on_every_continuing_path_can_feed_the_same_iteration_update():
    result = transformed("int x=0;for(int i=0;i<3;i=x){if(i)x=5;else x=5;}return x;")
    loop = result.program.function.body.items[1]
    assert isinstance(loop.update.value, ast.IntegerLiteral) and loop.update.value.value == 5
    assert isinstance(result.program.function.body.items[-1].value, ast.Identifier)


def test_loop_does_not_propagate_entry_zero_into_a_loop_carried_denominator():
    result = transformed("int x=0;for(int i=0;i<2;i=i+1){x=x+1;int y=1/x;}return x;")
    divisor = result.program.function.body.items[1].body.items[1].initializer.right
    assert isinstance(divisor, ast.Identifier) and divisor.name == "x"
    analyze(result.program)


def test_structurally_dead_syntax_and_unreachable_loop_updates_are_cloned_unchanged():
    original = parse("int main(){int x=1;for(int i=0;i<3;i=x+1){return x;}return x;int y=2+3;}")
    result = propagate_and_fold(original)
    old_loop = original.function.body.items[1]
    new_loop = result.program.function.body.items[1]
    assert ast.ast_to_json(old_loop.update) == ast.ast_to_json(new_loop.update)
    old_dead = original.function.body.items[-1]
    new_dead = result.program.function.body.items[-1]
    assert ast.ast_to_json(old_dead) == ast.ast_to_json(new_dead)
    assert new_loop.body.items[0].value.value == 1


def test_return_terminated_conditional_leaves_following_syntax_unchanged():
    original = parse("int main(){int x=1;if(x)return 2;else return 3;return x+1;}")
    result = propagate_and_fold(original)
    assert ast.ast_to_json(result.program.function.body.items[-1]) == ast.ast_to_json(original.function.body.items[-1])


def test_every_result_node_is_fresh_and_original_ast_serialization_is_unchanged():
    original = parse("int main(){int x=1;int y=x+3;if(x)y=y+2;else y=y+2;return y;}")
    snapshot = ast.ast_to_json(original)
    result = propagate_and_fold(original)
    assert ast.ast_to_json(original) == snapshot
    old_objects = {id(node) for node in ast.walk(original)}
    new_nodes = tuple(ast.walk(result.program))
    assert old_objects.isdisjoint(id(node) for node in new_nodes)
    assert len({node.node_id for node in new_nodes}) == len(new_nodes)
    assert set(result.origins) == {node.node_id for node in new_nodes}
    assert all(result.origins[node.node_id] == node.node_id for node in new_nodes)


def test_reports_and_transformed_ast_are_deterministic_and_repeated_application_is_stable():
    original = parse("int main(){int x=2+3;int y=x*2;return y;}")
    first = propagate_and_fold(original)
    independent = propagate_and_fold(parse("int main(){int x=2+3;int y=x*2;return y;}"))
    assert first.report == independent.report
    assert ast.ast_to_json(first.program) == ast.ast_to_json(independent.program)
    repeated = propagate_and_fold(first.program)
    assert ast.ast_to_json(repeated.program) == ast.ast_to_json(first.program)
    assert repeated.report.status == "not_applicable"
    assert repeated.report.statistics.changed_nodes == 0
    assert repeated.report.statistics.expressions_folded == 0
    assert repeated.report.statistics.references_propagated == 0


def test_an_unchanged_program_is_still_fresh_with_an_explicit_not_applicable_report():
    original = parse("int main(){return 7;}")
    result = propagate_and_fold(original)
    assert result.report.status == "not_applicable"
    assert result.report.statistics.changed_nodes == 0
    assert ast.ast_to_json(result.program) == ast.ast_to_json(original)
    assert {id(node) for node in ast.walk(original)}.isdisjoint(id(node) for node in ast.walk(result.program))


@pytest.mark.parametrize("body,code", [
    ("return 1/0;", "DIVISION_BY_ZERO"),
    ("return 1%0;", "MODULO_BY_ZERO"),
    ("return 2147483647+1;", "INTEGER_OVERFLOW"),
    ("return (-2147483647-1)/-1;", "INTEGER_OVERFLOW"),
    ("return missing;", "UNDECLARED_VARIABLE"),
])
def test_program_pass_preserves_the_original_semantic_error_contract(body, code):
    with pytest.raises(SemanticError) as caught:
        transformed(body)
    assert caught.value.diagnostic.code == code

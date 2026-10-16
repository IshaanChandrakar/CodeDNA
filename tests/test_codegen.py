"""Subset-C emission round trips and full integer results without machine execution."""

from dataclasses import replace
from pathlib import Path

import pytest

from compiler import ast_nodes as ast
from compiler.cfg import build_cfg, format_cfg
from compiler.codegen import emit_c
from compiler.diagnostics import SemanticError
from compiler.ir import (
    Binary, Branch, Constant, Copy, Jump, Label, Return, Unary,
    emit_c as planned_emit_c, format_ir, lower_ir,
)
from compiler.parser import parse
from compiler.semantic import INT_MAX, INT_MIN, analyze


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_RESULTS = {
    "basic/minimal.c": 0,
    "basic/arithmetic.c": 15,
    "basic/assignments.c": 14,
    "basic/simple_if.c": 5,
    "basic/if_else.c": 7,
    "basic/nested_if_else.c": 5,
    "loops/sum.c": 6,
    "loops/arithmetic.c": 10,
    "loops/nested.c": 3,
}


def _execute_tac(program):
    """Bounded test-only TAC oracle; values remain full signed integers."""
    instructions = lower_ir(program).instructions
    labels = {instruction.name: index for index, instruction in enumerate(instructions)
              if isinstance(instruction, Label)}
    values = {}

    def read(operand):
        return operand.value if isinstance(operand, Constant) else values[operand]

    def binary(operator, left, right):
        if operator in ("/", "%"):
            quotient = (abs(left) // abs(right)) * (-1 if (left < 0) != (right < 0) else 1)
            return quotient if operator == "/" else left - quotient * right
        if operator == "+":
            return left + right
        if operator == "-":
            return left - right
        if operator == "*":
            return left * right
        return int({"<": left < right, "<=": left <= right, ">": left > right,
                    ">=": left >= right, "==": left == right, "!=": left != right}[operator])

    position = 0
    for _ in range(10000):
        instruction = instructions[position]
        position += 1
        if isinstance(instruction, Label):
            continue
        if isinstance(instruction, Copy):
            result = read(instruction.operand)
        elif isinstance(instruction, Unary):
            result = read(instruction.operand)
            if instruction.operator == "-":
                result = -result
        elif isinstance(instruction, Binary):
            result = binary(instruction.operator.value, read(instruction.left), read(instruction.right))
        elif isinstance(instruction, Branch):
            position = labels[instruction.true_label if read(instruction.condition) else instruction.false_label]
            continue
        elif isinstance(instruction, Jump):
            position = labels[instruction.label]
            continue
        elif isinstance(instruction, Return):
            return read(instruction.operand)
        else:
            raise AssertionError(f"Unexpected instruction: {instruction}")
        assert INT_MIN <= result <= INT_MAX
        values[instruction.destination] = result
    raise AssertionError("Test TAC exceeded its instruction bound")


@pytest.mark.parametrize("name,expected", EXAMPLE_RESULTS.items())
def test_every_original_example_round_trips_through_semantics_tac_and_cfg(name, expected):
    original = parse((ROOT / "examples" / name).read_text(encoding="utf-8"))
    emitted = emit_c(original)
    round_trip = parse(emitted)
    assert analyze(round_trip).diagnostics == ()
    original_ir, emitted_ir = lower_ir(original), lower_ir(round_trip)
    assert format_ir(emitted_ir) == format_ir(original_ir)
    assert format_cfg(build_cfg(emitted_ir)) == format_cfg(build_cfg(original_ir))
    assert _execute_tac(original) == _execute_tac(round_trip) == expected
    assert emit_c(round_trip) == emitted


def test_planned_ir_api_reexports_the_same_emitter():
    assert planned_emit_c is emit_c
    assert planned_emit_c(parse("int main(){return 0;}")) == "int main(void) {\n    return (0);\n}\n"


@pytest.mark.parametrize("expression,expected", [
    ("2+3*4", 14),
    ("(2+3)*4", 20),
    ("18-(7-2)", 13),
    ("20/5/2", 2),
    ("20/(5/2)", 10),
    ("+ - + 7", -7),
    ("-(-(-2))", -2),
    ("-7/3", -2),
    ("7/-3", -2),
    ("-7%3", -1),
    ("7%-3", 1),
    ("-7%-3", -1),
    ("1+2<3*4==1", 1),
    ("4>2!=0", 1),
    ("-2147483647-1", INT_MIN),
    ("2147483647", INT_MAX),
    ("256+256", 512),
])
def test_emitted_arithmetic_preserves_precedence_signs_comparisons_and_full_results(expression, expected):
    original = parse(f"int main(){{return {expression};}}")
    emitted = emit_c(original)
    assert _execute_tac(parse(emitted)) == _execute_tac(original) == expected
    assert format_ir(lower_ir(parse(emitted))) == format_ir(lower_ir(original))


@pytest.mark.parametrize("value", [INT_MIN, INT_MIN + 1, -7, -1, 0, 1, INT_MAX])
def test_folded_integer_nodes_emit_values_accepted_by_the_unchanged_lexer(value):
    original = parse("int main(){return 0;}")
    returned = original.function.body.items[0]
    folded = replace(original, function=replace(
        original.function, body=replace(original.function.body, items=(
            replace(returned, value=replace(returned.value, value=value)),
        )),
    ))
    before = ast.ast_to_dict(folded)
    emitted = emit_c(folded)
    assert _execute_tac(parse(emitted)) == value
    assert ast.ast_to_dict(folded) == before
    if value == INT_MIN:
        assert "(-2147483647 - 1)" in emitted
        assert "2147483648" not in emitted


@pytest.mark.parametrize("body,expected", [
    ("int x=0;if(1)if(0)x=1;else x=2;return x;", 2),
    ("int x=0;if(0){if(1)x=1;}else x=3;return x;", 3),
    ("int x=0;if(1)for(int i=0;i<2;i=i+1)if(i)x=x+3;else x=x+1;else x=9;return x;", 4),
    ("int x;int i;for(i=0;i<3;i=i+1){if(i==1)x=4;else x=2;}return i;", 3),
    ("int x=1;{int y=3;x=x+y;}{int z=2;x=x*z;}return x;", 8),
    ("for(int i=0;i<2;i=i+1)return i+5;return 9;", 5),
    ("int x=1;;if(x);else;return x;", 1),
])
def test_braces_preserve_dangling_else_loop_headers_scopes_and_empty_statements(body, expected):
    original = parse(f"int main(){{{body}}}")
    emitted = emit_c(original)
    round_trip = parse(emitted)
    assert _execute_tac(round_trip) == expected
    assert format_ir(lower_ir(round_trip)) == format_ir(lower_ir(original))


def test_declaration_and_assignment_loop_headers_have_exactly_two_separators():
    source = "int main(){int total=0;int i;for(i=0;i<2;i=i+1)total=total+i;for(int j=0;j<2;j=j+1);return total;}"
    emitted = emit_c(parse(source))
    headers = [line.strip() for line in emitted.splitlines() if line.strip().startswith("for ")]
    assert headers == [
        "for (i = (0); ((i) < (2)); i = ((i) + (1))) {",
        "for (int j = (0); ((j) < (2)); j = ((j) + (1))) {",
    ]
    assert all(line.count(";") == 2 for line in headers)
    assert _execute_tac(parse(emitted)) == 1


def test_emission_keeps_dead_source_and_its_diagnostics_instead_of_optimizing_it():
    original = parse("int main(){return 1;int x;return x/0;}")
    emitted = emit_c(original)
    round_trip = parse(emitted)
    assert "int x;" in emitted and "return ((x) / (0));" in emitted
    assert len(round_trip.function.body.items) == 3
    assert [diagnostic.code for diagnostic in analyze(round_trip).diagnostics] == [
        "UNREACHABLE_STATEMENT", "UNREACHABLE_STATEMENT",
    ]
    assert _execute_tac(round_trip) == 1


@pytest.mark.parametrize("body,code", [
    ("return x;", "UNDECLARED_VARIABLE"),
    ("int x;return x;", "UNINITIALIZED_VARIABLE"),
    ("int x=0;{int x=1;}return x;", "DUPLICATE_DECLARATION"),
    ("return 1/0;", "DIVISION_BY_ZERO"),
    ("return 1%0;", "MODULO_BY_ZERO"),
    ("return 2147483647+1;", "INTEGER_OVERFLOW"),
    ("int x=1;", "MISSING_RETURN"),
])
def test_emitter_reuses_source_located_semantic_validation(body, code):
    program = parse(f"int main(){{{body}}}")
    with pytest.raises(SemanticError) as caught:
        emit_c(program)
    assert caught.value.diagnostic.code == code
    assert caught.value.diagnostic.span.start_line == 1
    assert caught.value.diagnostic.span.start_column >= 1


def test_output_is_deterministic_and_original_nodes_and_provenance_are_unchanged():
    source = "int main(){int x=0;for(int i=0;i<3;i=i+1){if(i)x=x+i;else;}return x;}"
    original = parse(source)
    before = ast.ast_to_dict(original)
    node_objects = tuple(ast.walk(original))
    emitted = emit_c(original)
    assert emit_c(original) == emit_c(parse(source)) == emitted
    assert ast.ast_to_dict(original) == before
    assert all(left is right for left, right in zip(ast.walk(original), node_objects))
    assert emitted.endswith("\n") and not emitted.endswith("\n\n")
    assert "\t" not in emitted

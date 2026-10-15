"""TAC structure and executable control-flow semantics, without benchmarking."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from compiler import ast_nodes as ast
from compiler.ir import (
    Binary, Branch, Constant, Copy, IRProgram, Jump, Label, Return, SymbolRef,
    TempRef, Unary, format_instruction, format_ir, lower_ir, validate,
)
from compiler.parser import parse


def execute_ir(program: IRProgram) -> int:
    """Small test-only TAC oracle; not a product runtime or performance backend."""
    values = {}
    labels = {instruction.name: index for index, instruction in enumerate(program.instructions)
              if isinstance(instruction, Label)}

    def read(operand):
        return operand.value if isinstance(operand, Constant) else values[operand]

    def operation(operator, left, right):
        if operator == "+":
            return left + right
        if operator == "-":
            return left - right
        if operator == "*":
            return left * right
        if operator in ("/", "%"):
            quotient = (abs(left) // abs(right)) * (-1 if (left < 0) != (right < 0) else 1)
            return quotient if operator == "/" else left - quotient * right
        return int({"<": left < right, "<=": left <= right, ">": left > right,
                    ">=": left >= right, "==": left == right, "!=": left != right}[operator])

    index = 0
    for _ in range(10000):
        instruction = program.instructions[index]
        index += 1
        if isinstance(instruction, Copy):
            values[instruction.destination] = read(instruction.operand)
        elif isinstance(instruction, Unary):
            value = read(instruction.operand)
            values[instruction.destination] = value if instruction.operator == "+" else -value
        elif isinstance(instruction, Binary):
            values[instruction.destination] = operation(
                instruction.operator.value, read(instruction.left), read(instruction.right),
            )
        elif isinstance(instruction, Branch):
            index = labels[instruction.true_label if read(instruction.condition) else instruction.false_label]
        elif isinstance(instruction, Jump):
            index = labels[instruction.label]
        elif isinstance(instruction, Return):
            return read(instruction.operand)
        else:
            assert isinstance(instruction, Label)
    raise AssertionError("TAC did not return within test execution bound")


@pytest.mark.parametrize("body,expected", [
    ("return 2+3*4;", 14),
    ("return (2+3)*4;", 20),
    ("return 20-6-3;", 11),
    ("int x=1; x=x+2; x=x*3; return x;", 9),
    ("int x; x=4; return x;", 4),
    ("int x=1; {int y=3; x=x+y;} return x;", 4),
    ("if(1)return 7;else return 9;", 7),
    ("if(0)return 7;else return 9;", 9),
    ("int x=2;if(1)x=3;return x;", 3),
    ("int x=2;if(0)x=3;return x;", 2),
    ("int x;if(1)x=3;else x=4;return x;", 3),
    ("int x;if(0)x=3;else x=4;return x;", 4),
    ("if(1){if(0)return 8;else return 6;}else return 9;", 6),
    ("int x=0;for(int i=0;i<4;i=i+1)x=x+i;return x;", 6),
    ("int x=0;for(int i=4;i<4;i=i+1)x=x+1;return x;", 0),
    ("int i;for(i=1;i<=5;i=i+1);return i;", 6),
    ("int i;for(i=3;i>0;i=i-1);return i;", 0),
    ("int x=0;for(int i=0;i<3;i=i+1){for(int j=0;j<2;j=j+1)x=x+i*j;}return x;", 3),
    ("for(int i=0;i<3;i=i+1)return i+7;return 99;", 7),
    ("for(int i=3;i<3;i=i+1)return 7;return 99;", 99),
    ("int x=0;for(int i=0;i<5;i=i+1){if(i==3)return x;x=x+i;}return 99;", 3),
    ("return -7/3;", -2),
    ("return 7/-3;", -2),
    ("return -7%3;", -1),
    ("return 7%-3;", 1),
    ("return -7%-3;", -1),
    ("return + - + 7;", -7),
])
def test_tac_computes_expected_source_results(body, expected):
    assert execute_ir(lower_ir(parse(f"int main(){{{body}}}"))) == expected


@pytest.mark.parametrize("operator,expected", [
    ("<", 0), ("<=", 0), (">", 1), (">=", 1), ("==", 0), ("!=", 1),
])
def test_relational_results_are_integer_booleans(operator, expected):
    assert execute_ir(lower_ir(parse(f"int main(){{return 4{operator}2;}}"))) == expected


def test_arithmetic_is_lowered_in_order_without_folding():
    program = lower_ir(parse("int main(){int x=2+3*4;return x;}"))
    assert format_ir(program) == "%t0 = 3 * 4\n%t1 = 2 + %t0\nx = %t1\nreturn x"
    multiply, add, copy, result = program.instructions
    assert isinstance(multiply, Binary) and multiply.left == Constant(3)
    assert add.right == multiply.destination
    assert isinstance(copy, Copy) and copy.operand == add.destination
    assert isinstance(result.operand, SymbolRef)
    assert result.operand.symbol_id == program.symbols[0].symbol_id


def test_identifier_storage_and_temporary_names_are_unambiguous():
    program = lower_ir(parse("int main(){int t0=2;int L0=3;return t0+L0;}"))
    assert format_ir(program) == "t0 = 2\nL0 = 3\n%t0 = t0 + L0\nreturn %t0"
    assert execute_ir(program) == 5
    assert isinstance(program.instructions[2].destination, TempRef)


def test_uninitialized_declaration_allocates_symbol_without_fake_value_assignment():
    program = lower_ir(parse("int main(){int x; x=7;return x;}"))
    assert len(program.symbols) == 1
    assert format_ir(program) == "x = 7\nreturn x"


def test_if_else_branch_and_jump_paths_join_before_following_return():
    program = lower_ir(parse("int main(){int x;if(1)x=2;else x=3;return x;}"))
    assert format_ir(program) == (
        "if 1 goto L0 else goto L1\nL0:\nx = 2\ngoto L2\nL1:\nx = 3\nL2:\nreturn x"
    )


def test_loop_condition_is_recomputed_and_update_precedes_back_edge():
    instructions = lower_ir(parse("int main(){for(int i=0;i<2;i=i+1);return 0;}")).instructions
    condition = next(i for i, instruction in enumerate(instructions)
                     if isinstance(instruction, Binary) and instruction.operator == "<")
    assert isinstance(instructions[condition - 1], Label)
    branch = instructions[condition + 1]
    back = next(instruction for instruction in instructions if isinstance(instruction, Jump))
    assert isinstance(branch, Branch) and back.label == instructions[condition - 1].name
    update = next(i for i, instruction in enumerate(instructions)
                  if isinstance(instruction, Binary) and instruction.operator == "+")
    assert condition < update < instructions.index(back)


def test_returning_loop_body_has_no_update_or_back_edge():
    program = lower_ir(parse("int main(){for(int i=0;i<2;i=i+1)return i;return 9;}"))
    assert not any(isinstance(instruction, Jump) for instruction in program.instructions)
    assert not any(isinstance(instruction, Binary) and instruction.operator == "+" for instruction in program.instructions)
    assert len([instruction for instruction in program.instructions if isinstance(instruction, Return)]) == 2
    assert any(diagnostic.code == "UNREACHABLE_STATEMENT" for diagnostic in program.diagnostics)


def test_dead_sequential_source_is_warned_and_not_attached_after_return():
    program = lower_ir(parse("int main(){int x=1;return x;x=2;}"))
    assert format_ir(program) == "x = 1\nreturn x"
    assert len(program.diagnostics) == 1
    assert program.diagnostics[0].severity == "warning"


def test_both_returning_arms_do_not_acquire_a_merge_jump():
    program = lower_ir(parse("int main(){if(1)return 2;else return 3;}"))
    assert not any(isinstance(instruction, Jump) for instruction in program.instructions)
    assert isinstance(program.instructions[-1], Return)


def test_metadata_determinism_immutability_and_source_ast_preservation():
    source = "int main(){int x=0;for(int i=0;i<2;i=i+1){if(i==0)x=x+1;else x=x+2;}return x;}"
    tree = parse(source)
    before = ast.ast_to_dict(tree)
    first, second = lower_ir(tree), lower_ir(tree)
    assert first == second == lower_ir(parse(source))
    assert ast.ast_to_dict(tree) == before
    nodes = {node.node_id: node for node in ast.walk(tree)}
    for instruction in first.instructions:
        assert instruction.span == nodes[instruction.node_id].span
    with pytest.raises(FrozenInstanceError):
        first.instructions[0].node_id = "changed"


def test_validate_returns_none_and_lowering_rejects_semantically_invalid_source():
    from compiler.diagnostics import SemanticError
    assert validate(parse("int main(){return 1;}")) is None
    for source in ("int main(){return missing;}", "int main(){int x;return x;}", "int main(){}"):
        with pytest.raises(SemanticError):
            lower_ir(parse(source))


@pytest.mark.parametrize("example,expected", [
    ("basic/minimal.c", 0), ("basic/arithmetic.c", 15), ("basic/assignments.c", 14),
    ("basic/simple_if.c", 5), ("basic/if_else.c", 7), ("basic/nested_if_else.c", 5),
    ("loops/sum.c", 6), ("loops/arithmetic.c", 10), ("loops/nested.c", 3),
])
def test_all_existing_valid_examples_lower_to_correct_results(example, expected):
    root = Path(__file__).resolve().parents[1]
    assert execute_ir(lower_ir(parse((root / "examples" / example).read_text()))) == expected

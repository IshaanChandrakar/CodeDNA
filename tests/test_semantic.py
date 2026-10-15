"""Observable semantic behavior: lexical names, definite reads and C arithmetic."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from compiler.ast_nodes import Declaration, Identifier, ast_to_json, walk
from compiler.diagnostics import Diagnostic, FrontendError, SemanticError
from compiler.parser import parse
from compiler.semantic import analyze, validate


def check(body):
    return analyze(parse(f"int main(){{{body}}}"))


def fails(body, code):
    with pytest.raises(SemanticError) as caught:
        check(body)
    assert isinstance(caught.value, FrontendError)
    diagnostic = caught.value.diagnostic
    assert diagnostic.stage == "semantic"
    assert diagnostic.code == code
    assert diagnostic.severity == "error"
    assert diagnostic.span.start_line >= 1
    assert diagnostic.span.start_column >= 1
    return diagnostic


@pytest.mark.parametrize("body", [
    "return 0;",
    "int x; x=3; return x;",
    "int x=1; {int y=x+1; x=y;} return x;",
    "int x; if(1) x=1; else x=2; return x;",
    "int x; if(1) return 0; else x=2; return x;",
    "int x; if(1) x=1; else return 0; return x;",
    "int x; if(1){if(1)x=1;else return 0;}else x=2;return x;",
    "if(1)return 1;else return 2;",
    "int x; for(x=0;x<3;x=x+1); return x;",
    "for(int i=0;i<3;i=i+1){int x; x=i; if(x) return x;}return 0;",
    "int x=1; for(int i=0;i<2;i=i+1){x=x+1;}return x;",
    "int x=-2147483647-1; return x;",
])
def test_valid_declarations_scopes_initialized_reads_and_live_return_paths(body):
    assert check(body).diagnostics == ()


@pytest.mark.parametrize("body", [
    "return x;",
    "x=1;return 0;",
    "int x=y;return 0;",
    "{int x=1;}return x;",
    "if(1){int x=1;}else{return x;}return 0;",
    "for(int i=0;i<3;i=i+1);return i;",
    "for(int i=0;i<3;i=x){int x=1;}return 0;",
    "for(int i=0;i<3;i=i+1);i=0;return 0;",
    "return 0; x=1;",
    "return 0;int x=y;",
])
def test_undeclared_or_out_of_scope_names_are_errors_even_in_dead_syntax(body):
    fails(body, "UNDECLARED_VARIABLE")


@pytest.mark.parametrize("body", [
    "int x=0;int x=1;return x;",
    "int x=0;{int x=1;}return x;",
    "{int x=0;}{int x=1;}return 0;",
    "if(1){int x=0;}else{int x=1;}return 0;",
    "for(int i=0;i<2;i=i+1);for(int i=0;i<2;i=i+1);return 0;",
    "return 0;int x=1;int x=2;",
    "{int x=1;}int x=2;return x;",
])
def test_duplicate_names_are_forbidden_across_all_of_main(body):
    fails(body, "DUPLICATE_DECLARATION")


@pytest.mark.parametrize("body", [
    "int x;return x;",
    "int x=x;return x;",
    "int x; x=x+1;return x;",
    "int x; if(1)x=1;return x;",
    "int x; if(0)x=1;return x;",
    "int x; if(1)x=1;else;return x;",
    "int x; if(1){if(1)x=1;}else x=2;return x;",
    "int x;for(int i=0;i<3;i=i+1)x=1;return x;",
    "int x;for(int i=0;i<3;i=i+1){if(i)x=1;return x;}return 0;",
    "int x;for(int i=0;i<3;i=i+1){return x;}return 0;",
    "int x;for(int i=0;i<3;i=x);return 0;",
    "int x;for(int i=x;i<3;i=i+1);return 0;",
    "int x;for(int i=0;x<3;i=i+1);return 0;",
])
def test_every_possible_evaluated_read_requires_definite_initialization(body):
    fails(body, "UNINITIALIZED_VARIABLE")


@pytest.mark.parametrize("body", [
    "", "int x=0;", "if(1)return 1;",
    "if(0)return 1;", "for(int i=0;i<3;i=i+1)return i;",
    "for(int i=0;1;i=i+1);",
])
def test_reachable_function_exits_require_explicit_returns(body):
    fails(body, "MISSING_RETURN")


def test_scope_error_span_points_to_the_actual_read():
    source = "int main(){\n  {int hidden=2;}\n  return hidden;\n}"
    with pytest.raises(SemanticError) as caught:
        analyze(parse(source))
    diagnostic = caught.value.diagnostic
    assert (diagnostic.span.start_line, diagnostic.span.start_column) == (3, 10)
    assert source[diagnostic.span.start_offset:diagnostic.span.end_offset] == "hidden"
    assert diagnostic.format("scope.c") == (
        "scope.c:3:10: semantic error [UNDECLARED_VARIABLE]: "
        "Variable 'hidden' is undeclared or outside its scope"
    )


@pytest.mark.parametrize("body,code", [
    ("return 3/0;", "DIVISION_BY_ZERO"),
    ("return 3%0;", "MODULO_BY_ZERO"),
    ("int x=2;return 3/(x-2);", "DIVISION_BY_ZERO"),
    ("int x=2;x=x-2;return 3%x;", "MODULO_BY_ZERO"),
    ("int x;if(1)x=0;else x=0;return 1/x;", "DIVISION_BY_ZERO"),
    ("int x;if(1)return 0;else x=0;return 1/x;", "DIVISION_BY_ZERO"),
    ("int x;if(1)x=0;else return 0;return 1%x;", "MODULO_BY_ZERO"),
    ("return 2147483647+1;", "INTEGER_OVERFLOW"),
    ("return (-2147483647-1)-1;", "INTEGER_OVERFLOW"),
    ("return 65536*65536;", "INTEGER_OVERFLOW"),
    ("int x=-2147483647-1;return -x;", "INTEGER_OVERFLOW"),
    ("int x=-2147483647-1;return x/-1;", "INTEGER_OVERFLOW"),
    ("int x=-2147483647-1;return x%-1;", "INTEGER_OVERFLOW"),
    ("int x=2147483647;x=x+1;return x;", "INTEGER_OVERFLOW"),
])
def test_proven_undefined_arithmetic_has_semantic_diagnostics(body, code):
    fails(body, code)


@pytest.mark.parametrize("expression", [
    "(-7/3)+2", "(7/-3)+2", "(-7/-3)-2", "(7/3)-2",
    "(-7%3)+1", "(7%-3)-1", "(-7%-3)+1", "(7%3)-1",
    "(1<2)-1", "(2<=2)-1", "(3>2)-1", "(3>=3)-1",
    "(2==2)-1", "(2!=3)-1", "(2<1)", "(3<=2)",
    "(2>3)", "(2>=3)", "(2==3)", "(3!=3)",
    "+0",
])
def test_constant_diagnostics_use_c_division_remainder_and_comparison_values(expression):
    fails(f"return 1/({expression});", "DIVISION_BY_ZERO")


@pytest.mark.parametrize("body", [
    "int x;if(1)x=0;else x=1;return 1/x;",
    "int x=0;for(int i=0;i<3;i=i+1){x=x+1;int y=1/x;}return x;",
    "int x=0;for(int i=0;i<3;i=i+1){int y=1/x;x=1;}return x;",
    "int x=0;for(int i=0;i<3;i=i+1)x=1;return 1/x;",
    "int x=2147483647;for(int i=0;i<3;i=i+1)x=x+1;return x;",
    "int x=0;for(int i=0;1/x;i=i+1)x=1;return x;",
    "int x=0;for(int i=0;i<2;i=1/x){x=1;}return x;",
    "int x=0;for(int i=0;i<2;i=i+1){for(x=1;x<2;x=x+1);int y=1/x;}return x;",
])
def test_unknown_or_loop_carried_values_do_not_create_false_static_arithmetic_errors(body):
    # These examples are accepted by conservative static checks. This is not a
    # claim that their runtime-dependent arithmetic is always defined/terminating.
    check(body)


def test_known_zero_introduced_in_the_loop_body_is_still_diagnosed():
    fails("for(int i=0;i<3;i=i+1){int x=0;int y=1/x;}return 0;", "DIVISION_BY_ZERO")


def test_zero_divisor_span_preserves_expression_parentheses_and_source_line():
    source = "int main(){\n  int x=4;\n  return x / (x - 4);\n}"
    with pytest.raises(SemanticError) as caught:
        analyze(parse(source))
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == "DIVISION_BY_ZERO"
    assert diagnostic.span.start_line == 3
    assert source[diagnostic.span.start_offset:diagnostic.span.end_offset] == "(x - 4)"


def test_unreachable_statements_warn_without_evaluating_reads_or_arithmetic():
    source = "int main(){return 0;int x;{x=1/0;return x;}}"
    program = parse(source)
    result = analyze(program)
    dead_nodes = program.function.body.items[1:]
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["UNREACHABLE_STATEMENT"] * 2
    assert all(diagnostic.severity == "warning" for diagnostic in result.diagnostics)
    assert result.unreachable_node_ids == frozenset(node.node_id for item in dead_nodes for node in walk(item))
    assert "semantic warning [UNREACHABLE_STATEMENT]" in result.diagnostics[0].format("dead.c")
    assert validate(program) is None


def test_loop_update_after_body_returns_is_unreachable_and_has_no_evaluated_read():
    program = parse("int main(){int x;for(int i=0;i<3;i=x){if(i)return 1;else return 2;}return 0;}")
    loop = program.function.body.items[1]
    result = analyze(program)
    assert result.unreachable_node_ids == frozenset(node.node_id for node in walk(loop.update))
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].span == loop.update.span


def test_returning_both_arms_makes_the_following_statement_unreachable():
    result = check("int x;if(1)return 1;else return 2;return x;")
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "UNREACHABLE_STATEMENT"


def test_if_and_loop_conditions_do_not_claim_constant_path_or_termination_proofs():
    fails("int x;if(1)x=2;return x;", "UNINITIALIZED_VARIABLE")
    fails("for(int i=0;1;i=i+1)return 1;", "MISSING_RETURN")
    fails("if(0)return 1/0;return 0;", "DIVISION_BY_ZERO")


def test_annotations_bind_declarations_reads_and_targets_without_mutating_the_ast():
    source = "int main(){int x=1;{int y=x;x=y;}for(int i=x;i<3;i=i+1)x=x+i;return x;}"
    program = parse(source)
    original = ast_to_json(program)
    result = analyze(program)
    assert [(symbol.symbol_id, symbol.name) for symbol in result.symbols] == [("s0", "x"), ("s1", "y"), ("s2", "i")]
    for node in walk(program):
        if isinstance(node, (Declaration, Identifier)):
            assert result.bindings[node.node_id].name == node.name
    for symbol in result.symbols:
        assert result.bindings[symbol.declaration_id] is symbol
    assert ast_to_json(program) == original
    assert analyze(parse(source)) == result


def test_analysis_records_and_binding_mapping_are_immutable():
    result = check("int x=1;return x;")
    with pytest.raises(FrozenInstanceError):
        result.symbols[0].name = "changed"
    with pytest.raises(FrozenInstanceError):
        result.symbols = ()
    with pytest.raises(TypeError):
        result.bindings["extra"] = result.symbols[0]


def test_fresh_analyses_do_not_leak_symbols_or_diagnostics():
    assert check("int x=1;return x;").symbols[0].symbol_id == "s0"
    assert check("return 1;return 2;").diagnostics
    clean = check("int x=2;return x;")
    assert clean.symbols[0].symbol_id == "s0"
    assert clean.diagnostics == () and clean.unreachable_node_ids == frozenset()


def test_existing_phase_one_diagnostic_format_remains_unchanged():
    span = parse("int main(){return 0;}").span
    diagnostic = Diagnostic("parser", "UNEXPECTED_TOKEN", "example", span)
    assert diagnostic.format("old.c") == "old.c:1:1: parser error [UNEXPECTED_TOKEN]: example"


EXAMPLES = sorted((Path(__file__).resolve().parents[1] / "examples" / "basic").glob("*.c")) + sorted(
    (Path(__file__).resolve().parents[1] / "examples" / "loops").glob("*.c")
)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_all_existing_valid_examples_pass_semantic_validation(path):
    assert validate(parse(path.read_text(encoding="utf-8"))) is None

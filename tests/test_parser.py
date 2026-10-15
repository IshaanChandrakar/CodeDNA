"""Real AST shape checks and rejection of syntax outside the documented subset."""

from io import StringIO

import pytest
from ply import yacc

from compiler.ast_nodes import (
    Assignment, BinaryExpression, BinaryOperator, Block, Declaration, EmptyStatement,
    For, If, IntegerLiteral, Return, UnaryExpression, UnaryOperator, ast_to_dict,
)
from compiler.diagnostics import FrontendError, LexicalError, ParseError
from compiler.lexer import build_lexer
from compiler.parser import _Grammar, parse


def expression(source):
    return parse(f"int main() {{ return {source}; }}").function.body.items[0].value


def shape(node):
    if isinstance(node, IntegerLiteral):
        return node.value
    if isinstance(node, UnaryExpression):
        return (node.operator.value, shape(node.operand))
    return (node.operator.value, shape(node.left), shape(node.right))


@pytest.mark.parametrize("signature", ["int main()", "int main(void)"])
def test_entry_forms(signature):
    program = parse(signature + " { return 0; }")
    assert program.function.name == "main"
    assert program.function.return_type == "int"
    assert program.schema_version == 1
    assert isinstance(program.function.body.items[0], Return)


def test_declarations_assignments_and_nested_blocks():
    program = parse("int main(){ int x; int y=2; x=y+1; { x=x*2; ; } return x; }")
    x, y, assignment, block, result = program.function.body.items
    assert isinstance(x, Declaration) and x.name == "x" and x.initializer is None
    assert isinstance(y, Declaration) and y.initializer.value == 2
    assert isinstance(assignment, Assignment) and assignment.target.name == "x"
    assert assignment.value.operator == BinaryOperator.ADD
    assert assignment.value.left.name == "y"
    assert isinstance(block, Block)
    assert isinstance(block.items[0], Assignment)
    assert isinstance(block.items[1], EmptyStatement)
    assert result.value.name == "x"


@pytest.mark.parametrize("source,expected", [
    ("2+3*4", ("+", 2, ("*", 3, 4))),
    ("(2+3)*4", ("*", ("+", 2, 3), 4)),
    ("12-3-2", ("-", ("-", 12, 3), 2)),
    ("12/3*2%5", ("%", ("*", ("/", 12, 3), 2), 5)),
    ("1+2<3*4==5!=6", ("!=", ("==", ("<", ("+", 1, 2), ("*", 3, 4)), 5), 6)),
    ("1<2<=3>4>=5", (">=", (">", ("<=", ("<", 1, 2), 3), 4), 5)),
    ("1==2!=3", ("!=", ("==", 1, 2), 3)),
    ("-2*+3", ("*", ("-", 2), ("+", 3))),
    ("- + - 1", ("-", ("+", ("-", 1)))),
    ("-(2+3)", ("-", ("+", 2, 3))),
])
def test_precedence_associativity_and_parentheses(source, expected):
    assert shape(expression(source)) == expected


@pytest.mark.parametrize("operator", [member.value for member in BinaryOperator])
def test_every_binary_operator_has_a_typed_ast_operator(operator):
    result = expression(f"4 {operator} 2")
    assert isinstance(result, BinaryExpression)
    assert result.operator is BinaryOperator(operator)


@pytest.mark.parametrize("operator", ["+", "-"])
def test_unary_operator_types(operator):
    result = expression(operator + "1")
    assert isinstance(result, UnaryExpression)
    assert result.operator is UnaryOperator(operator)


def test_simple_if_and_if_else():
    first, second, _ = parse(
        "int main(){ if(1) return 2; if(0){return 3;}else{return 4;} return 0; }"
    ).function.body.items
    assert isinstance(first, If) and first.else_branch is None
    assert isinstance(first.then_branch, Return) and first.then_branch.value.value == 2
    assert isinstance(second.then_branch, Block) and isinstance(second.else_branch, Block)
    assert second.else_branch.items[0].value.value == 4


def test_else_binds_to_nearest_if_without_braces():
    outer = parse("int main(){if(1) if(2) return 3; else return 4; return 5;}").function.body.items[0]
    assert isinstance(outer, If) and outer.else_branch is None
    assert isinstance(outer.then_branch, If)
    assert outer.then_branch.else_branch.value.value == 4


def test_braces_allow_else_to_bind_to_outer_if():
    outer = parse("int main(){if(1){if(2)return 3;}else return 4;return 5;}").function.body.items[0]
    assert isinstance(outer.then_branch, Block)
    assert outer.then_branch.items[0].else_branch is None
    assert outer.else_branch.value.value == 4


def test_two_else_clauses_bind_to_two_nested_ifs():
    outer = parse("int main(){if(1)if(2)return 3;else return 4;else return 5;}").function.body.items[0]
    assert outer.then_branch.else_branch.value.value == 4
    assert outer.else_branch.value.value == 5


@pytest.mark.parametrize("initializer,node_type", [("int i=0", Declaration), ("i=0", Assignment)])
@pytest.mark.parametrize("body", ["{ x=x+i*2; }", "x=x+i;", ";"])
def test_for_components_and_body_forms(initializer, node_type, body):
    loop = parse(f"int main(){{for({initializer};i<4;i=i+1){body}return 0;}}").function.body.items[0]
    assert isinstance(loop, For)
    assert isinstance(loop.initializer, node_type)
    assert loop.condition.operator is BinaryOperator.LESS
    assert loop.condition.left.name == "i" and loop.condition.right.value == 4
    assert loop.update.target.name == "i"
    assert loop.update.value.operator is BinaryOperator.ADD
    assert isinstance(loop.body, (Block, Assignment, EmptyStatement))


def test_nested_loops_and_arithmetic():
    outer = parse(
        "int main(){for(int i=0;i<2;i=i+1){for(int j=0;j<3;j=j+1)x=x+i*j;}return 0;}"
    ).function.body.items[0]
    inner = outer.body.items[0]
    assert isinstance(inner, For)
    assert inner.initializer.name == "j"
    assert inner.body.value.right.operator is BinaryOperator.MULTIPLY


def test_syntactic_constructs_are_not_semantically_analyzed():
    # These are grammar-valid; declaration scope, overflow, and returns are Phase 2.
    program = parse("int main(){int x; int x; missing=1/0; return unknown;}")
    assert len(program.function.body.items) == 4
    assert parse("int main(){}").function.body.items == ()


@pytest.mark.parametrize("source", [
    "int main(){int x=1 return x;}",
    "int main(){return (1+2;}",
    "int main(){return 1+;}",
    "int main(){return;}",
    "int main(){else return 1;}",
    "int main(){for(;1;x=x+1);return 0;}",
    "int main(){for(x=0;;x=x+1);return 0;}",
    "int main(){for(x=0;x<1;);return 0;}",
    "int main(){for(int i;i<1;i=i+1);return 0;}",
    "int main(){if(1)int x=0;return 0;}",
    "int main(){return (x=1);}",
    "int main(){int *x;return 0;}",
    "int main(){foo();return 0;}",
    "int main(int x){return x;}",
    "int main(void x){return x;}",
    "void main(){return 0;}",
    "int x; int main(){return 0;}",
    "int main(){return 0;} int other(){return 0;}",
    "int main(){return 0;} trailing",
])
def test_unsupported_or_invalid_syntax_is_rejected(source):
    with pytest.raises(ParseError) as caught:
        parse(source)
    assert caught.value.diagnostic.stage == "parser"
    assert caught.value.diagnostic.code == "UNEXPECTED_TOKEN"


def test_only_main_is_an_entry_point():
    with pytest.raises(ParseError) as caught:
        parse("int other(){return 0;}")
    assert caught.value.diagnostic.code == "INVALID_ENTRY_POINT"
    assert caught.value.diagnostic.span.start_column == 5


@pytest.mark.parametrize("source", ["", "// nothing", "int", "int main(", "int main(){return 0;\n"])
def test_eof_diagnostic_has_a_zero_width_source_position(source):
    with pytest.raises(ParseError) as caught:
        parse(source)
    span = caught.value.diagnostic.span
    assert caught.value.diagnostic.code == "UNEXPECTED_EOF"
    assert span.start_offset == span.end_offset == len(source)
    if source.endswith("\n"):
        assert (span.start_line, span.start_column) == (2, 1)


def test_unexpected_token_reports_its_exact_source_location():
    source = "int main() {\n    int x = 1\n    return x;\n}"
    with pytest.raises(ParseError) as caught:
        parse(source)
    diagnostic = caught.value.diagnostic
    assert (diagnostic.span.start_line, diagnostic.span.start_column) == (3, 5)
    assert source[diagnostic.span.start_offset:diagnostic.span.end_offset] == "return"
    assert "RETURN" in diagnostic.message


@pytest.mark.parametrize("source,code", [
    ("int main(){return @;}", "ILLEGAL_CHARACTER"),
    ("int main(){int x=1,y=2;return x;}", "ILLEGAL_CHARACTER"),
    ("int main(){return ++x;}", "UNSUPPORTED_OPERATOR"),
    ("int main(){return --x;}", "UNSUPPORTED_OPERATOR"),
    ("int main(){while(1);return 0;}", "UNSUPPORTED_KEYWORD"),
])
def test_lexical_errors_propagate_through_parser(source, code):
    with pytest.raises(LexicalError) as caught:
        parse(source)
    assert caught.value.diagnostic.code == code


def test_repeated_parses_after_errors_are_independent():
    source = "int main(){return 2+3;}"
    first = ast_to_dict(parse(source))
    for invalid in ("int main(", "int main(){return @;}"):
        with pytest.raises(FrontendError):
            parse(invalid)
    parse("int main(){int x=9;return x;}")
    assert ast_to_dict(parse(source)) == first


def test_ply_lalr_build_has_no_unresolved_conflicts_or_generated_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    errors, debug = StringIO(), StringIO()
    grammar = _Grammar(build_lexer("int main(){return 0;}"))
    parser = yacc.yacc(
        module=grammar, start="program", debug=True, write_tables=False,
        tabmodule="compiler._ply_tables", errorlog=yacc.PlyLogger(errors), debuglog=yacc.PlyLogger(debug),
    )
    assert parser.parse(lexer=grammar.lexer).function.name == "main"
    assert "conflict" not in errors.getvalue().lower()
    assert "WARNING" not in errors.getvalue()
    assert "ERROR" not in errors.getvalue()
    assert list(tmp_path.iterdir()) == []

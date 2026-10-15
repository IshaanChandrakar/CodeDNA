"""Traversal, hierarchy, immutable nodes, spans, and actual JSON serialization."""

from dataclasses import FrozenInstanceError
import json

import pytest

from compiler.ast_nodes import (
    Assignment, BinaryExpression, Block, Declaration, EmptyStatement, For, Function,
    Identifier, If, IntegerLiteral, Program, Return, UnaryExpression, ast_to_dict,
    ast_to_json, iter_child_nodes, walk,
)
from compiler.diagnostics import SourceMap
from compiler.parser import parse


def test_all_documented_node_kinds_are_traversable():
    program = parse("""int main(void){
        int x=0;
        for(int i=0;i<2;i=i+1){
            if(i!=0)x=x+-i;else;
        }
        return x;
    }""")
    nodes = tuple(walk(program))
    assert {type(node) for node in nodes} == {
        Program, Function, Block, Declaration, For, If, Assignment, Return,
        EmptyStatement, Identifier, IntegerLiteral, UnaryExpression, BinaryExpression,
    }
    assert tuple(iter_child_nodes(program)) == (program.function,)
    assert tuple(iter_child_nodes(program.function)) == (program.function.body,)
    assert tuple(iter_child_nodes(program.function.body)) == program.function.body.items
    loop = program.function.body.items[1]
    assert tuple(iter_child_nodes(loop)) == (loop.initializer, loop.condition, loop.update, loop.body)
    assert len({node.node_id for node in nodes}) == len(nodes)


def test_source_spans_enclose_children_and_select_exact_constructs():
    source = "// prefix\nint main(void) {\n  int x = 2 + 3;\n  x = (x * 4);\n  return -x;\n}\n"
    program = parse(source)
    declarations, assignment, result = program.function.body.items
    for node in walk(program):
        assert 0 <= node.span.start_offset < node.span.end_offset <= len(source)
        for child in iter_child_nodes(node):
            assert node.span.start_offset <= child.span.start_offset
            assert child.span.end_offset <= node.span.end_offset
    def text(node):
        return source[node.span.start_offset:node.span.end_offset]
    assert text(declarations) == "int x = 2 + 3;"
    assert text(assignment) == "x = (x * 4);"
    assert text(assignment.value) == "(x * 4)"
    assert text(result) == "return -x;"
    assert text(program).startswith("int main") and text(program).endswith("}")
    assert (result.span.start_line, result.span.start_column) == (5, 3)
    assert (result.span.end_line, result.span.end_column) == (5, 13)


def test_parenthesized_literal_keeps_one_node_and_inclusive_group_span():
    source = "int main(){return ((1));}"
    literal = parse(source).function.body.items[0].value
    assert isinstance(literal, IntegerLiteral) and literal.value == 1
    assert source[literal.span.start_offset:literal.span.end_offset] == "((1))"


def test_for_header_spans_do_not_include_separator_semicolons():
    source = "int main(){for(int i=0;i<2;i=i+1);return 0;}"
    loop = parse(source).function.body.items[0]
    assert source[loop.initializer.span.start_offset:loop.initializer.span.end_offset] == "int i=0"
    assert source[loop.update.span.start_offset:loop.update.span.end_offset] == "i=i+1"


def test_nodes_and_statement_sequences_are_immutable():
    program = parse("int main(){return 1;}")
    with pytest.raises(FrozenInstanceError):
        program.function.name = "other"
    with pytest.raises(FrozenInstanceError):
        program.function.body.items[0].value.value = 2
    assert isinstance(program.function.body.items, tuple)


def test_json_has_real_hierarchy_types_spans_and_plain_operator_strings():
    program = parse("int main(){int x=-2;return x+1;}")
    data = json.loads(ast_to_json(program))
    assert data == ast_to_dict(program)
    assert data["kind"] == "Program" and data["schema_version"] == 1
    body = data["function"]["body"]
    assert body["kind"] == "Block"
    assert body["items"][0]["initializer"]["kind"] == "UnaryExpression"
    assert body["items"][0]["initializer"]["operator"] == "-"
    assert body["items"][1]["value"]["operator"] == "+"
    assert body["items"][1]["value"]["left"]["name"] == "x"
    assert data["span"]["start_offset"] == 0
    assert "\n" in ast_to_json(program)
    assert "\n" not in ast_to_json(program, indent=None)
    assert ast_to_json(parse("int main(){int x=-2;return x+1;}")) == ast_to_json(program)


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_source_map_eof_and_end_positions(newline):
    source = "a" + newline + "bc" + newline
    mapping = SourceMap(source)
    span = mapping.span(source.index("b"), source.index("c") + 1)
    assert (span.start_line, span.start_column, span.end_line, span.end_column) == (2, 1, 2, 3)
    end = mapping.span(len(source), len(source))
    assert (end.start_line, end.start_column) == (3, 1)
    assert mapping.span(0, 0).start_column == 1


@pytest.mark.parametrize("start,end", [(-1, 0), (2, 1), (0, 5)])
def test_source_map_rejects_invalid_api_offsets(start, end):
    with pytest.raises(ValueError):
        SourceMap("abc").span(start, end)

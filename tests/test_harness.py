"""Controlled wrapper generation and strict full-integer observation protocol."""

from dataclasses import FrozenInstanceError, replace
import json
import shutil

import pytest

from compiler import ast_nodes as ast
from compiler.codegen import emit_c
from compiler.diagnostics import FrontendError, SemanticError
from compiler.parser import parse
from compiler.semantic import INT_MAX, INT_MIN, analyze
from runtime import harness
from runtime.harness import (
    MAX_OBSERVATION_BYTES, OBSERVATION_FILE, PROTOCOL_VERSION, ObservationError,
    make_harness, parse_observation,
)


def test_harness_wraps_only_the_known_generated_function_and_keeps_canonical_subset_source():
    program = parse("int main(){int main=257;return main;}")
    generated = make_harness(program)
    assert generated.canonical_source == emit_c(program)
    assert generated.source.startswith("static int codedna_entry(void) {\n")
    computation, wrapper = generated.source.split("/* Generated infrastructure:", 1)
    restored = "int main(void) {" + computation[len("static int codedna_entry(void) {"):]
    assert restored.rstrip() == generated.canonical_source.rstrip()
    assert "int main = (257);" in computation
    assert "return (main);" in computation
    assert "int main(void) {" in wrapper
    analyze(parse(generated.canonical_source))
    assert generated.observation_file == OBSERVATION_FILE == "codedna_observation.json"
    assert generated.protocol_version == PROTOCOL_VERSION == 1


@pytest.mark.parametrize("declarations,expected", [
    ("", "codedna_entry"),
    ("int codedna_entry=1;", "codedna_entry_1"),
    ("int codedna_entry=1;int codedna_entry_1=2;", "codedna_entry_2"),
    ("int codedna_entry=1;int codedna_entry_2=2;", "codedna_entry_1"),
    ("int CODEDNA_ENTRY=1;", "codedna_entry"),
])
def test_entry_name_avoids_all_user_declarations_with_a_deterministic_suffix(declarations, expected):
    program = parse(f"int main(){{{declarations}return 0;}}")
    generated = make_harness(program)
    assert generated.entry_name == expected
    assert f"static int {expected}(void) {{" in generated.source
    assert f"int codedna_return_value = {expected}();" in generated.source


def test_unreachable_declarations_also_reserve_names_without_losing_dead_source():
    program = parse("int main(){return 257;int codedna_entry=1;}")
    generated = make_harness(program)
    assert generated.entry_name == "codedna_entry_1"
    assert "int codedna_entry = (1);" in generated.source


def test_system_headers_follow_user_computation_so_their_macros_cannot_change_identifiers():
    names = ["EOF", "INT_MIN", "INT_MAX", "CHAR_BIT", "stdin", "stdout", "stderr", "FILE", "fopen", "fprintf"]
    declarations = "".join(f"int {name}={index};" for index, name in enumerate(names))
    program = parse(f"int main(){{{declarations}return {'+'.join(names)};}}")
    generated = make_harness(program)
    before_headers = generated.source.split("#include", 1)[0]
    for index, name in enumerate(names):
        assert f"int {name} = ({index});" in before_headers
    assert generated.source.index("#include <limits.h>") > generated.source.index("return ")
    assert generated.canonical_source == emit_c(program)


def test_wrapper_invokes_computation_once_and_separates_return_protocol_from_process_status():
    generated = make_harness(parse("int main(){return 257;}"))
    wrapper = generated.source.split("/* Generated infrastructure:", 1)[1]
    assert wrapper.count(f"{generated.entry_name}()") == 1
    assert f'fopen("{OBSERVATION_FILE}", "wx")' in wrapper
    assert "fprintf(codedna_observation," in wrapper
    assert "return codedna_return_value;" not in wrapper
    assert wrapper.endswith("    return 0;\n}\n")
    assert "printf(" not in wrapper.replace("fprintf(", "")
    assert all(f"return {code};" in wrapper for code in (120, 121, 122))
    assert wrapper.count("CODEDNA_OBSERVATION_ERROR") == 3


@pytest.mark.parametrize("value", [INT_MIN, -257, -1, 0, 1, 257, INT_MAX])
def test_generated_c_format_string_is_a_valid_full_integer_json_protocol(value):
    generated = make_harness(parse("int main(){return 0;}"))
    line = next(line for line in generated.source.splitlines() if 'protocol_version' in line and '%d' in line)
    # JSON string literals share the quote/newline escaping used here by C.
    # Decode the actual emitted format string independently before substituting
    # a mathematical expected integer; no OS exit-code truncation is involved.
    format_string = json.loads(line.strip().removesuffix(","))
    record = format_string % value
    assert json.loads(record) == {"protocol_version": 1, "return_value": value}
    assert parse_observation(record) == value


def test_target_assertions_explicitly_require_the_documented_signed_32_bit_environment():
    source = make_harness(parse("int main(){return 0;}" )).source
    assert '_Static_assert(CHAR_BIT == 8, "CODEDNA_TARGET_INT32:' in source
    assert '_Static_assert(sizeof(int) == 4, "CODEDNA_TARGET_INT32:' in source
    assert "INT_MIN == (-2147483647 - 1) && INT_MAX == 2147483647" in source
    assert source.count("CODEDNA_TARGET_INT32") == 3


def test_folded_int_min_and_original_ast_are_preserved_without_extending_the_frontend():
    original = parse("int main(){return 0;}")
    returned = original.function.body.items[0]
    folded = replace(original, function=replace(original.function, body=replace(
        original.function.body, items=(replace(returned, value=replace(returned.value, value=INT_MIN)),),
    )))
    before = ast.ast_to_dict(folded)
    nodes = tuple(ast.walk(folded))
    generated = make_harness(folded)
    assert "return (-2147483647 - 1);" in generated.canonical_source
    analyze(parse(generated.canonical_source))
    assert ast.ast_to_dict(folded) == before
    assert all(left is right for left, right in zip(nodes, ast.walk(folded)))


def test_harness_generation_is_deterministic_and_metadata_is_immutable():
    source = "int main(){int x=1;for(int i=0;i<3;i=i+1)x=x+i;return x;}"
    program = parse(source)
    generated = make_harness(program)
    assert generated == make_harness(program) == make_harness(parse(source))
    with pytest.raises(FrozenInstanceError):
        generated.entry_name = "changed"


def test_harness_requires_the_existing_parsed_program_boundary():
    with pytest.raises(TypeError, match="parsed Program"):
        make_harness("int main(){return 0;}")
    with pytest.raises(FrontendError):
        parse(make_harness(parse("int main(){return 0;}")).source)


@pytest.mark.parametrize("body,code", [
    ("return missing;", "UNDECLARED_VARIABLE"),
    ("int x;return x;", "UNINITIALIZED_VARIABLE"),
    ("return 1/0;", "DIVISION_BY_ZERO"),
    ("return 2147483647+1;", "INTEGER_OVERFLOW"),
    ("int x=1;", "MISSING_RETURN"),
])
def test_semantically_invalid_programs_keep_the_established_source_diagnostics(body, code):
    with pytest.raises(SemanticError) as caught:
        make_harness(parse(f"int main(){{{body}}}"))
    assert caught.value.diagnostic.code == code


def test_wrapper_refuses_a_changed_or_untrusted_emitter_header(monkeypatch):
    monkeypatch.setattr(harness, "emit_c", lambda program: "int other(void) { return 0; }\n")
    with pytest.raises(ValueError, match="unexpected main header"):
        make_harness(parse("int main(){return 0;}"))


def test_generated_computation_is_reparsed_before_it_can_enter_the_internal_wrapper(monkeypatch):
    monkeypatch.setattr(harness, "emit_c", lambda program: "int main(void) {\n    return function_call();\n}\n")
    with pytest.raises(FrontendError):
        make_harness(parse("int main(){return 0;}"))


@pytest.mark.parametrize("text,expected", [
    ('{"protocol_version":1,"return_value":0}', 0),
    ('{"protocol_version":1,"return_value":257}\n', 257),
    ('{"protocol_version":1,"return_value":-1}', -1),
    ('{"return_value":-2147483648,"protocol_version":1}', INT_MIN),
    (' \n {"protocol_version":1,"return_value":2147483647} \t', INT_MAX),
])
def test_observation_parser_accepts_exact_versioned_full_signed_integer_records(text, expected):
    assert parse_observation(text) == expected


@pytest.mark.parametrize("text", [
    "", " ", "{", "null", "[]", "1", "true", '"text"',
    '{"protocol_version":1,"return_value":1} trailing',
    '{"protocol_version":1,"return_value":1}\n{"protocol_version":1,"return_value":2}',
    '{"protocol_version":1}', '{"return_value":1}',
    '{"protocol_version":1,"return_value":1,"extra":0}',
    '{"protocol_version":1,"return_value":1,"return_value":257}',
    '{"protocol_version":1,"protocol_version":1,"return_value":1}',
    '{"protocol_version":1,"return_value":1,"\\u0072eturn_value":257}',
    '{"protocol_version":0,"return_value":1}',
    '{"protocol_version":2,"return_value":1}',
    '{"protocol_version":true,"return_value":1}',
    '{"protocol_version":1.0,"return_value":1}',
    '{"protocol_version":"1","return_value":1}',
    '{"protocol_version":null,"return_value":1}',
    '{"protocol_version":1,"return_value":true}',
    '{"protocol_version":1,"return_value":false}',
    '{"protocol_version":1,"return_value":1.0}',
    '{"protocol_version":1,"return_value":1e0}',
    '{"protocol_version":1,"return_value":"257"}',
    '{"protocol_version":1,"return_value":null}',
    '{"protocol_version":1,"return_value":[]}',
    '{"protocol_version":1,"return_value":{}}',
    '{"protocol_version":1,"return_value":NaN}',
    '{"protocol_version":1,"return_value":Infinity}',
    '{"protocol_version":1,"return_value":-Infinity}',
    '{"protocol_version":1,"return_value":2147483648}',
    '{"protocol_version":1,"return_value":-2147483649}',
])
def test_malformed_ambiguous_tampered_or_out_of_range_observations_are_protocol_failures(text):
    with pytest.raises(ObservationError):
        parse_observation(text)


@pytest.mark.parametrize("value", [b'{"protocol_version":1,"return_value":1}', None, 1, {}, []])
def test_observation_parser_requires_text(value):
    with pytest.raises(ObservationError, match="JSON text"):
        parse_observation(value)


def test_observation_size_and_nesting_are_bounded_protocol_errors():
    with pytest.raises(ObservationError, match="size limit"):
        parse_observation(" " * (MAX_OBSERVATION_BYTES + 1))
    with pytest.raises(ObservationError):
        parse_observation("[" * 1500 + "0" + "]" * 1500)


@pytest.fixture(scope="module", params=("O0", "O2"))
def clang_runner(request):
    if shutil.which("clang") is None:
        pytest.skip("Clang executable is unavailable for actual harness integration")
    from runtime.compiler_runner import CompilerRunner
    from runtime.models import CompileConfig

    # Harness/protocol tests are independent of the optional sanitizer backend;
    # sanitizer behavior is tested by the compiler/equivalence integration suite.
    # Give functional observations room for macOS cold executable startup.
    with CompilerRunner(CompileConfig(optimization=request.param, sanitize=False, execution_timeout=10.0)) as runner:
        assert runner.compiler_info.status == "available", runner.compiler_info
        yield runner


@pytest.mark.integration
@pytest.mark.parametrize("body,expected", [
    ("return 0;", 0),
    ("return 257;", 257),
    ("return -257;", -257),
    ("return -2147483647-1;", INT_MIN),
    ("return 2147483647;", INT_MAX),
    ("return (-7/3)*100+(-7%3);", -201),
    ("int main=256;int codedna_entry=1;int codedna_entry_1=2;return main+codedna_entry+codedna_entry_1;", 259),
    ("int EOF=1;int INT_MIN=2;int INT_MAX=3;int CHAR_BIT=4;int stdin=5;int stdout=6;int stderr=7;int FILE=8;int fopen=9;int fprintf=10;return EOF+INT_MIN+INT_MAX+CHAR_BIT+stdin+stdout+stderr+FILE+fopen+fprintf;", 55),
])
def test_actual_clang_harness_captures_full_results_and_preserves_user_names(clang_runner, body, expected):
    generated = make_harness(parse(f"int main(){{{body}}}"))
    compiled = clang_runner.compile_source(generated.source, observation_file=generated.observation_file)
    assert compiled.status == "success", compiled.stderr
    observed = clang_runner.execute(compiled.artifact)
    assert observed.status == "success", observed
    assert observed.process_returncode == 0
    assert observed.return_value == expected
    assert observed.stdout == observed.stderr == ""

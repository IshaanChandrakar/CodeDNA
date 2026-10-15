"""File → tokens → AST/JSON and CLI integration, including expected failures."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from compiler.ast_nodes import ast_to_json, walk
from compiler.diagnostics import FrontendError
from compiler.lexer import tokenize
from compiler.parser import parse


ROOT = Path(__file__).resolve().parents[1]
VALID_EXAMPLES = sorted((ROOT / "examples" / "basic").glob("*.c")) + sorted((ROOT / "examples" / "loops").glob("*.c"))
INVALID_EXAMPLES = sorted((ROOT / "examples" / "invalid").glob("*.c"))


def run_cli(*arguments, cwd=ROOT):
    return subprocess.run(
        [sys.executable, "-m", "compiler", *map(str, arguments)],
        cwd=cwd, capture_output=True, text=True, timeout=15,
    )


@pytest.mark.parametrize("path", VALID_EXAMPLES, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_all_valid_example_files_generate_tokens_and_actual_ast_json(path):
    source = path.read_text(encoding="utf-8")
    records = tokenize(source)
    program = parse(source)
    data = json.loads(ast_to_json(program))
    assert records[0].type == "INT"
    assert data["function"]["name"] == "main"
    assert len(tuple(walk(program))) > 3
    assert data["span"]["end_offset"] == source.rindex("}") + 1


@pytest.mark.parametrize("path", INVALID_EXAMPLES, ids=lambda path: path.name)
def test_all_invalid_example_files_produce_structured_errors(path):
    with pytest.raises(FrontendError) as caught:
        parse(path.read_text(encoding="utf-8"))
    assert caught.value.diagnostic.span.start_line >= 1
    assert caught.value.diagnostic.span.start_column >= 1


def test_cli_token_stream_comes_from_real_file():
    result = run_cli("--tokens", "examples/basic/minimal.c")
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout.splitlines() == [
        "1:1 INT 'int'", "1:5 ID 'main'", "1:9 LPAREN '('", "1:10 RPAREN ')'",
        "1:12 LBRACE '{'", "1:14 RETURN 'return'", "1:21 INTEGER 0",
        "1:22 SEMICOLON ';'", "1:24 RBRACE '}'",
    ]


@pytest.mark.parametrize("path", VALID_EXAMPLES, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_cli_ast_matches_library_output_for_each_example(path):
    result = run_cli("--ast", path)
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout == ast_to_json(parse(path.read_text(encoding="utf-8"))) + "\n"


@pytest.mark.parametrize("path", INVALID_EXAMPLES, ids=lambda path: path.name)
def test_cli_reports_each_invalid_example_without_traceback(path):
    result = run_cli("--ast", path)
    assert result.returncode == 1 and result.stdout == ""
    assert str(path) in result.stderr
    assert "error [" in result.stderr
    assert "Traceback" not in result.stderr


def test_token_mode_is_lexical_only():
    result = run_cli("--tokens", "examples/invalid/missing_semicolon.c")
    assert result.returncode == 0 and result.stderr == ""
    assert "RETURN 'return'" in result.stdout


def test_cli_lexical_failure_prints_no_partial_token_stream():
    result = run_cli("--tokens", "examples/invalid/invalid_token.c")
    assert result.returncode == 1 and result.stdout == ""
    assert ":2:14: lexer error [ILLEGAL_CHARACTER]" in result.stderr


def test_cli_file_error(tmp_path):
    result = run_cli("--ast", tmp_path / "missing.c")
    assert result.returncode == 2 and result.stdout == ""
    assert "file error" in result.stderr and "Traceback" not in result.stderr


def test_cli_invalid_encoding(tmp_path):
    path = tmp_path / "invalid-encoding.c"
    path.write_bytes(b"\xff")
    result = run_cli("--ast", path)
    assert result.returncode == 2 and "file error" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_preserves_crlf_offsets(tmp_path):
    path = tmp_path / "crlf.c"
    source = "int main() {\r\n  return 0;\r\n}\r\n"
    path.write_bytes(source.encode("utf-8"))
    result = run_cli("--ast", path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == json.loads(ast_to_json(parse(source)))


def test_cli_works_from_outside_checkout_with_editable_install(tmp_path):
    result = run_cli("--ast", ROOT / "examples" / "basic" / "minimal.c", cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout)["function"]["body"]["items"][0]["value"]["value"] == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("arguments", [(), ("--ast",), ("examples/basic/minimal.c",), ("--tokens", "--ast", "examples/basic/minimal.c")])
def test_cli_argument_errors_have_exit_code_two(arguments):
    result = run_cli(*arguments)
    assert result.returncode == 2
    assert "usage:" in result.stderr and "Traceback" not in result.stderr


def test_cli_empty_source_distinguishes_tokenization_from_parsing(tmp_path):
    path = tmp_path / "empty.c"
    path.write_text("", encoding="utf-8")
    lexical = run_cli("--tokens", path)
    syntax = run_cli("--ast", path)
    assert lexical.returncode == 0 and lexical.stdout == ""
    assert syntax.returncode == 1 and syntax.stdout == ""
    assert ":1:1: parser error [UNEXPECTED_EOF]" in syntax.stderr

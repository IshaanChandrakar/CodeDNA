"""Transformation CLI reports, emitted subset C, inspectable TAC/CFG and errors."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from compiler import ast_nodes as ast
from compiler.cfg import build_cfg
from compiler.ir import lower_ir
from compiler.parser import parse
from compiler.semantic import analyze


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "transformations"


def cli(*arguments, cwd=ROOT):
    return subprocess.run(
        [sys.executable, "-m", "compiler", *map(str, arguments)], cwd=cwd,
        capture_output=True, text=True, timeout=20,
    )


def test_actual_constant_report_and_tac():
    report = cli("--transform", "constants", "--report", EXAMPLES / "constants.c")
    assert report.returncode == 0 and report.stderr == ""
    data = json.loads(report.stdout)
    assert data["sequence"] == ["constants"]
    result = data["reports"][0]
    assert result["status"] == "applied"
    assert result["statistics"]["expressions_folded"] == 4
    assert result["statistics"]["references_propagated"] == 2
    tac = cli("--transform", "constants", "--tac", EXAMPLES / "constants.c")
    assert tac.returncode == 0 and tac.stderr == ""
    assert tac.stdout == "base = 14\nadjusted = 10\nreturn 3\n"


def test_transform_without_an_inspection_mode_defaults_to_reports():
    implicit = cli("--transform", "constants", EXAMPLES / "constants.c")
    explicit = cli("--transform", "constants", "--report", EXAMPLES / "constants.c")
    assert implicit.returncode == explicit.returncode == 0
    assert implicit.stdout == explicit.stdout


@pytest.mark.parametrize("name,count,expected", [
    ("unroll_positive.c", 4, 64), ("unroll_negative.c", 3, 89), ("combined.c", 4, 146),
])
def test_ordered_combined_passes_produce_hand_derived_return_values(name, count, expected):
    flags = ("--transform", "constants", "--transform", "unroll", "--transform", "constants")
    report = cli(*flags, "--report", EXAMPLES / name)
    assert report.returncode == 0 and report.stderr == ""
    data = json.loads(report.stdout)
    assert data["sequence"] == ["constants", "unroll", "constants"]
    assert data["reports"][1]["statistics"]["loops_unrolled"] == 1
    assert data["reports"][1]["statistics"]["iterations_expanded"] == count
    tree = cli(*flags, "--ast", EXAMPLES / name)
    assert tree.returncode == 0 and tree.stderr == ""
    final_return = json.loads(tree.stdout)["function"]["body"]["items"][-1]
    assert final_return["kind"] == "Return"
    assert final_return["value"]["kind"] == "IntegerLiteral"
    assert final_return["value"]["value"] == expected


@pytest.mark.parametrize("name,code", [
    ("rejected_induction.c", "INDUCTION_WRITE"),
    ("rejected_declaration.c", "DECLARATION_IN_BODY"),
    ("rejected_limit.c", "ITERATION_LIMIT"),
])
def test_rejected_reports_are_successful_inspections_without_fake_applied_counts(name, code):
    result = cli("--transform", "unroll", "--report", EXAMPLES / name)
    assert result.returncode == 0 and result.stderr == ""
    report = json.loads(result.stdout)["reports"][0]
    assert report["status"] == "rejected"
    assert report["statistics"]["loops_unrolled"] == 0
    decision = next(item for item in report["decisions"] if item["code"] == code)
    assert decision["span"]["start_line"] == 3
    original = cli("--tac", EXAMPLES / name)
    preserved = cli("--transform", "unroll", "--tac", EXAMPLES / name)
    assert original.returncode == preserved.returncode == 0
    assert preserved.stdout == original.stdout
    assert f"rejected [{code}]" in preserved.stderr


def test_maximum_unroll_option_changes_the_actual_applicability():
    limited = cli("--transform", "unroll", "--max-unroll", "2", "--report", EXAMPLES / "unroll_positive.c")
    allowed = cli("--transform", "unroll", "--max-unroll", "4", "--report", EXAMPLES / "unroll_positive.c")
    assert limited.returncode == allowed.returncode == 0
    assert json.loads(limited.stdout)["reports"][0]["status"] == "rejected"
    assert json.loads(allowed.stdout)["reports"][0]["status"] == "applied"
    assert json.loads(allowed.stdout)["reports"][0]["parameters"]["max_iterations"] == 4


def test_no_op_reports_are_distinct_from_rejected_passes():
    result = cli("--transform", "unroll", "examples/basic/minimal.c")
    assert result.returncode == 0 and result.stderr == ""
    report = json.loads(result.stdout)["reports"][0]
    assert report["status"] == "not_applicable"
    assert report["statistics"]["loops_unrolled"] == 0
    assert report["decisions"][0]["status"] == "not_applicable"


def test_repeated_constant_pass_reports_a_stable_second_result():
    result = cli("--transform", "constants", "--transform", "constants", EXAMPLES / "constants.c")
    assert result.returncode == 0
    reports = json.loads(result.stdout)["reports"]
    assert [report["status"] for report in reports] == ["applied", "not_applicable"]
    assert reports[1]["statistics"]["expressions_folded"] == 0
    assert reports[1]["statistics"]["references_propagated"] == 0


@pytest.mark.parametrize("flags", [(), ("--transform", "constants"),
    ("--transform", "constants", "--transform", "unroll", "--transform", "constants")])
def test_source_emission_round_trips_without_compilation(flags):
    result = cli(*flags, "--c", EXAMPLES / "combined.c")
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout.startswith("int main(void) {\n")
    program = parse(result.stdout)
    analyze(program)
    build_cfg(lower_ir(program))
    if "unroll" in flags:
        assert not any(isinstance(node, ast.For) for node in ast.walk(program))


@pytest.mark.parametrize("mode", ["--cfg", "--cfg-dot", "--ast-dot", "--check"])
def test_transformed_analysis_and_graph_modes_use_actual_transformed_syntax(mode):
    result = cli("--transform", "unroll", mode, EXAMPLES / "unroll_positive.c")
    assert result.returncode == 0 and result.stderr == ""
    if mode == "--cfg":
        assert "B0:" in result.stdout and "B1:" not in result.stdout
        assert "goto" not in result.stdout
    elif mode == "--cfg-dot":
        assert result.stdout.startswith("digraph CFG") and "goto" not in result.stdout
    elif mode == "--ast-dot":
        assert result.stdout.startswith("digraph AST") and 'label="For' not in result.stdout
    else:
        assert result.stdout == "Semantic analysis passed.\n"


@pytest.mark.parametrize("flags", [
    ("--report",),
    ("--transform", "unknown", "--tac"),
    ("--transform", "constants", "--tokens"),
    ("--transform", "unroll", "--max-unroll", "-1"),
    ("--transform", "unroll", "--max-unroll", "1025"),
    ("--transform", "unroll", "--max-unroll", "not-a-number"),
    ("--transform", "constants", "--max-unroll", "4"),
    ("--tac", "--max-unroll", "4"),
    ("--c", "--format", "svg"),
    ("--transform", "constants", "--tac", "--report"),
])
def test_invalid_transformation_options_are_argument_errors(flags):
    result = cli(*flags, EXAMPLES / "constants.c")
    assert result.returncode == 2
    assert "usage:" in result.stderr and "Traceback" not in result.stderr


def test_transformation_input_errors_keep_existing_exit_conventions(tmp_path):
    path = tmp_path / "source.c"
    for source, code in (("int main(){return @;}", "ILLEGAL_CHARACTER"),
                         ("int main(){return missing;}", "UNDECLARED_VARIABLE")):
        path.write_text(source)
        result = cli("--transform", "constants", "--report", path)
        assert result.returncode == 1 and result.stdout == ""
        assert f"[{code}]" in result.stderr and "Traceback" not in result.stderr
    missing = cli("--transform", "unroll", tmp_path / "missing.c")
    assert missing.returncode == 2 and missing.stdout == ""
    assert "file error" in missing.stderr


def test_revalidation_rejection_is_reported_without_exposing_invalid_candidate(tmp_path):
    path = tmp_path / "revealed-zero.c"
    path.write_text("int main(){int x=0;for(int i=0;i<2;i=i+1)x=1/i;return x;}")
    result = cli("--transform", "unroll", "--report", path)
    assert result.returncode == 0 and result.stderr == ""
    report = json.loads(result.stdout)["reports"][0]
    assert report["status"] == "rejected"
    assert report["decisions"][-1]["code"] == "REVALIDATION_FAILED"
    assert report["statistics"]["loops_unrolled"] == 0
    tree = cli("--transform", "unroll", "--ast", path)
    assert tree.returncode == 0
    assert json.loads(tree.stdout)["function"]["body"]["items"][1]["kind"] == "For"


def test_saved_transformation_report_and_source_are_deterministic_outside_checkout(tmp_path):
    output = tmp_path / "reports" / "constants.json"
    source = EXAMPLES / "constants.c"
    result = cli("--transform", "constants", "--report", "--output", output, source, cwd=tmp_path)
    assert result.returncode == 0 and result.stderr == ""
    assert json.loads(output.read_text())["reports"][0]["status"] == "applied"
    assert output.read_text() == cli("--transform", "constants", "--report", source).stdout
    emitted = tmp_path / "transformed.c"
    result = cli("--transform", "constants", "--c", "--output", emitted, source, cwd=tmp_path)
    assert result.returncode == 0
    assert "return (3);" in emitted.read_text()
    analyze(parse(emitted.read_text()))


def test_emitted_c_cannot_overwrite_its_original_source(tmp_path):
    source = tmp_path / "source.c"
    original = (EXAMPLES / "constants.c").read_text()
    source.write_text(original)
    result = cli("--transform", "constants", "--c", "--output", source, source)
    assert result.returncode == 2 and "overwrite" in result.stderr
    assert source.read_text() == original


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.c")), ids=lambda path: path.name)
def test_all_new_examples_follow_the_existing_grammar_and_analysis(path):
    program = parse(path.read_text())
    assert analyze(program).diagnostics == ()
    build_cfg(lower_ir(program))

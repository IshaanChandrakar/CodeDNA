"""Real runtime CLI observations, failure statuses, option errors and file safety."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "runtime"
CLANG = shutil.which("clang")
requires_clang = pytest.mark.skipif(CLANG is None, reason="Runtime CLI integration requires the Clang executable")


def cli(*arguments, cwd=ROOT):
    return subprocess.run(
        [sys.executable, "-m", "compiler", *map(str, arguments)],
        cwd=cwd, capture_output=True, text=True, timeout=45,
    )


def report_from(result, expected_exit=0):
    assert result.returncode == expected_exit, result.stderr or result.stdout
    assert "Traceback" not in result.stderr
    data = json.loads(result.stdout)
    assert data["schema_version"] == 1
    assert set(data) == {"schema_version", "result", "environment_metadata"}
    assert "outcome" in data["result"]
    return data


def write_source(tmp_path, body, name="program.c"):
    path = tmp_path / name
    path.write_text(f"int main(void){{{body}}}\n", encoding="utf-8")
    return path


@pytest.mark.integration
@requires_clang
def test_compile_reports_actual_clang_success_without_executing_or_retaining_a_binary():
    completed = cli("--compile", EXAMPLES / "constants_return257.c")
    data = report_from(completed)
    result = data["result"]
    assert result["outcome"] == "compiled"
    assert result["original"]["compilation"]["status"] == "success"
    assert result["original"]["execution"] is None
    assert "clang" in data["environment_metadata"]["compiler"]["version"].lower()
    assert "-std=c11" in result["settings"]["flags"]
    assert "-O0" in result["settings"]["flags"]
    assert not Path(data["environment_metadata"]["workspace"]).exists()
    assert completed.stderr == ""


@pytest.mark.integration
@requires_clang
@pytest.mark.parametrize("optimization", ["O0", "O2"])
@pytest.mark.parametrize("body,expected", [
    ("return 0;", 0), ("return 257;", 257), ("return -257;", -257),
    ("return -2147483647-1;", -2147483648), ("return 2147483647;", 2147483647),
])
def test_run_displays_full_signed_return_separately_from_wrapper_process_status(tmp_path, optimization, body, expected):
    source = write_source(tmp_path, body)
    data = report_from(cli("--run", "--execution-timeout", "10", "--opt", optimization, source))
    assert data["result"]["outcome"] == "executed"
    observed = data["result"]["original"]["execution"]
    assert observed["status"] == "success"
    assert observed["return_value"] == expected
    assert observed["process_returncode"] == 0
    assert observed["stdout"] == observed["stderr"] == ""
    assert data["result"]["settings"]["optimization"] == optimization


@pytest.mark.integration
@requires_clang
def test_equivalence_defaults_to_constants_and_reports_real_observed_values():
    data = report_from(cli("--equiv", "--execution-timeout", "10", EXAMPLES / "constants_return257.c"))
    result = data["result"]
    assert result["outcome"] == "observed_equivalent"
    assert result["sequence"] == ["constants"]
    assert result["accepted_transformation"] is True
    assert result["transformation_reports"][0]["status"] == "applied"
    assert result["original"]["execution"]["return_value"] == 257
    assert result["transformed"]["execution"]["return_value"] == 257
    assert "not a formal proof" in result["explanation"].lower()


@pytest.mark.integration
@requires_clang
def test_runtime_keeps_explicit_transformation_order_and_configured_unroll_limit():
    flags = ("--transform", "constants", "--transform", "unroll", "--transform", "constants")
    data = report_from(cli("--equiv", "--execution-timeout", "10", *flags, "--max-unroll", "4", "--opt", "O2",
                           ROOT / "examples" / "transformations" / "combined.c"))
    result = data["result"]
    assert result["outcome"] == "observed_equivalent"
    assert result["sequence"] == ["constants", "unroll", "constants"]
    assert [item["status"] for item in result["transformation_reports"]] == ["applied"] * 3
    assert result["transformation_reports"][1]["parameters"]["max_iterations"] == 4
    assert result["original"]["execution"]["return_value"] == 146
    assert result["transformed"]["execution"]["return_value"] == 146


@pytest.mark.integration
@requires_clang
def test_against_detects_one_versus_257_instead_of_comparing_low_byte_exit_codes():
    data = report_from(cli("--equiv", "--execution-timeout", "10", "--against", EXAMPLES / "mismatch_257.c",
                           EXAMPLES / "mismatch_one.c"), expected_exit=5)
    result = data["result"]
    assert result["outcome"] == "different_behavior"
    assert result["comparison_kind"] == "independent_sources"
    assert result["sequence"] == []
    assert result["original"]["execution"]["return_value"] == 1
    assert result["transformed"]["execution"]["return_value"] == 257
    assert result["original"]["execution"]["process_returncode"] == 0
    assert result["transformed"]["execution"]["process_returncode"] == 0


@pytest.mark.integration
@requires_clang
def test_no_applied_transformation_is_not_reported_as_validated_optimization():
    data = report_from(cli("--equiv", "--execution-timeout", "10", "--transform", "unroll", "examples/basic/minimal.c"), expected_exit=6)
    result = data["result"]
    assert result["outcome"] == "no_transformation"
    assert result["accepted_transformation"] is False
    assert result["transformation_reports"][0]["status"] == "not_applicable"
    assert result["original"]["execution"]["return_value"] == 0
    assert result["transformed"]["execution"]["return_value"] == 0


@pytest.mark.integration
@requires_clang
def test_rejected_unrolling_remains_explicit_without_claiming_optimization_equivalence():
    source = ROOT / "examples" / "transformations" / "rejected_induction.c"
    data = report_from(cli("--equiv", "--execution-timeout", "10", "--transform", "unroll", source), expected_exit=6)
    result = data["result"]
    assert result["outcome"] == "no_transformation"
    assert result["accepted_transformation"] is False
    report = result["transformation_reports"][0]
    assert report["status"] == "rejected"
    assert any(item["code"] == "INDUCTION_WRITE" for item in report["decisions"])


@pytest.mark.integration
@requires_clang
def test_nontermination_reports_timeout_without_a_return_observation():
    data = report_from(cli("--run", "--execution-timeout", "0.1", EXAMPLES / "timeout.c"), expected_exit=4)
    result = data["result"]
    assert result["outcome"] == "timeout"
    assert result["original"]["execution"]["status"] == "timeout"
    assert result["original"]["execution"]["return_value"] is None


@pytest.mark.integration
@requires_clang
def test_dynamic_undefined_arithmetic_reports_ubsan_failure_instead_of_a_value():
    data = report_from(cli("--run", "--execution-timeout", "10", "--sanitize", EXAMPLES / "dynamic_divzero.c"), expected_exit=4)
    result = data["result"]
    assert result["outcome"] == "undefined_behavior"
    execution = result["original"]["execution"]
    assert execution["status"] == "undefined_behavior" and execution["return_value"] is None
    assert "runtime error" in execution["stderr"].lower()


@pytest.mark.integration
@requires_clang
def test_no_sanitize_is_explicitly_recorded_for_execution_only():
    data = report_from(cli("--run", "--execution-timeout", "10", "--no-sanitize", EXAMPLES / "negative_math.c"))
    assert data["result"]["outcome"] == "executed"
    assert data["result"]["settings"]["sanitizer_requested"] is False
    assert "-fsanitize=undefined" not in data["result"]["settings"]["flags"]
    assert data["result"]["original"]["execution"]["return_value"] == -201


@pytest.mark.integration
@requires_clang
def test_saved_mismatch_report_retains_mismatch_exit_status_and_preserves_inputs(tmp_path):
    original = write_source(tmp_path, "return 1;", "original.c")
    other = write_source(tmp_path, "return 257;", "other.c")
    output = tmp_path / "reports" / "comparison.json"
    before = (original.read_bytes(), other.read_bytes())
    completed = cli("--equiv", "--execution-timeout", "10", "--against", other, "--output", output, original, cwd=tmp_path)
    assert completed.returncode == 5 and completed.stderr == ""
    assert completed.stdout == f"Saved {output}\n"
    assert json.loads(output.read_text())["result"]["outcome"] == "different_behavior"
    assert (original.read_bytes(), other.read_bytes()) == before


def test_missing_compiler_is_unavailable_and_can_save_the_failure_report(tmp_path):
    source = write_source(tmp_path, "return 257;")
    output = tmp_path / "unavailable.json"
    completed = cli("--run", "--clang", tmp_path / "missing clang; unused", "--output", output, source)
    assert completed.returncode == 6 and completed.stderr == ""
    assert completed.stdout == f"Saved {output}\n"
    data = json.loads(output.read_text())
    assert data["result"]["outcome"] == "unavailable"
    assert data["result"]["original"]["execution"] is None


def fake_compiler(tmp_path, *, delay=False):
    path = tmp_path / "clang with spaces; harmless"
    action = "import time; time.sleep(5)" if delay else "print('intentional compiler fixture diagnostic', file=sys.stderr); sys.exit(1)"
    path.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "if '--version' in sys.argv:\n    print('clang version 99.0 (test fixture)')\n"
        f"else:\n    {action}\n", encoding="utf-8",
    )
    path.chmod(0o700)
    return path


@pytest.mark.skipif(os.name != "posix", reason="Executable Python fixture uses POSIX shebang semantics")
def test_compiler_failure_preserves_actual_diagnostics_and_uses_exit_three(tmp_path):
    compiler = fake_compiler(tmp_path)
    data = report_from(cli("--compile", "--clang", compiler, "examples/basic/minimal.c"), expected_exit=3)
    assert data["result"]["outcome"] == "compilation_failure"
    assert "intentional compiler fixture diagnostic" in data["result"]["original"]["compilation"]["stderr"]
    assert data["result"]["original"]["execution"] is None


@pytest.mark.skipif(os.name != "posix", reason="Executable Python fixture uses POSIX shebang semantics")
def test_compilation_timeout_is_distinct_from_compiler_diagnostic_failure(tmp_path):
    compiler = fake_compiler(tmp_path, delay=True)
    data = report_from(cli("--compile", "--clang", compiler, "--compile-timeout", "0.2",
                           "examples/basic/minimal.c"), expected_exit=4)
    assert data["result"]["outcome"] == "timeout"
    assert data["result"]["original"]["compilation"]["status"] == "timeout"
    assert data["result"]["original"]["execution"] is None


@pytest.mark.parametrize("flags", [
    ("--run", "--compile"), ("--run", "--tac"),
    ("--run", "--against", "unused.c"),
    ("--equiv", "--against", "unused.c", "--transform", "constants"),
    ("--equiv", "--max-unroll", "2"),
    ("--run", "--format", "dot"), ("--run", "--opt", "O1"),
    ("--run", "--clang", ""),
    ("--run", "--compile-timeout", "0"), ("--run", "--compile-timeout", "-1"),
    ("--run", "--execution-timeout", "0"), ("--run", "--execution-timeout", "nan"),
    ("--run", "--execution-timeout", "inf"), ("--run", "--execution-timeout", "words"),
    ("--tac", "--clang", "clang"), ("--ast", "--opt", "O2"),
    ("--c", "--compile-timeout", "1"), ("--check", "--execution-timeout", "1"),
    ("--tokens", "--sanitize"), ("--ast", "--no-sanitize"),
    ("--transform", "constants", "--clang", "clang"),
])
def test_invalid_runtime_options_preserve_argument_error_conventions(flags):
    completed = cli(*flags, "examples/basic/minimal.c")
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "usage:" in completed.stderr and "Traceback" not in completed.stderr


@pytest.mark.parametrize("source_text,code", [
    ("int main(){return @;}", "ILLEGAL_CHARACTER"),
    ("int main(){return missing;}", "UNDECLARED_VARIABLE"),
    ("int main(){int x;return x;}", "UNINITIALIZED_VARIABLE"),
])
def test_runtime_source_errors_leave_existing_report_untouched(tmp_path, source_text, code):
    source = tmp_path / "invalid.c"
    source.write_text(source_text)
    output = tmp_path / "existing.json"
    output.write_text("retain existing report")
    completed = cli("--run", "--output", output, source)
    assert completed.returncode == 1 and completed.stdout == ""
    assert str(source) in completed.stderr and f"[{code}]" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert output.read_text() == "retain existing report"


def test_against_semantic_errors_are_attributed_to_the_second_source(tmp_path):
    source = write_source(tmp_path, "return 1;", "original.c")
    other = tmp_path / "invalid-other.c"
    other.write_text("int main(){return missing;}")
    completed = cli("--equiv", "--against", other, source)
    assert completed.returncode == 1 and completed.stdout == ""
    assert f"{other}:1:" in completed.stderr
    assert "UNDECLARED_VARIABLE" in completed.stderr and "Traceback" not in completed.stderr


def test_against_encoding_errors_are_attributed_to_the_second_source(tmp_path):
    source = write_source(tmp_path, "return 1;", "original.c")
    other = tmp_path / "invalid-encoding.c"
    other.write_bytes(b"\xff")
    completed = cli("--equiv", "--against", other, source)
    assert completed.returncode == 2 and completed.stdout == ""
    assert str(other) in completed.stderr and "file error" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_runtime_missing_input_is_file_error_with_no_partial_json(tmp_path):
    completed = cli("--run", tmp_path / "missing.c")
    assert completed.returncode == 2 and completed.stdout == ""
    assert "file error" in completed.stderr and "Traceback" not in completed.stderr


@pytest.mark.parametrize("which", ["original", "against"])
@pytest.mark.parametrize("alias", ["direct", "hardlink", "symlink"])
def test_runtime_report_output_cannot_overwrite_either_source_through_aliases(tmp_path, which, alias):
    source = write_source(tmp_path, "return 1;", "original.c")
    other = write_source(tmp_path, "return 257;", "other.c")
    protected = source if which == "original" else other
    output = protected if alias == "direct" else tmp_path / "output-alias.json"
    if alias == "hardlink":
        output.hardlink_to(protected)
    elif alias == "symlink":
        output.symlink_to(protected)
    before = (source.read_bytes(), other.read_bytes())
    completed = cli("--equiv", "--against", other, "--output", output, source)
    assert completed.returncode == 2 and completed.stdout == ""
    assert "overwrite" in completed.stderr and "Traceback" not in completed.stderr
    assert (source.read_bytes(), other.read_bytes()) == before

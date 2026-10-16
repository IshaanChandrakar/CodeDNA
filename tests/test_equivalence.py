"""Real Clang comparisons: complete int observations, mismatches and unsafe runs."""

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from compiler import ast_nodes as ast
from compiler.codegen import emit_c
from compiler.diagnostics import FrontendError
from compiler.parser import parse
from compiler.semantic import analyze
from runtime.equivalence import check_equivalence, compare_sources
from runtime.models import CompileConfig


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "runtime"
CLANG = shutil.which("clang")
requires_clang = pytest.mark.skipif(CLANG is None, reason="Real Clang compilation/execution requires the clang executable")


def source(body):
    return f"int main(void){{{body}}}"


def fixture(name):
    return (EXAMPLES / name).read_text(encoding="utf-8")


def config(optimization="O0", **changes):
    return CompileConfig(compiler=CLANG or "clang", optimization=optimization, **changes)


def assert_observed(report, expected):
    assert report.outcome == "observed_equivalent", report.explanation
    assert report.original.execution is not None
    assert report.transformed.execution is not None
    assert report.original.execution.return_value == expected
    assert report.transformed.execution.return_value == expected
    assert report.original.execution.status == report.transformed.execution.status == "success"
    assert report.original.execution.process_returncode == report.transformed.execution.process_returncode == 0
    assert report.original.execution.stdout == report.transformed.execution.stdout == ""
    assert report.original.execution.stderr == report.transformed.execution.stderr == ""
    assert report.original.compilation is not None
    assert report.transformed.compilation is not None


@requires_clang
@pytest.mark.parametrize("optimization", ["O0", "O2"])
@pytest.mark.parametrize("body,expected", [
    ("return 0+0;", 0),
    ("return 8+9;", 17),
    ("return -8-9;", -17),
    ("return 256+1;", 257),
    ("return 2147483646+1;", 2147483647),
    ("return -2147483647-1;", -2147483648),
])
def test_exact_full_signed_int_results_after_constants_at_each_optimization(optimization, body, expected):
    report = check_equivalence(source(body), ("constants",), config=config(optimization))
    assert_observed(report, expected)
    assert report.sequence == ("constants",)
    assert any(item.status == "applied" for item in report.transformation_reports)
    for variant in (report.original, report.transformed):
        assert f"-{optimization}" in variant.compilation.command
        assert "-std=c11" in variant.compilation.command
        assert "-fsanitize=undefined" in variant.compilation.command
    assert report.original.compilation.command != report.transformed.compilation.command


@requires_clang
@pytest.mark.parametrize("optimization", ["O0", "O2"])
@pytest.mark.parametrize("body,sequence,expected", [
    ("int x=2+3*4;int y=x-4;return y/3;", ("constants",), 3),
    ("int sum=0;int i;for(i=0;i<4;i=i+1)sum=sum+i;return sum*10+i;", ("unroll",), 64),
    ("int sum=0;int i;for(i=4;i>0;i=i-1)sum=sum+i;return sum*10+i;", ("unroll",), 100),
    ("int sum=0;int i;for(i=-3;i<2;i=i+2)sum=sum+i;return sum*10+i;", ("unroll",), -27),
    ("int total=7;int i=99;for(i=5;i<3;i=i+1)total=total+100;return total+i;", ("unroll",), 12),
    ("int start=2;int sum=0;int i;for(i=start;i<start+4;i=i+1)sum=sum+i;return sum*10+i;", ("constants", "unroll", "constants"), 146),
    ("int x=2+3;if(x>4)return x*100;else return 0;", ("constants",), 500),
    ("int x=3;if(x){if(x>2)return 256;else return 1;}else return -1;", ("constants",), 256),
    ("int q=-7/3;int r=-7%3;return q*100+r;", ("constants",), -201),
])
def test_real_transformation_comparisons_cover_control_flow_and_c_arithmetic(optimization, body, sequence, expected):
    report = check_equivalence(source(body), sequence, config=config(optimization))
    assert_observed(report, expected)
    assert tuple(report.sequence) == sequence
    assert len(report.transformation_reports) == len(sequence)
    assert report.original.canonical_source == emit_c(parse(source(body)))


@requires_clang
@pytest.mark.parametrize("optimization", ["O0", "O2"])
@pytest.mark.parametrize("left,right,expected_left,expected_right", [
    ("return 1;", "return 257;", 1, 257),
    ("return 0;", "return 256;", 0, 256),
    ("return -1;", "return 255;", -1, 255),
    ("return -2147483647-1;", "return 2147483647;", -2147483648, 2147483647),
])
def test_deliberate_negative_controls_detect_full_value_mismatches(optimization, left, right, expected_left, expected_right):
    report = compare_sources(source(left), source(right), config=config(optimization))
    assert report.outcome == "different_behavior", report.explanation
    assert report.original.execution.return_value == expected_left
    assert report.transformed.execution.return_value == expected_right
    assert report.original.execution.return_value != report.transformed.execution.return_value


@requires_clang
def test_genuine_mismatch_example_pair_is_not_hidden_by_equal_low_bytes():
    report = compare_sources(
        fixture("mismatch_one.c"), fixture("mismatch_257.c"), config=config(),
        original_name="mismatch_one.c", transformed_name="mismatch_257.c",
    )
    assert report.outcome == "different_behavior"
    assert report.original.execution.return_value == 1
    assert report.transformed.execution.return_value == 257
    assert 1 % 256 == 257 % 256


@requires_clang
@pytest.mark.parametrize("body,sequence", [
    ("return 257;", ("constants",)),
    ("return 257;", ()),
    ("int x=0;for(int i=0;i<2;i=i+1){int y=i;x=x+y;}return x;", ("unroll",)),
])
def test_unchanged_or_rejected_passes_are_not_evidence_of_accepted_optimization(body, sequence):
    report = check_equivalence(source(body), sequence, config=config())
    assert report.outcome == "no_transformation", report.explanation
    assert not any(item.status == "applied" for item in report.transformation_reports)
    assert report.outcome != "observed_equivalent"


@requires_clang
def test_unsafe_original_retains_undefined_behavior_outcome_after_a_rejected_pass():
    body = "int x=0;for(int i=0;i<2;i=i+1)x=1/i;return x;"
    report = check_equivalence(source(body), ("unroll",), config=config())
    assert report.outcome == "undefined_behavior", report.explanation
    assert not any(item.status == "applied" for item in report.transformation_reports)
    assert report.transformation_reports[0].status == "rejected"
    assert report.transformation_reports[0].statistics.changed_nodes == 0


@requires_clang
def test_later_accepted_passes_retain_earlier_rejection_without_claiming_its_success():
    body = "int start=2;int sum=0;int i;for(i=start;i<start+4;i=i+1)sum=sum+i;return sum*10+i;"
    sequence = ("unroll", "constants", "unroll", "constants")
    report = check_equivalence(source(body), sequence, config=config())
    assert_observed(report, 146)
    assert [item.status for item in report.transformation_reports] == ["rejected", "applied", "applied", "applied"]
    assert report.transformation_reports[0].statistics.loops_unrolled == 0


@requires_clang
@pytest.mark.parametrize("optimization", ["O0", "O2"])
@pytest.mark.parametrize("body", [
    "int numerator=5+5;int d=1;for(int i=0;i<1;i=i+1)d=d-1;return numerator/d;",
    "int numerator=5+5;int d=1;for(int i=0;i<1;i=i+1)d=d-1;return numerator%d;",
    "int x=2147483647;for(int i=0;i<1;i=i+1)x=x+1;return x+(2-2);",
    "int x=-2147483647-1;for(int i=0;i<1;i=i+1)x=x-1;return x+(2-2);",
    "int x=2147483647;for(int i=0;i<1;i=i+1)x=x*2;return x+(2-2);",
    "int x=-2147483647-1;for(int i=0;i<1;i=i+1)x=x+0;return x/-1;",
    "int x=-2147483647-1;for(int i=0;i<1;i=i+1)x=x+0;return x%-1;",
])
def test_matching_undefined_arithmetic_never_becomes_observed_equivalence(optimization, body):
    # Loop-carried writes deliberately make these faults unknown to the static
    # checker. The real instrumented executions, rather than mocks, detect them.
    analyze(parse(source(body)))
    report = check_equivalence(source(body), ("constants",), config=config(optimization))
    assert report.outcome == "undefined_behavior", report.explanation
    assert report.outcome != "observed_equivalent"
    observations = [item.execution for item in (report.original, report.transformed) if item.execution is not None]
    assert observations
    assert any("runtime error" in item.stderr.lower() for item in observations)


@requires_clang
def test_disabled_sanitizer_does_not_claim_safe_observed_equivalence():
    report = check_equivalence(source("return 2+3;"), ("constants",), config=config(sanitize=False))
    assert report.outcome == "inconclusive", report.explanation
    assert report.outcome != "observed_equivalent"


@requires_clang
def test_matching_dynamic_undefined_arithmetic_without_sanitizer_remains_unvalidated():
    unsafe = source("int x=2147483647;for(int i=0;i<1;i=i+1)x=x+1;return x;")
    analyze(parse(unsafe))
    report = compare_sources(unsafe, unsafe, config=config(sanitize=False))
    assert report.outcome in ("inconclusive", "execution_failure"), report.explanation
    assert report.outcome != "observed_equivalent"


@requires_clang
def test_nonterminating_runtime_fixture_times_out_without_an_equivalence_result():
    # The deadline includes process and sanitizer startup, as well as user code.
    report = check_equivalence(fixture("timeout.c"), ("constants",), config=config(execution_timeout=3.0))
    assert report.outcome == "timeout", report.explanation
    assert report.outcome != "observed_equivalent"
    assert report.original.execution.return_value is None


@requires_clang
def test_a_terminating_program_and_a_timeout_are_never_classified_as_a_value_mismatch():
    # Allow sanitizer startup under suite load; the infinite loop still expires.
    report = compare_sources(source("return 3;"), fixture("timeout.c"), config=config(execution_timeout=3.0))
    assert report.outcome == "timeout", report.explanation
    assert report.original.execution.return_value == 3
    assert report.transformed.execution.return_value is None


def test_missing_compiler_returns_unavailable_without_invented_observations(tmp_path):
    missing = str(tmp_path / "no such clang executable")
    report = check_equivalence(source("return 2+3;"), ("constants",), config=CompileConfig(compiler=missing))
    assert report.outcome == "unavailable", report.explanation
    assert report.original.execution is None
    assert report.transformed.execution is None


@requires_clang
def test_unsupported_compiler_option_is_a_compilation_failure_with_actual_diagnostics():
    report = check_equivalence(
        source("return 2+3;"), ("constants",),
        config=config(extra_flags=("-Werror", "-Wcodedna-intentionally-invalid-option")),
    )
    assert report.outcome == "compilation_failure", report.explanation
    assert report.original.execution is None
    assert report.transformed.execution is None
    diagnostics = report.original.compilation.stderr + report.transformed.compilation.stderr
    assert "-Wcodedna-intentionally-invalid-option" in diagnostics
    assert "unknown warning option" in diagnostics.lower()


@pytest.mark.parametrize("flag", [
    "-fno-sanitize=all", "-fno-sanitize=undefined", "-fwrapv", "-ftrapv",
    "-O2", "-std=c89", "-m32", "-o", "-c", "-Xclang", "-Wl,-no_pie",
    "-Wp,-Dfor(x)=if(0)", "-Wa,-defsym,codedna=1",
])
def test_extra_flags_cannot_override_arithmetic_target_sanitizer_or_artifact_settings(flag):
    with pytest.raises(ValueError):
        CompileConfig(extra_flags=(flag,))


@pytest.mark.parametrize("left,right", [
    ("int main(){return missing;}", "int main(){return 1;}"),
    ("int main(){return 1;}", "int main(){return missing;}"),
    ("int main(){return 1/0;}", "int main(){return 1;}"),
])
def test_deliberate_source_comparison_still_enforces_the_supported_language(left, right):
    with pytest.raises(FrontendError):
        compare_sources(left, right)


@requires_clang
def test_original_source_and_ast_are_preserved_and_canonical_sources_are_real():
    original_source = "// source identity\nint main() { int x=2+3; return x*100+7; }\n"
    original_ast = parse(original_source)
    snapshot = ast.ast_to_json(original_ast)
    report = check_equivalence(original_source, ("constants",), config=config(), source_name="identity.c")
    assert_observed(report, 507)
    assert original_source == "// source identity\nint main() { int x=2+3; return x*100+7; }\n"
    assert ast.ast_to_json(original_ast) == snapshot
    assert report.original.canonical_source == emit_c(original_ast)
    assert "return (507);" in report.transformed.canonical_source
    assert report.original.source_sha256 == hashlib.sha256(original_source.encode("utf-8")).hexdigest()
    analyze(parse(report.transformed.canonical_source))


@requires_clang
def test_report_json_separates_repeatable_results_from_ephemeral_execution_metadata():
    original = source("int x=16*16;return x+1;")
    first = check_equivalence(original, ("constants",), config=config(), source_name="report.c")
    second = check_equivalence(original, ("constants",), config=config(), source_name="report.c")
    assert_observed(first, 257)
    assert_observed(second, 257)
    first_data = first.to_dict()
    second_data = second.to_dict()
    assert json.loads(first.to_json()) == first_data
    assert first_data["result"] == second_data["result"]
    assert first_data["environment_metadata"]
    assert "command" in json.dumps(first_data["environment_metadata"])
    assert "benchmark" not in first_data["result"]
    assert "wall_time_ns" not in first_data["result"]


@pytest.mark.parametrize("name", sorted(path.name for path in EXAMPLES.glob("*.c")))
def test_runtime_examples_remain_genuine_semantically_valid_subset_sources(name):
    program = parse(fixture(name))
    analyze(program)
    assert program.function.name == "main"


@requires_clang
@pytest.mark.parametrize("name,sequence,expected", [
    ("constants_return257.c", ("constants",), 257),
    ("negative_math.c", ("constants",), -201),
    ("zero_trip_final.c", ("unroll",), 12),
])
def test_runtime_success_examples_compile_and_compare_for_real(name, sequence, expected):
    report = check_equivalence(fixture(name), sequence, config=config(), source_name=name)
    assert_observed(report, expected)

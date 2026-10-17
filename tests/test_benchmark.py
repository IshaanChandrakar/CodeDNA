"""Benchmark orchestration, failure exclusion and genuine repeated Clang runs."""

from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import shutil
import statistics
from types import MappingProxyType

import pytest

from runtime.benchmark import benchmark, format_benchmark_summary, measurement_order
from runtime.benchmark_models import BenchmarkConfig, TimedExecution
from runtime.compiler_runner import CompilerRunner
from runtime.equivalence import EquivalenceReport, VariantReport
from runtime.models import CompilationResult, CompileConfig, CompiledArtifact, CompilerInfo, ExecutionResult
from transformations.common import Statistics, TransformationReport


benchmark_module = importlib.import_module("runtime.benchmark")
ROOT = Path(__file__).resolve().parents[1]
CLANG = shutil.which("clang")
requires_clang = pytest.mark.skipif(CLANG is None, reason="Real benchmark integration requires Clang compilation and execution")


def successful(value=1, **changes):
    return ExecutionResult("success", process_returncode=0, return_value=value, **changes)


def fake_prepared(monkeypatch, tmp_path, *, outcome="observed_equivalent", warmups=(), measurements=()):
    """Inject only the prepared boundary; production orchestration stays intact."""
    workspace = tmp_path / "prepared runner"
    workspace.mkdir()
    compile_config = CompileConfig()
    variants = {}
    for name in ("original", "transformed"):
        path = workspace / name
        path.write_text("synthetic executable identity", encoding="utf-8")
        artifact = CompiledArtifact(path, name, True, "observation.json")
        compilation = CompilationResult(
            "success", artifact=artifact, command=("fixture-clang", "-O0", str(path)),
            returncode=0, source_sha256=name,
        )
        variants[name] = VariantReport("int main(void){return 1;}\n", name, compilation, successful())
    report = EquivalenceReport(
        outcome, "Synthetic prepared validation result", "transformation_pipeline", "fixture.c", "source-hash",
        ("constants",), (TransformationReport("constants", "1", "applied", (), Statistics(changed_nodes=1), ()),),
        MappingProxyType({}), compile_config, CompilerInfo("available", path="fixture-clang", version="fixture clang"),
        variants["original"], variants["transformed"], workspace=str(workspace),
    )

    class Runner:
        def __init__(self):
            self.calls = []
            self.active = False
            self.closed = False
            self.warmups = list(warmups)
            self.measurements = list(measurements)
            self.forwarded = None

        def take(self, artifact, phase, plan):
            assert self.active and artifact.path.exists(), "Prepared artifact must remain alive while sampling"
            self.calls.append((phase, artifact.path.name, artifact))
            if plan:
                result = plan.pop(0)
                if isinstance(result, BaseException):
                    raise result
                return result
            return successful() if phase == "warmup" else TimedExecution(successful(), 100 if artifact.path.name == "original" else 50)

        def execute(self, artifact):
            return self.take(artifact, "warmup", self.warmups)

        def timed_execute(self, artifact):
            return self.take(artifact, "measurement", self.measurements)

    runner = Runner()

    @contextmanager
    def prepare(*args, **kwargs):
        runner.forwarded = (args, kwargs)
        runner.active = True
        try:
            yield runner, report
        finally:
            runner.active = False
            runner.closed = True
            shutil.rmtree(workspace)

    monkeypatch.setattr(benchmark_module, "prepared_equivalence", prepare)
    return runner, report


def run_fake(monkeypatch, tmp_path, *, config=None, **plans):
    runner, validation = fake_prepared(monkeypatch, tmp_path, **plans)
    report = benchmark("int main(){return 1+0;}", config=config or BenchmarkConfig(warmups=0, repetitions=3), benchmark_id="controlled")
    return runner, validation, report


def assert_no_comparison(report):
    assert report.comparison.status == "unavailable"
    assert report.comparison.speedup is None and report.comparison.percentage_change is None
    assert all(summary.median_ns is None and summary.mean_ns is None for _, summary in report.summaries)


def test_warmups_measurements_alternate_in_balanced_pairs_and_preserve_raw_durations(monkeypatch, tmp_path):
    durations = [100, 50, 60, 110, 120, 70]
    runner, validation, report = run_fake(
        monkeypatch, tmp_path, config=BenchmarkConfig(warmups=2, repetitions=3),
        measurements=[TimedExecution(successful(), value) for value in durations],
    )
    assert report.status == "completed"
    assert [(sample.phase, sample.round_index, sample.variant) for sample in report.samples] == [
        ("warmup", 0, "original"), ("warmup", 0, "transformed"),
        ("warmup", 1, "transformed"), ("warmup", 1, "original"),
        ("measurement", 0, "original"), ("measurement", 0, "transformed"),
        ("measurement", 1, "transformed"), ("measurement", 1, "original"),
        ("measurement", 2, "original"), ("measurement", 2, "transformed"),
    ]
    assert [sample.order_index for sample in report.samples] == list(range(10))
    assert [sample.duration_ns for sample in report.samples[:4]] == [None] * 4
    assert [sample.duration_ns for sample in report.samples[4:]] == durations
    assert all(sample.valid and sample.matches_expected for sample in report.samples)
    summaries = dict(report.summaries)
    assert summaries["original"].count == summaries["transformed"].count == 3
    assert summaries["original"].median_ns == 110
    assert summaries["transformed"].median_ns == 60
    assert report.comparison.speedup == pytest.approx(110 / 60)
    assert report.comparison.status == "unreliable"  # Three samples are descriptive and undersampled.
    assert runner.closed and not Path(validation.workspace).exists()
    for _, variant, artifact in runner.calls:
        assert artifact is getattr(validation, variant).compilation.artifact


@pytest.mark.parametrize("rounds,expected", [
    (0, []), (1, [(0, "original"), (0, "transformed")]),
    (2, [(0, "original"), (0, "transformed"), (1, "transformed"), (1, "original")]),
])
def test_order_schedule_is_reproducible_and_balances_each_round(rounds, expected):
    assert list(measurement_order(rounds)) == expected
    assert list(measurement_order(rounds)) == expected


def test_zero_warmups_do_not_execute_unrequested_untimed_runs(monkeypatch, tmp_path):
    runner, _, report = run_fake(monkeypatch, tmp_path, config=BenchmarkConfig(warmups=0, repetitions=1))
    assert [call[:2] for call in runner.calls] == [("measurement", "original"), ("measurement", "transformed")]
    assert len(report.samples) == 2
    assert all(sample.phase == "measurement" for sample in report.samples)


@pytest.mark.parametrize("outcome", [
    "different_behavior", "compilation_failure", "execution_failure", "timeout", "undefined_behavior",
    "unavailable", "inconclusive", "no_transformation",
])
def test_failed_or_unaccepted_validation_prevents_every_warmup_and_measurement(monkeypatch, tmp_path, outcome):
    runner, validation, report = run_fake(monkeypatch, tmp_path, outcome=outcome)
    assert report.status == outcome
    assert report.validation is validation
    assert report.samples == () and runner.calls == []
    assert_no_comparison(report)
    assert runner.closed


@pytest.mark.parametrize("status,expected_status", [
    ("timeout", "timeout"), ("undefined_behavior", "undefined_behavior"), ("signal", "execution_failure"),
    ("os_error", "execution_failure"), ("output_limit", "execution_failure"), ("protocol_error", "execution_failure"),
    ("interrupted", "interrupted"),
])
def test_warmup_failures_are_recorded_and_stop_before_measured_samples(monkeypatch, tmp_path, status, expected_status):
    failed = ExecutionResult(status, detail="controlled warm-up failure")
    runner, _, report = run_fake(
        monkeypatch, tmp_path, config=BenchmarkConfig(warmups=1, repetitions=3), warmups=[successful(), failed],
    )
    assert report.status == expected_status
    assert len(report.samples) == 2 and len(runner.calls) == 2
    assert [sample.phase for sample in report.samples] == ["warmup", "warmup"]
    assert report.samples[0].valid and not report.samples[1].valid
    assert report.samples[1].issue == status and report.samples[1].duration_ns is None
    assert_no_comparison(report)


@pytest.mark.parametrize("status,expected_status", [
    ("timeout", "timeout"), ("undefined_behavior", "undefined_behavior"), ("signal", "execution_failure"),
    ("nonzero_exit", "execution_failure"), ("missing_executable", "execution_failure"),
])
def test_a_later_failed_measurement_invalidates_both_groups_including_a_completed_other_side(monkeypatch, tmp_path, status, expected_status):
    runner, _, report = run_fake(
        monkeypatch, tmp_path, config=BenchmarkConfig(warmups=0, repetitions=1),
        measurements=[TimedExecution(successful(), 100), TimedExecution(ExecutionResult(status), 50)],
    )
    assert report.status == expected_status and len(runner.calls) == 2
    assert [sample.duration_ns for sample in report.samples] == [100, 50]
    assert report.samples[0].valid and not report.samples[1].valid
    assert_no_comparison(report)
    groups = report.to_dict()["benchmark"]["groups"]
    assert groups["original"]["successful_samples"] == 1
    assert groups["transformed"]["successful_samples"] == 0
    assert groups["original"]["summary"]["status"] == "invalid"
    assert groups["original"]["summary"]["issues"] == ["comparison_invalid"]


@pytest.mark.parametrize("changed", [
    successful(257), successful(None), successful(stdout="unexpected output"), successful(stderr="unexpected diagnostic"),
    ExecutionResult("success", process_returncode=1, return_value=1),
])
def test_repeated_behavior_drift_checks_full_returns_and_all_observed_streams(monkeypatch, tmp_path, changed):
    _, validation, report = run_fake(
        monkeypatch, tmp_path,
        measurements=[TimedExecution(successful(), 100), TimedExecution(changed, 50)],
    )
    assert report.status == "different_behavior"
    assert len(report.samples) == 2
    assert report.samples[1].issue == "observation_changed"
    assert not report.samples[1].matches_expected and not report.samples[1].valid
    assert validation.transformed.execution.return_value == 1
    assert_no_comparison(report)


def test_low_byte_aliasing_during_measurement_cannot_hide_return_value_drift(monkeypatch, tmp_path):
    _, _, report = run_fake(monkeypatch, tmp_path, measurements=[TimedExecution(successful(257), 100)])
    assert 1 % 256 == 257 % 256
    assert report.samples[0].execution.return_value == 257
    assert report.status == "different_behavior" and not report.samples[0].valid
    assert len(report.samples) == 1


def test_warmup_return_drift_stops_before_any_timing_samples(monkeypatch, tmp_path):
    _, _, report = run_fake(
        monkeypatch, tmp_path, config=BenchmarkConfig(warmups=1, repetitions=3),
        warmups=[successful(), successful(257)],
    )
    assert report.status == "different_behavior"
    assert len(report.samples) == 2 and all(sample.phase == "warmup" for sample in report.samples)
    assert report.samples[-1].issue == "observation_changed"
    assert_no_comparison(report)


@pytest.mark.parametrize("duration", [None, -1, True, False, 1.0, float("nan"), float("inf")])
def test_invalid_clock_values_leave_failed_rows_and_never_produce_partial_averages(monkeypatch, tmp_path, duration):
    _, _, report = run_fake(monkeypatch, tmp_path, measurements=[TimedExecution(successful(), duration)])
    assert report.status == "measurement_failure"
    assert len(report.samples) == 1
    sample = report.samples[0]
    assert sample.matches_expected and not sample.valid and sample.issue == "invalid_duration"
    assert_no_comparison(report)
    json.loads(report.to_json())


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), True])
@pytest.mark.parametrize("execution,status,issue", [
    (ExecutionResult("timeout"), "timeout", "timeout"),
    (successful(257), "different_behavior", "observation_changed"),
])
def test_failure_or_drift_with_invalid_clock_preserves_outcome_and_json_null(monkeypatch, tmp_path, duration, execution, status, issue):
    _, _, report = run_fake(monkeypatch, tmp_path, measurements=[TimedExecution(execution, duration)])
    assert report.status == status
    assert len(report.samples) == 1
    sample = report.samples[0]
    assert sample.execution is execution
    assert sample.issue == issue and not sample.valid
    assert sample.duration_ns is None
    assert_no_comparison(report)
    data = json.loads(report.to_json())
    assert data["benchmark"]["samples"][0]["duration_ns"] is None


def test_real_zero_clock_values_are_preserved_without_fabricated_ratios_or_formatter_errors(monkeypatch, tmp_path):
    _, _, report = run_fake(
        monkeypatch, tmp_path, config=BenchmarkConfig(warmups=0, repetitions=1),
        measurements=[TimedExecution(successful(), 0), TimedExecution(successful(), 10)],
    )
    assert report.status == "completed"
    assert report.samples[0].duration_ns == 0 and report.samples[0].valid
    assert dict(report.summaries)["original"].median_ns == 0
    assert report.comparison.status == "unavailable"
    assert report.comparison.speedup == 0 and report.comparison.percentage_change is None
    assert "clock_resolution" in dict(report.summaries)["original"].issues
    assert "unavailable" in format_benchmark_summary(report)
    json.loads(report.to_json())


@pytest.mark.parametrize("phase", ["warmup", "measurement"])
def test_keyboard_interruption_stops_the_schedule_preserves_failure_and_closes_context(monkeypatch, tmp_path, phase):
    options = {"warmups": [KeyboardInterrupt()]} if phase == "warmup" else {
        "measurements": [TimedExecution(successful(), 100), KeyboardInterrupt()],
    }
    runner, validation, report = run_fake(
        monkeypatch, tmp_path, config=BenchmarkConfig(warmups=1 if phase == "warmup" else 0, repetitions=3), **options,
    )
    assert report.status == "interrupted"
    assert report.samples[-1].execution.status == "interrupted"
    assert report.samples[-1].duration_ns is None and not report.samples[-1].valid
    assert runner.closed and not Path(validation.workspace).exists()
    assert_no_comparison(report)
    if phase == "measurement":
        assert [sample.duration_ns for sample in report.samples] == [100, None]


def test_complete_records_separate_compiler_analysis_from_measurements_and_unavailable_hardware(monkeypatch, tmp_path):
    _, validation, report = run_fake(monkeypatch, tmp_path)
    data = report.to_dict()
    assert data["analysis"] == validation.to_dict()["result"]
    assert "samples" not in data["analysis"] and "duration_ns" not in json.dumps(data["analysis"])
    settings = data["benchmark"]["settings"]
    assert settings["compilation_timed"] is False and settings["warmups_timed"] is False
    assert settings["duration_unit"] == "ns" and settings["measurement_scope"] == "end_to_end_process_execution"
    hardware = data["benchmark"]["metrics"]["hardware_instructions"]
    assert hardware["value"] is None and hardware["status"] == "unavailable" and hardware["reason"]
    assert json.loads(report.to_json()) == data
    text = format_benchmark_summary(report)
    assert "process" in text.lower() and "Hardware instructions: unavailable" in text
    assert "No computational speedup or statistical significance is established" in text


def test_benchmark_forwards_exact_preparation_settings_and_user_identity(monkeypatch, tmp_path):
    runner, _ = fake_prepared(monkeypatch, tmp_path)
    compile_config = CompileConfig(optimization="O2", execution_timeout=3)
    config = BenchmarkConfig(compile_config=compile_config, warmups=0, repetitions=1, max_iterations=7)
    report = benchmark("original source", (), config=config, source_name="first.c", comparison_source="second source", comparison_source_name="second.c", benchmark_id="run-1.2_test")
    assert report.benchmark_id == "run-1.2_test"
    args, options = runner.forwarded
    assert args == ("original source", ())
    assert options == {
        "config": compile_config, "max_iterations": 7, "source_name": "first.c",
        "comparison_source": "second source", "comparison_source_name": "second.c",
    }


@pytest.mark.parametrize("field,bad", [
    ("warmups", -1), ("warmups", 10001), ("warmups", True), ("warmups", 1.0),
    ("repetitions", 0), ("repetitions", -1), ("repetitions", 10001), ("repetitions", True), ("repetitions", 1.0),
    ("max_iterations", -1), ("max_iterations", 1025), ("max_iterations", True),
    ("compile_config", None), ("compile_config", False), ("compile_config", {}),
])
def test_invalid_benchmark_configuration_is_rejected_before_execution(field, bad):
    with pytest.raises(ValueError):
        BenchmarkConfig(**{field: bad})


@pytest.mark.parametrize("bad", [False, 0, "config", object()])
def test_falsey_or_wrong_config_objects_are_not_silently_replaced_with_defaults(bad):
    with pytest.raises(ValueError):
        benchmark("int main(){return 1;}", config=bad)


@pytest.mark.parametrize("identifier", ["", "../escape", ".hidden", " bad", "bad/name", "a" * 129, True, 17])
def test_invalid_benchmark_identifiers_are_rejected_before_preparation(monkeypatch, identifier):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid IDs must be rejected before compilation or execution")
    monkeypatch.setattr(benchmark_module, "prepared_equivalence", unexpected)
    with pytest.raises(ValueError):
        benchmark("int main(){return 1;}", benchmark_id=identifier)


def integration_config(optimization="O0", *, sanitize=True, execution_timeout=3):
    return BenchmarkConfig(
        compile_config=CompileConfig(compiler=CLANG or "clang", optimization=optimization, sanitize=sanitize, execution_timeout=execution_timeout),
        warmups=1, repetitions=3,
    )


@requires_clang
@pytest.mark.integration
@pytest.mark.parametrize("optimization", ["O0", "O2"])
@pytest.mark.parametrize("name,sequence,expected", [
    ("runtime/constants_return257.c", ("constants",), 257),
    ("transformations/unroll_positive.c", ("unroll",), 64),
    ("transformations/combined.c", ("constants", "unroll", "constants"), 146),
    ("runtime/negative_math.c", ("constants",), -201),
])
def test_real_clang_repeated_benchmarks_validate_each_observation_and_keep_raw_samples(optimization, name, sequence, expected):
    original_source = (ROOT / "examples" / name).read_text(encoding="utf-8")
    report = benchmark(original_source, sequence, config=integration_config(optimization), source_name=name, benchmark_id="real-integration")
    assert report.status == "completed", report.explanation
    assert report.validation.outcome == "observed_equivalent"
    assert len(report.samples) == 8
    measured = [sample for sample in report.samples if sample.phase == "measurement"]
    assert len(measured) == 6
    for sample in report.samples:
        assert sample.valid and sample.matches_expected
        assert sample.execution.status == "success" and sample.execution.return_value == expected
        assert sample.execution.process_returncode == 0
        if sample.phase == "measurement":
            assert type(sample.duration_ns) is int and sample.duration_ns >= 0
        else:
            assert sample.duration_ns is None
    for variant, summary in report.summaries:
        raw = [sample.duration_ns for sample in measured if sample.variant == variant]
        assert summary.count == 3 and summary.status == "available"
        assert summary.median_ns == statistics.median(raw)
        assert summary.mean_ns == statistics.mean(raw)
        compilation = getattr(report.validation, variant).compilation
        assert f"-{optimization}" in compilation.command
        assert all(sample.execution.command[0] == str(compilation.artifact.path) for sample in report.samples if sample.variant == variant)
    assert not Path(report.validation.workspace).exists()
    data = report.to_dict()
    assert data["benchmark"]["metrics"]["hardware_instructions"]["value"] is None
    assert "process_startup_scope" in report.comparison.issues
    assert json.loads(report.to_json()) == data


@requires_clang
@pytest.mark.integration
def test_validation_and_measurement_reuse_the_same_live_artifacts_without_recompilation(monkeypatch):
    events = []
    original_compile = CompilerRunner.compile_source
    original_execute = CompilerRunner.execute
    original_timed = CompilerRunner.timed_execute

    def compiling(self, source, **options):
        result = original_compile(self, source, **options)
        events.append(("compile", options.get("label"), result.artifact.path if result.artifact else None, str(self.root)))
        return result

    def executing(self, artifact, case=None):
        assert artifact.path.exists() and self.root.exists()
        events.append(("execute", None, artifact.path, str(self.root)))
        return original_execute(self, artifact, case)

    def timing(self, artifact, case=None):
        assert artifact.path.exists() and self.root.exists()
        events.append(("timed", None, artifact.path, str(self.root)))
        return original_timed(self, artifact, case)

    monkeypatch.setattr(CompilerRunner, "compile_source", compiling)
    monkeypatch.setattr(CompilerRunner, "execute", executing)
    monkeypatch.setattr(CompilerRunner, "timed_execute", timing)
    report = benchmark("int main(){return 2+3;}", config=integration_config(), benchmark_id="same-artifacts")
    assert report.status == "completed", report.explanation
    builds = [event for event in events if event[0] == "compile"]
    assert [event[1] for event in builds] == ["capability", "original", "transformed"]
    assert len({event[3] for event in events}) == 1
    first_timed = next(index for index, event in enumerate(events) if event[0] == "timed")
    assert not any(event[0] == "compile" for event in events[first_timed:])
    for variant in ("original", "transformed"):
        artifact = getattr(report.validation, variant).compilation.artifact.path
        assert sum(event[0] == "timed" and event[2] == artifact for event in events) == 3
        assert sum(event[0] == "execute" and event[2] == artifact for event in events) == 2  # Validation + warm-up.
        assert not artifact.exists()
    assert not Path(report.validation.workspace).exists()


@requires_clang
@pytest.mark.integration
@pytest.mark.parametrize("source,sequence,status", [
    ("int main(){return 7;}", ("constants",), "no_transformation"),
    ((ROOT / "examples/transformations/rejected_declaration.c").read_text(), ("unroll",), "no_transformation"),
    ((ROOT / "examples/runtime/dynamic_divzero.c").read_text(), ("constants",), "undefined_behavior"),
    ((ROOT / "examples/runtime/timeout.c").read_text(), ("constants",), "timeout"),
])
def test_real_unaccepted_or_unsafe_comparisons_have_no_timing_samples(source, sequence, status):
    report = benchmark(source, sequence, config=integration_config(), benchmark_id="invalid-real-comparison")
    assert report.validation.outcome == status and report.status == status
    assert report.samples == ()
    assert_no_comparison(report)


@requires_clang
@pytest.mark.integration
def test_real_deliberately_different_full_returns_block_benchmark_measurements():
    report = benchmark(
        "int main(){return 1;}", (), comparison_source="int main(){return 257;}",
        config=integration_config(), benchmark_id="real-negative-control",
    )
    assert report.status == report.validation.outcome == "different_behavior"
    assert report.validation.original.execution.return_value == 1
    assert report.validation.transformed.execution.return_value == 257
    assert report.samples == ()
    assert_no_comparison(report)


@requires_clang
@pytest.mark.integration
def test_unsanitized_matching_runs_are_inconclusive_and_never_measured():
    report = benchmark("int main(){return 2+3;}", config=integration_config(sanitize=False), benchmark_id="unchecked")
    assert report.status == report.validation.outcome == "inconclusive"
    assert report.samples == ()
    assert_no_comparison(report)


def test_missing_compiler_is_unavailable_without_any_samples(tmp_path):
    config = BenchmarkConfig(compile_config=CompileConfig(compiler=str(tmp_path / "missing-clang")), warmups=1, repetitions=3)
    report = benchmark("int main(){return 2+3;}", config=config, benchmark_id="missing-compiler")
    assert report.status == report.validation.outcome == "unavailable"
    assert report.samples == ()
    assert_no_comparison(report)


@requires_clang
@pytest.mark.integration
def test_real_compiler_diagnostic_failure_blocks_timing_and_retains_diagnostics():
    config = BenchmarkConfig(
        compile_config=CompileConfig(compiler=CLANG, extra_flags=("-Werror", "-Wcodedna-intentionally-invalid-option")),
        warmups=1, repetitions=3,
    )
    report = benchmark("int main(){return 2+3;}", config=config, benchmark_id="compiler-failure")
    assert report.status == "compilation_failure" and report.samples == ()
    assert "unknown warning option" in report.validation.original.compilation.stderr
    assert_no_comparison(report)


@requires_clang
@pytest.mark.integration
def test_repeated_real_benchmarks_keep_deterministic_analysis_separate_from_timing_data():
    config = BenchmarkConfig(compile_config=CompileConfig(compiler=CLANG, execution_timeout=3), warmups=0, repetitions=1)
    first = benchmark("int main(){return 2+3;}", config=config, source_name="stable.c", benchmark_id="stable")
    second = benchmark("int main(){return 2+3;}", config=config, source_name="stable.c", benchmark_id="stable")
    assert first.status == second.status == "completed"
    assert first.to_dict()["analysis"] == second.to_dict()["analysis"]
    assert first.to_dict()["analysis"] == first.validation.to_dict()["result"]
    assert "duration_ns" not in json.dumps(first.to_dict()["analysis"])
    assert len(first.samples) == len(second.samples) == 2

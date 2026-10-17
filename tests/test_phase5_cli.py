"""Real repeated measurements, honest CLI summaries, exports and preflight safety."""

import csv
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
from types import SimpleNamespace

import pytest

from runtime.benchmark_storage import SAMPLE_COLUMNS, SUMMARY_COLUMNS


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "examples" / "runtime"
TRANSFORMATIONS = ROOT / "examples" / "transformations"
CLANG = shutil.which("clang")
requires_clang = pytest.mark.skipif(CLANG is None, reason="Benchmark CLI integration requires the Clang executable")


def cli(*arguments, cwd=ROOT):
    return subprocess.run(
        [sys.executable, "-m", "compiler", *map(str, arguments)],
        cwd=cwd, capture_output=True, text=True, timeout=60,
    )


def benchmark_report(tmp_path, source, *arguments, expected_exit=0):
    output = tmp_path / "exports" / "benchmark.json"
    completed = cli("--benchmark", "--warmups", "0", "--repetitions", "2",
                    "--execution-timeout", "3", "--output", output, *arguments, source)
    assert completed.returncode == expected_exit, completed.stderr or completed.stdout
    assert "Traceback" not in completed.stderr
    assert output.exists(), completed.stderr
    data = json.loads(output.read_text())
    assert set(data) == {"schema_version", "benchmark_id", "analysis", "environment_metadata", "benchmark"}
    assert data["schema_version"] == 1
    return completed, data, output


@pytest.mark.integration
@requires_clang
@pytest.mark.parametrize("optimization", ["O0", "O2"])
@pytest.mark.parametrize("path,sequence,expected", [
    (RUNTIME / "constants_return257.c", (), 257),
    (TRANSFORMATIONS / "unroll_positive.c", ("unroll",), 64),
    (TRANSFORMATIONS / "combined.c", ("constants", "unroll", "constants"), 146),
    (RUNTIME / "negative_math.c", ("constants",), -201),
])
def test_real_benchmarks_preserve_all_samples_and_expected_results_without_speedup_thresholds(tmp_path, optimization, path, sequence, expected):
    flags = [flag for name in sequence for flag in ("--transform", name)]
    completed, data, _ = benchmark_report(tmp_path, path, "--opt", optimization, *flags)
    measured = data["benchmark"]
    assert measured["status"] == "completed"
    assert data["analysis"]["outcome"] == "observed_equivalent"
    assert data["analysis"]["sequence"] == list(sequence or ("constants",))
    assert data["analysis"]["settings"]["optimization"] == optimization
    samples = measured["samples"]
    assert len(samples) == 4
    assert [sample["variant"] for sample in samples] == ["original", "transformed", "transformed", "original"]
    assert [sample["order_index"] for sample in samples] == list(range(4))
    assert all(sample["phase"] == "measurement" for sample in samples)
    assert all(type(sample["duration_ns"]) is int and sample["duration_ns"] >= 0 for sample in samples)
    assert all(sample["duration_unit"] == "ns" and sample["measurement_scope"] == "end_to_end_process_execution" for sample in samples)
    assert all(sample["valid"] and sample["matches_expected"] for sample in samples)
    assert all(sample["execution"]["return_value"] == expected and sample["execution"]["process_returncode"] == 0 for sample in samples)
    for variant in ("original", "transformed"):
        durations = [sample["duration_ns"] for sample in samples if sample["variant"] == variant]
        group = measured["groups"][variant]
        summary = group["summary"]
        assert group["expected_samples"] == group["attempted_samples"] == group["successful_samples"] == 2
        assert summary["count"] == 2
        assert summary["median_ns"] == statistics.median(durations)
        assert summary["mean_ns"] == statistics.mean(durations)
        assert summary["min_ns"] == min(durations) and summary["max_ns"] == max(durations)
        assert summary["stdev_ns"] == pytest.approx(statistics.stdev(durations))
    assert measured["settings"]["compilation_timed"] is False
    assert measured["comparison"]["status"] == "unreliable"  # Only two samples: explicitly undersampled.
    assert "undersampled" in measured["comparison"]["issues"]
    assert measured["metrics"]["hardware_instructions"]["value"] is None
    assert measured["metrics"]["hardware_instructions"]["status"] == "unavailable"
    assert "Duration scope: end-to-end process execution" in completed.stdout
    assert "No computational speedup or statistical significance is established." in completed.stdout
    assert '"samples":' not in completed.stdout
    assert completed.stderr == ""


@pytest.mark.integration
@requires_clang
def test_json_and_csv_keep_warmups_separate_from_timed_samples_and_aggregates(tmp_path):
    completed, data, output = benchmark_report(tmp_path, RUNTIME / "constants_return257.c", "--warmups", "1", "--csv")
    raw_path = output.with_suffix(".samples.csv")
    summary_path = output.with_suffix(".summary.csv")
    assert all(f"Saved {path}\n" in completed.stdout for path in (output, raw_path, summary_path))
    samples = data["benchmark"]["samples"]
    assert [sample["phase"] for sample in samples] == ["warmup", "warmup", *(["measurement"] * 4)]
    assert [sample["variant"] for sample in samples] == ["original", "transformed", "original", "transformed", "transformed", "original"]
    assert all(sample["duration_ns"] is None for sample in samples[:2])
    assert all(type(sample["duration_ns"]) is int for sample in samples[2:])
    with raw_path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == list(SAMPLE_COLUMNS)
    assert len(rows) == len(samples) == 6
    assert [row["duration_ns"] for row in rows[:2]] == ["", ""]
    assert [int(row["duration_ns"]) for row in rows[2:]] == [sample["duration_ns"] for sample in samples[2:]]
    assert all(row["return_value"] == "257" and row["process_returncode"] == "0" for row in rows)
    assert all(row["benchmark_id"] == data["benchmark_id"] for row in rows)
    with summary_path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        groups = list(reader)
        assert reader.fieldnames == list(SUMMARY_COLUMNS)
    assert [group["variant"] for group in groups] == ["original", "transformed"]
    for group in groups:
        expected = data["benchmark"]["groups"][group["variant"]]
        assert int(group["successful_samples"]) == int(group["attempted_samples"]) == 2
        assert float(group["median_ns"]) == expected["summary"]["median_ns"]
        assert group["duration_unit"] == "ns"
        assert group["hardware_instructions"] == "" and group["hardware_instructions_status"] == "unavailable"
        assert group["benchmark_id"] == data["benchmark_id"]


@pytest.mark.integration
@requires_clang
def test_default_output_is_saved_in_a_benchmark_identifier_directory_under_current_cwd(tmp_path):
    completed = cli("--benchmark", "--warmups", "0", "--repetitions", "1",
                    "--execution-timeout", "3", RUNTIME / "constants_return257.c", cwd=tmp_path)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    outputs = list((tmp_path / "results").glob("*/benchmark.json"))
    assert len(outputs) == 1
    output = outputs[0]
    data = json.loads(output.read_text())
    assert output.parent.name == data["benchmark_id"]
    assert len(data["benchmark_id"]) == 32
    assert "Saved results/" in completed.stdout
    assert data["benchmark"]["groups"]["original"]["successful_samples"] == 1


@pytest.mark.integration
@requires_clang
def test_independent_equal_sources_can_be_benchmarked_without_inventing_transformation_passes(tmp_path):
    other = tmp_path / "same-result.c"
    other.write_text("int main(){return 257;}\n")
    _, data, _ = benchmark_report(tmp_path, RUNTIME / "constants_return257.c", "--against", other)
    assert data["analysis"]["comparison_kind"] == "independent_sources"
    assert data["analysis"]["sequence"] == []
    assert data["analysis"]["comparison_source"]["name"] == str(other)
    assert data["benchmark"]["status"] == "completed" and len(data["benchmark"]["samples"]) == 4


@pytest.mark.integration
@requires_clang
@pytest.mark.parametrize("path,flags,status,exit_code", [
    (ROOT / "examples" / "basic" / "minimal.c", ("--transform", "unroll"), "no_transformation", 6),
    (TRANSFORMATIONS / "rejected_induction.c", ("--transform", "unroll"), "no_transformation", 6),
    (RUNTIME / "mismatch_one.c", ("--against", RUNTIME / "mismatch_257.c"), "different_behavior", 5),
    (RUNTIME / "constants_return257.c", ("--no-sanitize",), "inconclusive", 6),
    (RUNTIME / "dynamic_divzero.c", (), "undefined_behavior", 4),
    (RUNTIME / "timeout.c", ("--execution-timeout", "0.2"), "timeout", 4),
])
def test_invalid_unavailable_or_unaccepted_comparisons_stop_before_timed_sampling(tmp_path, path, flags, status, exit_code):
    _, data, _ = benchmark_report(tmp_path, path, *flags, expected_exit=exit_code)
    measured = data["benchmark"]
    assert measured["status"] == data["analysis"]["outcome"] == status
    assert measured["samples"] == []
    assert measured["comparison"]["status"] == "unavailable"
    assert measured["comparison"]["speedup"] is None and measured["comparison"]["percentage_change"] is None
    assert all(group["successful_samples"] == group["attempted_samples"] == 0 for group in measured["groups"].values())
    assert all(group["summary"]["median_ns"] is None for group in measured["groups"].values())


def test_unavailable_compiler_saves_defaults_and_failure_with_no_fake_samples(tmp_path):
    output = tmp_path / "unavailable.json"
    completed = cli("--benchmark", "--clang", tmp_path / "missing compiler", "--output", output,
                    RUNTIME / "constants_return257.c")
    assert completed.returncode == 6 and completed.stderr == ""
    data = json.loads(output.read_text())
    measured = data["benchmark"]
    assert measured["status"] == "unavailable" and measured["samples"] == []
    assert measured["settings"]["warmups_per_variant"] == 5
    assert measured["settings"]["measurements_per_variant"] == 30
    assert data["analysis"]["settings"]["execution_timeout_seconds"] == 2
    assert "Saved " in completed.stdout and "unavailable" in completed.stdout


@pytest.mark.parametrize("which", ["samples", "summary"])
def test_custom_csv_outputs_are_independent_and_do_not_require_the_csv_pair_flag(tmp_path, which):
    output = tmp_path / "report.json"
    custom = tmp_path / "csv exports" / "observations.csv"
    completed = cli("--benchmark", "--clang", tmp_path / "missing compiler", "--output", output,
                    f"--{which}-csv", custom, RUNTIME / "constants_return257.c")
    assert completed.returncode == 6 and completed.stderr == ""
    assert custom.is_file()
    assert not output.with_suffix(".samples.csv").exists()
    assert not output.with_suffix(".summary.csv").exists()
    with custom.open(newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == list(SAMPLE_COLUMNS if which == "samples" else SUMMARY_COLUMNS)
    if which == "samples":
        assert rows == []
    else:
        assert len(rows) == 2 and all(row["median_ns"] == "" for row in rows)


@pytest.mark.skipif(os.name != "posix", reason="Executable compiler fixture uses POSIX shebang semantics")
def test_compilation_failure_keeps_a_saved_failure_report_and_exit_three(tmp_path):
    compiler = tmp_path / "clang fixture"
    compiler.write_text(f"#!{sys.executable}\nimport sys\nif '--version' in sys.argv:\n print('clang test fixture')\nelse:\n print('intentional compiler failure',file=sys.stderr)\n sys.exit(1)\n")
    compiler.chmod(0o700)
    _, data, _ = benchmark_report(tmp_path, RUNTIME / "constants_return257.c", "--clang", compiler, expected_exit=3)
    assert data["benchmark"]["status"] == "compilation_failure"
    assert data["benchmark"]["samples"] == []
    assert "intentional compiler failure" in data["analysis"]["capability"]["compilation"]["stderr"]


@pytest.mark.parametrize("flags", [
    ("--benchmark", "--warmups", "-1"), ("--benchmark", "--warmups", "10001"),
    ("--benchmark", "--warmups", "fraction"), ("--benchmark", "--repetitions", "0"),
    ("--benchmark", "--repetitions", "-1"), ("--benchmark", "--repetitions", "10001"),
    ("--benchmark", "--repetitions", "1.5"), ("--benchmark", "--run"),
    ("--benchmark", "--format", "svg"), ("--benchmark", "--against", "unused.c", "--transform", "constants"),
    ("--run", "--warmups", "0"), ("--equiv", "--repetitions", "2"),
    ("--compile", "--csv"), ("--tac", "--samples-csv", "unused.csv"),
    ("--ast", "--summary-csv", "unused.csv"),
])
def test_invalid_benchmark_counts_and_misplaced_flags_are_argument_errors_without_outputs(tmp_path, flags):
    completed = cli(*flags, "--output", tmp_path / "not-created" / "report.json",
                    RUNTIME / "constants_return257.c", cwd=tmp_path)
    assert completed.returncode == 2 and completed.stdout == ""
    assert "usage:" in completed.stderr and "Traceback" not in completed.stderr
    assert not (tmp_path / "not-created").exists() and not (tmp_path / "results").exists()


@pytest.mark.parametrize("export", ["output", "samples-csv", "summary-csv"])
@pytest.mark.parametrize("which", ["original", "against"])
@pytest.mark.parametrize("alias", ["hardlink", "symlink"])
def test_every_benchmark_export_protects_both_input_files_before_compilation(tmp_path, export, which, alias):
    original, other = tmp_path / "original.c", tmp_path / "other.c"
    original.write_text("int main(){return 1;}\n")
    other.write_text("int main(){return 257;}\n")
    protected = original if which == "original" else other
    destination = tmp_path / "export-alias"
    if alias == "hardlink":
        destination.hardlink_to(protected)
    else:
        destination.symlink_to(protected)
    before = original.read_bytes(), other.read_bytes()
    completed = cli("--benchmark", "--against", other, f"--{export}", destination,
                    "--clang", tmp_path / "missing compiler", original, cwd=tmp_path)
    assert completed.returncode == 2 and completed.stdout == ""
    assert "protected input" in completed.stderr or "symlink" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert (original.read_bytes(), other.read_bytes()) == before
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("collision", ["json_samples", "csv_pair", "hardlink_pair"])
def test_output_collisions_are_rejected_before_any_report_directory_is_created(tmp_path, collision):
    output = tmp_path / "not-created" / "report.json"
    first, second = tmp_path / "first.csv", tmp_path / "second.csv"
    if collision == "json_samples":
        flags = ("--samples-csv", output)
    elif collision == "csv_pair":
        flags = ("--samples-csv", first, "--summary-csv", first)
    else:
        first.write_text("existing csv")
        second.hardlink_to(first)
        flags = ("--samples-csv", first, "--summary-csv", second)
    completed = cli("--benchmark", "--output", output, *flags, RUNTIME / "constants_return257.c")
    assert completed.returncode == 2 and completed.stdout == ""
    assert "alias" in completed.stderr and "Traceback" not in completed.stderr
    assert not output.parent.exists()
    if collision == "hardlink_pair":
        assert first.read_text() == second.read_text() == "existing csv"


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_invalid_existing_csv_destinations_are_refused_before_benchmarking(tmp_path, kind):
    destination = tmp_path / "raw.csv"
    if kind == "directory":
        destination.mkdir()
    else:
        destination.symlink_to(tmp_path / "absent.csv")
    completed = cli("--benchmark", "--samples-csv", destination, RUNTIME / "constants_return257.c", cwd=tmp_path)
    assert completed.returncode == 2 and completed.stdout == ""
    assert "Traceback" not in completed.stderr
    assert not (tmp_path / "results").exists()


def test_source_failure_leaves_existing_export_and_all_optional_parent_directories_untouched(tmp_path):
    source = tmp_path / "invalid.c"
    source.write_text("int main(){return missing;}\n")
    output = tmp_path / "report.json"
    output.write_text("previous report")
    raw = tmp_path / "not-created" / "raw.csv"
    completed = cli("--benchmark", "--output", output, "--samples-csv", raw, source)
    assert completed.returncode == 1 and completed.stdout == ""
    assert "UNDECLARED_VARIABLE" in completed.stderr
    assert output.read_text() == "previous report" and not raw.parent.exists()


def test_saved_interrupted_report_preserves_exit_130(tmp_path, monkeypatch, capsys):
    from compiler import __main__ as command

    output = tmp_path / "interrupted.json"
    data = {"schema_version": 1, "benchmark_id": "synthetic-interruption", "benchmark": {"status": "interrupted", "samples": []}}
    fake = SimpleNamespace(status="interrupted", to_dict=lambda: data)
    monkeypatch.setattr(command, "benchmark", lambda *args, **kwargs: fake)
    monkeypatch.setattr(command, "format_benchmark_summary", lambda report: "Benchmark interrupted (synthetic exit-code fixture)")
    code = command.main(["--benchmark", "--output", str(output), str(RUNTIME / "constants_return257.c")])
    captured = capsys.readouterr()
    assert code == 130 and captured.err == ""
    assert json.loads(output.read_text()) == data
    assert f"Saved {output}" in captured.out

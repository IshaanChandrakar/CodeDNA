"""Benchmark export schemas, missing values and source-preserving file writes."""

from copy import deepcopy
import csv
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path

import pytest

from runtime import benchmark_storage as storage


class ReportFixture:
    """Controlled synthetic observations for export arithmetic/format checks only."""

    def __init__(self, data):
        self.data = data
        self.calls = 0

    def to_dict(self):
        self.calls += 1
        return self.data


@pytest.fixture
def report():
    def observation(phase, order, variant, duration, *, valid=True, issue=None):
        return {
            "phase": phase, "order_index": order, "round_index": 0,
            "variant": variant, "duration_ns": duration, "duration_unit": "ns",
            "measurement_scope": "end_to_end_process_execution",
            "matches_expected": valid, "valid": valid, "issue": issue,
            "execution": {
                "status": "success", "return_value": -257 if variant == "transformed" else 257,
                "process_returncode": 0, "signal": None,
                "stdout": 'quoted,"CSV"\nnext line', "stderr": "", "detail": None,
                "command": ["<workspace>/program"],
            },
        }
    def group(valid):
        return {
            "expected_samples": 2, "attempted_samples": 1,
            "successful_samples": 1 if valid else 0,
            "summary": {
                "status": "available" if valid else "invalid", "count": 1,
                **{name: 0 if valid else None for name in (
                    "median_ns", "mean_ns", "min_ns", "max_ns", "q1_ns", "q3_ns", "iqr_ns",
                )},
                "stdev_ns": None, "coefficient_of_variation": None,
                "issues": ["clock_resolution"] if valid else ["invalid_duration", "invalid_summary"],
            },
        }
    return ReportFixture({
        "schema_version": 1, "benchmark_id": "synthetic-export-fixture",
        "analysis": {"outcome": "different_behavior", "source": {"name": "fixture.c"}},
        "environment_metadata": {"compiler": {"version": "fixture-only"}},
        "benchmark": {
            "status": "invalid", "explanation": "Synthetic unit-test data, not a reported performance run.",
            "settings": {"duration_unit": "ns", "measurement_scope": "end_to_end_process_execution"},
            "samples": [
                observation("warmup", 0, "original", None),
                observation("measurement", 1, "transformed", 0),
                observation("measurement", 2, "original", 100, valid=False, issue="behavior_mismatch"),
            ],
            # Deliberately reverse the input mapping to verify documented order.
            "groups": {"transformed": group(True), "original": group(False)},
            "comparison": {"status": "unavailable", "speedup": None, "percentage_change": None,
                           "issues": ["process_startup_scope", "invalid_summary"]},
            "metrics": {"hardware_instructions": {"value": None, "status": "unavailable", "unit": "instructions",
                                                    "scope": "executed_hardware_instructions", "reason": "No backend"}},
            "limitations": ["Synthetic data is used only to verify storage behavior."],
        },
    })


def test_sample_schema_has_the_documented_explicit_units_and_stable_field_order():
    assert storage.SAMPLE_COLUMNS == (
        "benchmark_id", "phase", "order_index", "round_index", "variant", "duration_ns",
        "duration_unit", "measurement_scope", "status", "matches_expected", "valid", "return_value",
        "process_returncode", "signal", "stdout", "stderr", "detail", "issue",
    )


def test_summary_schema_separates_aggregates_and_unavailable_hardware_values():
    assert storage.SUMMARY_COLUMNS == (
        "benchmark_id", "benchmark_status", "variant", "expected_samples", "attempted_samples",
        "successful_samples", "summary_status", "median_ns", "mean_ns", "min_ns", "max_ns",
        "stdev_ns", "q1_ns", "q3_ns", "iqr_ns", "coefficient_of_variation", "duration_unit",
        "comparison_status", "speedup", "percentage_change", "issues", "hardware_instructions",
        "hardware_instructions_status",
    )


def test_raw_rows_preserve_warmups_zero_durations_failures_and_actual_order(report):
    snapshot = deepcopy(report.data)
    rows = storage.raw_rows(report)
    assert [row["order_index"] for row in rows] == [0, 1, 2]
    assert [row["phase"] for row in rows] == ["warmup", "measurement", "measurement"]
    assert [row["duration_ns"] for row in rows] == [None, 0, 100]
    assert [row["return_value"] for row in rows] == [257, -257, 257]
    assert rows[-1]["status"] == "success" and rows[-1]["valid"] is False
    assert rows[-1]["issue"] == "behavior_mismatch"
    assert all(tuple(row) == storage.SAMPLE_COLUMNS for row in rows)
    assert report.data == snapshot


def test_summary_rows_keep_original_first_and_combine_issue_codes_without_fabricating_metrics(report):
    snapshot = deepcopy(report.data)
    original, transformed = storage.summary_rows(report)
    assert [original["variant"], transformed["variant"]] == ["original", "transformed"]
    assert original["median_ns"] is None and original["successful_samples"] == 0
    assert transformed["median_ns"] == 0 and transformed["stdev_ns"] is None
    assert original["issues"] == "process_startup_scope;invalid_summary;invalid_duration"
    assert transformed["issues"] == "process_startup_scope;invalid_summary;clock_resolution"
    assert original["speedup"] is None and transformed["percentage_change"] is None
    assert original["hardware_instructions"] is None
    assert transformed["hardware_instructions_status"] == "unavailable"
    assert tuple(original) == tuple(transformed) == storage.SUMMARY_COLUMNS
    assert report.data == snapshot


def test_json_and_both_csv_exports_round_trip_supported_fields_and_missing_values(report, tmp_path):
    paths = storage.save_report(report, tmp_path / "report.json", samples_csv=tmp_path / "raw.csv", summary_csv=tmp_path / "summary.csv")
    assert report.calls == 1
    assert json.loads(paths.json_path.read_text()) == report.data
    assert '"duration_ns": null' in paths.json_path.read_text()
    with paths.samples_csv.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == list(storage.SAMPLE_COLUMNS)
    assert [row["duration_ns"] for row in rows] == ["", "0", "100"]
    assert rows[1]["return_value"] == "-257" and rows[1]["process_returncode"] == "0"
    assert rows[0]["signal"] == rows[0]["detail"] == ""
    assert rows[0]["stdout"] == 'quoted,"CSV"\nnext line'
    assert rows[-1]["matches_expected"] == rows[-1]["valid"] == "false"
    assert rows[0]["valid"] == "true"
    with paths.summary_csv.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        original, transformed = list(reader)
        assert reader.fieldnames == list(storage.SUMMARY_COLUMNS)
    assert original["median_ns"] == original["speedup"] == original["hardware_instructions"] == ""
    assert original["hardware_instructions_status"] == "unavailable"
    assert transformed["median_ns"] == transformed["iqr_ns"] == "0"
    assert transformed["stdev_ns"] == transformed["coefficient_of_variation"] == ""
    assert original["duration_unit"] == transformed["duration_unit"] == "ns"


def test_json_only_export_has_optional_paths_and_immutable_export_metadata(report, tmp_path):
    destination = tmp_path / "nested" / "report.json"
    paths = storage.save_report(report, str(destination))
    assert paths == storage.ExportPaths(destination)
    assert paths.samples_csv is None and paths.summary_csv is None
    assert list(destination.parent.iterdir()) == [destination]
    with pytest.raises(FrozenInstanceError):
        paths.json_path = tmp_path / "changed.json"


def test_typed_benchmark_report_uses_the_same_canonical_json_format(tmp_path):
    from runtime.benchmark_models import BenchmarkConfig, BenchmarkReport, BenchmarkSample
    from runtime.benchmark_statistics import compare_summaries, summarize
    from runtime.models import ExecutionResult

    class ValidationFixture:
        def to_dict(self):
            return {"result": {"outcome": "observed_equivalent"}, "environment_metadata": {"compiler": "synthetic"}}
    original, transformed = summarize((100, 200)), summarize((50, 100))
    sample = BenchmarkSample("measurement", 0, 0, "original", 100, ExecutionResult("success", process_returncode=0, return_value=257), True, True)
    typed = BenchmarkReport("typed-export-fixture", "valid", "Synthetic serialization fixture", BenchmarkConfig(repetitions=2), ValidationFixture(),
                            (sample,), (("original", original), ("transformed", transformed)), compare_summaries(original, transformed))
    paths = storage.save_report(typed, tmp_path / "typed.json")
    assert paths.json_path.read_text() == typed.to_json() + "\n"
    assert json.loads(paths.json_path.read_text()) == json.loads(typed.to_json())


def test_repeat_exports_have_identical_content_without_changing_report_data(report, tmp_path):
    snapshot = deepcopy(report.data)
    first = storage.save_report(report, tmp_path / "first.json", samples_csv=tmp_path / "first.csv", summary_csv=tmp_path / "first-summary.csv")
    second = storage.save_report(report, tmp_path / "second.json", samples_csv=tmp_path / "second.csv", summary_csv=tmp_path / "second-summary.csv")
    assert first.json_path.read_bytes() == second.json_path.read_bytes()
    assert first.samples_csv.read_bytes() == second.samples_csv.read_bytes()
    assert first.summary_csv.read_bytes() == second.summary_csv.read_bytes()
    assert report.data == snapshot


def test_empty_sample_and_group_exports_still_have_the_documented_headers(report, tmp_path):
    report.data["benchmark"]["samples"] = []
    report.data["benchmark"]["groups"] = {}
    paths = storage.save_report(report, tmp_path / "empty.json", samples_csv=tmp_path / "raw.csv", summary_csv=tmp_path / "summary.csv")
    assert paths.samples_csv.read_text().splitlines() == [",".join(storage.SAMPLE_COLUMNS)]
    assert paths.summary_csv.read_text().splitlines() == [",".join(storage.SUMMARY_COLUMNS)]
    assert storage.raw_rows(report) == storage.summary_rows(report) == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_values_cannot_write_nonstandard_json_or_touch_existing_exports(report, tmp_path, value):
    report.data["benchmark"]["samples"][1]["duration_ns"] = value
    existing = tmp_path / "report.json"
    existing.write_text("existing report")
    future = tmp_path / "not-created" / "raw.csv"
    with pytest.raises(ValueError):
        storage.save_report(report, existing, samples_csv=future)
    assert existing.read_text() == "existing report"
    assert not future.parent.exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_export_validates_every_path_before_reading_the_report_or_creating_directories(report, tmp_path):
    source = tmp_path / "source.c"
    source.write_text("int main(){return 0;}")
    destination = tmp_path / "not-created" / "report.json"
    with pytest.raises(ValueError, match="protected input"):
        storage.save_report(report, destination, samples_csv=source, protected_paths=(source,))
    assert report.calls == 0
    assert not destination.parent.exists()
    assert source.read_text() == "int main(){return 0;}"


@pytest.mark.parametrize("which", ["samples", "summary"])
def test_csv_and_json_cannot_share_the_same_destination(report, tmp_path, which):
    path = tmp_path / "report.json"
    options = {"samples_csv" if which == "samples" else "summary_csv": path}
    with pytest.raises(ValueError, match="alias"):
        storage.save_report(report, path, **options)
    assert not path.exists() and report.calls == 0


def test_public_preflight_accepts_generators_and_creates_nothing(tmp_path):
    requested = (str(tmp_path / "new" / name) for name in ("report.json", "raw.csv", "summary.csv"))
    result = storage.validate_output_paths(requested)
    assert result == tuple(tmp_path / "new" / name for name in ("report.json", "raw.csv", "summary.csv"))
    assert not (tmp_path / "new").exists()


def test_failed_replace_is_atomic_per_file_and_cleans_all_remaining_temps(report, tmp_path, monkeypatch):
    first, second = tmp_path / "report.json", tmp_path / "raw.csv"
    first.write_text("old json")
    second.write_text("old csv")
    actual_replace = storage.os.replace
    calls = 0
    def replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected replacement failure")
        return actual_replace(source, destination)
    monkeypatch.setattr(storage.os, "replace", replace)
    with pytest.raises(OSError, match="replacement failure"):
        storage.save_report(report, first, samples_csv=second)
    assert json.loads(first.read_text()) == report.data
    assert second.read_text() == "old csv"
    assert not list(tmp_path.glob(".*.tmp"))


def test_failed_fsync_leaves_the_previous_output_complete_and_cleans_temps(report, tmp_path, monkeypatch):
    output = tmp_path / "report.json"
    output.write_text("previous report")
    def fail(descriptor):
        raise OSError("injected flush failure")
    monkeypatch.setattr(storage.os, "fsync", fail)
    with pytest.raises(OSError, match="flush failure"):
        storage.save_report(report, output)
    assert output.read_text() == "previous report"
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("path", ["", ".", "/"])
def test_export_destinations_require_filenames(path):
    with pytest.raises(ValueError, match="filename"):
        storage._preflight_paths((path,))


def test_preflight_rejects_directories_before_creating_other_output_parents(tmp_path):
    directory = tmp_path / "existing-directory"
    directory.mkdir()
    first = tmp_path / "not-created" / "report.json"
    with pytest.raises(ValueError, match="regular file"):
        storage._preflight_paths((first, directory))
    assert not first.parent.exists()


@pytest.mark.parametrize("alias", ["direct", "hardlink", "symlink"])
def test_protected_sources_cannot_be_export_destinations_through_aliases(tmp_path, alias):
    source = tmp_path / "source.c"
    source.write_text("int main(){return 257;}\n")
    destination = source if alias == "direct" else tmp_path / "report.json"
    if alias == "hardlink":
        destination.hardlink_to(source)
    elif alias == "symlink":
        destination.symlink_to(source)
    with pytest.raises(ValueError, match="protected input|symlinks"):
        storage._preflight_paths((destination,), (source,))
    assert source.read_text() == "int main(){return 257;}\n"


def test_a_symlink_used_as_the_protected_input_still_protects_its_target(tmp_path):
    source = tmp_path / "source.c"
    source.write_text("source stays intact")
    alias = tmp_path / "source-alias.c"
    alias.symlink_to(source)
    with pytest.raises(ValueError, match="protected input"):
        storage._preflight_paths((source,), (alias,))
    assert source.read_text() == "source stays intact"


@pytest.mark.parametrize("target_exists", [False, True])
def test_output_symlinks_are_rejected_even_without_a_protected_input(tmp_path, target_exists):
    outside = tmp_path / "outside.json"
    if target_exists:
        outside.write_text("outside")
    destination = tmp_path / "report.json"
    destination.symlink_to(outside)
    with pytest.raises(ValueError, match="symlinks"):
        storage._preflight_paths((destination,))
    assert outside.read_text() == "outside" if target_exists else not outside.exists()


def test_missing_paths_are_compared_after_parent_symlink_resolution(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="alias"):
        storage._preflight_paths((real / "report.json", alias / "report.json"))
    assert list(real.iterdir()) == []


def test_existing_output_hardlinks_cannot_represent_different_exports(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.csv"
    first.write_text("existing")
    second.hardlink_to(first)
    with pytest.raises(ValueError, match="alias"):
        storage._preflight_paths((first, second))
    assert first.read_text() == second.read_text() == "existing"


def test_parent_child_output_collisions_are_rejected_before_creating_directories(tmp_path):
    parent = tmp_path / "report.json"
    with pytest.raises(ValueError, match="contain another"):
        storage._preflight_paths((parent, parent / "samples.csv"))
    assert not parent.exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO safety check requires POSIX")
def test_special_file_destinations_are_rejected_without_blocking(tmp_path):
    destination = tmp_path / "report.fifo"
    os.mkfifo(destination)
    with pytest.raises(ValueError, match="special file"):
        storage._preflight_paths((destination,))
    assert destination.exists()


def test_existing_plain_outputs_can_be_atomically_replaced(tmp_path):
    output = tmp_path / "report.json"
    output.write_text("old")
    paths = storage._preflight_paths((output,))
    storage._atomic_write(((paths[0], "new\n"),))
    assert output.read_text() == "new\n"
    assert list(tmp_path.iterdir()) == [output]


def test_failed_preparation_preserves_all_original_outputs_and_removes_temps(tmp_path, monkeypatch):
    first, second = tmp_path / "first.json", tmp_path / "second.csv"
    first.write_text("first original")
    second.write_text("second original")
    actual_create = storage.NamedTemporaryFile
    calls = 0
    def create(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected preparation failure")
        return actual_create(**kwargs)
    monkeypatch.setattr(storage, "NamedTemporaryFile", create)
    with pytest.raises(OSError, match="preparation failure"):
        storage._atomic_write(((first, "first new"), (second, "second new")))
    assert first.read_text() == "first original"
    assert second.read_text() == "second original"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["first.json", "second.csv"]


def test_each_replacement_sees_a_complete_prepared_file_for_every_export(tmp_path, monkeypatch):
    outputs = (tmp_path / "report.json", tmp_path / "samples.csv", tmp_path / "summary.csv")
    actual_replace = storage.os.replace
    observations = []
    def replace(source, destination):
        if not observations:
            observations.append(sorted(path.read_text() for path in tmp_path.glob(".*.tmp")))
        return actual_replace(source, destination)
    monkeypatch.setattr(storage.os, "replace", replace)
    storage._atomic_write(zip(outputs, ("complete json", "complete samples", "complete summary")))
    assert observations == [["complete json", "complete samples", "complete summary"]]
    assert [path.read_text() for path in outputs] == ["complete json", "complete samples", "complete summary"]
    assert not list(tmp_path.glob(".*.tmp"))

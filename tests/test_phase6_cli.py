"""Report-only Phase 6 integration using authentic saved Phase 5 observations."""

import csv
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from fingerprint.extraction import extract_fingerprint
from fingerprint.matrix import build_matrix
from fingerprint.storage import COMPARISON_COLUMNS, FEATURE_COLUMNS, save_document


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "examples" / "observations" / "phase5"


def cli(*arguments, cwd=ROOT):
    return subprocess.run([sys.executable, "-m", "compiler", *map(str, arguments)],
                          cwd=cwd, capture_output=True, text=True, timeout=30)


def imported(name="constants-O0"):
    return ["--benchmark-report", REPORTS / f"{name}.json"]


@pytest.fixture
def saved(tmp_path):
    reports = [json.loads((REPORTS / f"constants-{optimization}.json").read_text()) for optimization in ("O0", "O2")]
    matrix = build_matrix(reports)
    matrix_path = tmp_path / "matrix.json"
    save_document(matrix, matrix_path)
    fingerprints = []
    for index, configuration in enumerate(matrix.to_dict()["configurations"]):
        fingerprint = extract_fingerprint(matrix, configuration_id=configuration["id"])
        path = tmp_path / f"fingerprint-{index}.json"
        save_document(fingerprint, path)
        fingerprints.append(path)
    return matrix, matrix_path, fingerprints


def test_matrix_cli_imports_real_observations_without_c_source_or_compilation():
    completed = cli("--matrix", *imported(), *imported("unroll-O0"), *imported("rejected"))
    assert completed.returncode == 0, completed.stderr
    data = json.loads(completed.stdout)
    assert data["kind"] == "codedna.response_matrix"
    assert len(data["observations"]) == 3
    assert {observation["provenance"]["report"]["benchmark"]["status"] for observation in data["observations"]} == {"completed", "no_transformation"}
    assert completed.stderr == ""


def test_matrix_json_and_long_csv_export_preserve_identifiers_and_unreliable_values(tmp_path):
    output = tmp_path / "new" / "matrix.json"
    completed = cli("--matrix", *imported(), "--csv", "--output", output)
    assert completed.returncode == 0, completed.stderr
    assert f"Saved {output}" in completed.stdout
    assert f"Saved {output.with_suffix('.csv')}" in completed.stdout
    assert '"observations"' not in completed.stdout
    data = json.loads(output.read_text())
    with output.with_suffix(".csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == list(FEATURE_COLUMNS)
    assert all(row["artifact_id"] == data["matrix_id"] for row in rows)
    assert any(row["group"] == "performance" and row["reliability"] == "unreliable" for row in rows)
    assert any(row["value"] == "" for row in rows)
    assert "missing values" in completed.stdout
    assert f"Configuration {data['configurations'][0]['id']}: opt=O0;" in completed.stdout
    assert "Apple clang version" in completed.stdout


def test_fingerprint_cli_can_use_benchmark_reports_directly_and_inspect_without_corrupting_json():
    completed = cli("--fingerprint", *imported(), "--inspect-features")
    assert completed.returncode == 0, completed.stderr
    data = json.loads(completed.stdout)
    assert data["kind"] == "codedna.fingerprint"
    assert len(data["configurations"]) == 1
    assert "validity=" in completed.stderr and "reliability=unreliable" in completed.stderr


def test_fingerprint_cli_requires_explicit_configuration_for_mixed_matrix(saved):
    _, matrix_path, _ = saved
    completed = cli("--fingerprint", matrix_path)
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "configuration" in completed.stderr.lower()
    assert "Traceback" not in completed.stderr


def test_configuration_and_source_pipeline_filters_retain_only_selected_observation(saved):
    matrix, matrix_path, _ = saved
    observation = matrix.to_dict()["observations"][0]
    completed = cli("--fingerprint", matrix_path, "--configuration", observation["configuration_id"],
                    "--source-id", observation["source_id"], "--pipeline-id", observation["pipeline_id"],
                    "--observation-id", observation["id"])
    assert completed.returncode == 0, completed.stderr
    data = json.loads(completed.stdout)
    assert [item["id"] for item in data["observations"]] == [observation["id"]]


def test_comparison_cli_self_comparison_scores_valid_evidence_and_excludes_noisy_performance(saved):
    _, _, fingerprints = saved
    completed = cli("--compare-fingerprints", fingerprints[0], "--against", fingerprints[0])
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "comparable"
    assert result["distance"] == 0 and result["similarity"] == 1
    assert result["usable_dimensions"] >= 2
    assert any(dimension["group"] == "performance" and not dimension["usable"] and dimension["reasons"]
               for dimension in result["dimensions"])


def test_explicit_configuration_alignment_compares_o0_o2_without_claiming_different_compilers(saved):
    _, _, fingerprints = saved
    strict = cli("--compare-fingerprints", fingerprints[0], "--against", fingerprints[1])
    assert strict.returncode == 6
    assert json.loads(strict.stdout)["status"] == "incompatible"
    completed = cli("--compare-fingerprints", fingerprints[0], "--against", fingerprints[1], "--alignment", "configuration")
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "comparable" and result["usable_dimensions"] >= 2
    assert result["alignment"] == "configuration"


def test_insufficient_performance_evidence_exports_null_score_and_exit_six(tmp_path, saved):
    _, _, fingerprints = saved
    output = tmp_path / "comparison.json"
    completed = cli("--compare-fingerprints", fingerprints[0], "--against", fingerprints[0],
                    "--feature-group", "performance", "--inspect-features", "--output", output, "--csv")
    assert completed.returncode == 6, completed.stderr
    data = json.loads(output.read_text())
    assert data["status"] == "insufficient_evidence"
    assert data["distance"] is None and data["similarity"] is None and data["usable_dimensions"] == 0
    assert "excluded" in completed.stdout and "similarity unavailable" in completed.stdout
    assert "left=" in completed.stdout and "right=" in completed.stdout
    assert "unit=" in completed.stdout and "difference=unavailable" in completed.stdout
    with output.with_suffix(".csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == list(COMPARISON_COLUMNS)
    assert rows and all(row["similarity"] == "" and row["distance"] == "" for row in rows)


@pytest.mark.parametrize("arguments", [
    ("--matrix",), ("--fingerprint",), ("--compare-fingerprints",),
    ("--matrix", "--benchmark-report", "input.json", "extra.json"),
    ("--matrix", "--benchmark-report", "input.json", "--against", "other.json"),
    ("--fingerprint", "input.json", "--benchmark-report", "other.json"),
    ("--matrix", "--benchmark-report", "input.json", "--csv"),
    ("--matrix", "--benchmark-report", "input.json", "--transform", "constants"),
    ("--matrix", "--benchmark-report", "input.json", "--opt", "O2"),
    ("--matrix", "--benchmark-report", "input.json", "--no-sanitize"),
    ("--matrix", "--benchmark-report", "input.json", "--warmups", "0"),
    ("--matrix", "--benchmark-report", "input.json", "--format", "dot"),
    ("--matrix", "--benchmark-report", "input.json", "--configuration", "config"),
    ("--fingerprint", "input.json", "--feature-group", "structural"),
    ("--fingerprint", "input.json", "--alignment", "program"),
    ("--ast", "--configuration", "config", "input.c"),
    ("--ast", "--benchmark-report", "input.json", "input.c"),
    ("--ast", "--inspect-features", "input.c"),
    ("--ast",),
])
def test_invalid_or_wrong_mode_options_fail_usefully_without_traceback(arguments):
    completed = cli(*arguments)
    assert completed.returncode == 2
    assert completed.stderr and "Traceback" not in completed.stderr
    assert completed.stdout == ""


@pytest.mark.parametrize("weight", ["missingequals", "=2", "feature=nan", "feature=inf", "feature=0", "feature=-1"])
def test_invalid_comparison_weights_are_rejected(saved, weight):
    _, _, fingerprints = saved
    completed = cli("--compare-fingerprints", fingerprints[0], "--against", fingerprints[0], "--weight", weight)
    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr


def test_invalid_json_files_and_document_kinds_are_not_silently_treated_as_c(tmp_path, saved):
    _, matrix_path, _ = saved
    broken = tmp_path / "broken.json"
    broken.write_text('{"schema_version":1,"schema_version":1}')
    completed = cli("--fingerprint", broken)
    assert completed.returncode == 2 and "Duplicate JSON key" in completed.stderr
    completed = cli("--compare-fingerprints", matrix_path, "--against", matrix_path)
    assert completed.returncode == 2 and "fingerprint documents" in completed.stderr


@pytest.mark.parametrize("destination", ["json", "csv"])
@pytest.mark.parametrize("alias", ["direct", "hardlink", "symlink_parent"])
def test_exports_protect_every_benchmark_input_and_csv_sidecar(tmp_path, destination, alias):
    first = tmp_path / "first.json"
    first.write_bytes((REPORTS / "constants-O0.json").read_bytes())
    second = tmp_path / ("second.csv" if destination == "csv" else "second.json")
    second.write_bytes((REPORTS / "unroll-O0.json").read_bytes())
    target = second
    if alias == "hardlink":
        target = tmp_path / ("alias.csv" if destination == "csv" else "alias.json")
        os.link(second, target)
    elif alias == "symlink_parent":
        folder = tmp_path / "directory-alias"
        folder.symlink_to(tmp_path, target_is_directory=True)
        target = folder / second.name
    # JSON must remain a distinct path so the CSV check itself protects input.
    if destination == "csv":
        output = target.with_suffix(".json")
    else:
        output = target
    before = second.read_bytes()
    completed = cli("--matrix", "--benchmark-report", first, "--benchmark-report", second,
                    "--output", output, *( ["--csv"] if destination == "csv" else []))
    assert completed.returncode == 2
    assert second.read_bytes() == before and first.exists()
    assert "Traceback" not in completed.stderr


def test_comparison_output_protects_the_right_input_as_well_as_left(saved):
    _, _, fingerprints = saved
    before = fingerprints[1].read_bytes()
    completed = cli("--compare-fingerprints", fingerprints[0], "--against", fingerprints[1], "--output", fingerprints[1])
    assert completed.returncode == 2 and fingerprints[1].read_bytes() == before


def test_report_commands_never_invoke_existing_compiler_or_benchmark(monkeypatch, capsys):
    from compiler import __main__
    def forbidden(*args, **kwargs):
        raise AssertionError("Phase 6 must consume saved reports without executing Clang")
    monkeypatch.setattr(__main__, "benchmark", forbidden)
    monkeypatch.setattr(__main__, "check_equivalence", forbidden)
    monkeypatch.setattr(__main__, "evaluate_source", forbidden)
    assert __main__.main(["--matrix", *map(str, imported())]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "codedna.response_matrix"

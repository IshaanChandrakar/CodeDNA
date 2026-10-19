"""Lossless Phase 6 interchange and safe exports over genuine saved evidence."""

from copy import deepcopy
import csv
import json
import os
from pathlib import Path

import pytest

from fingerprint import storage
from fingerprint.extraction import extract_fingerprint
from fingerprint.matrix import build_matrix
from fingerprint.models import Fingerprint, ResponseMatrix
from fingerprint.similarity import compare


REPORTS = Path(__file__).resolve().parents[1] / "examples" / "observations" / "phase5"


@pytest.fixture
def matrix():
    return build_matrix([json.loads((REPORTS / "constants-O0.json").read_text())])


@pytest.fixture
def fingerprint(matrix):
    return extract_fingerprint(matrix)


def test_json_round_trip_preserves_real_sources_provenance_and_noisy_measurements(tmp_path, matrix):
    path = tmp_path / "matrix.json"
    exports = storage.save_document(matrix, path)
    restored = storage.load_document(exports.json_path)
    assert isinstance(restored, ResponseMatrix)
    assert restored.to_dict() == matrix.to_dict()
    observation = restored.to_dict()["observations"][0]
    assert observation["provenance"]["report"]["benchmark"]["comparison"]["status"] == "unreliable"
    assert observation["provenance"]["report"]["analysis"]["original"]["execution"]["return_value"] == 257


@pytest.mark.parametrize("kind", ["matrix", "fingerprint", "comparison"])
def test_all_document_kinds_round_trip_and_exports_repeat_identically(tmp_path, matrix, fingerprint, kind):
    document = {"matrix": matrix, "fingerprint": fingerprint, "comparison": compare(fingerprint, fingerprint)}[kind]
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    storage.save_document(document, first, csv_path=first.with_suffix(".csv"))
    storage.save_document(document, second, csv_path=second.with_suffix(".csv"))
    assert first.read_bytes() == second.read_bytes()
    assert first.with_suffix(".csv").read_bytes() == second.with_suffix(".csv").read_bytes()
    assert storage.load_document(first).to_dict() == document.to_dict()


def test_feature_csv_has_explicit_units_markers_and_machine_readable_provenance(tmp_path, matrix):
    path = tmp_path / "features.csv"
    storage.save_document(matrix, tmp_path / "matrix.json", csv_path=path)
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == list(storage.FEATURE_COLUMNS)
    typed = storage.feature_rows(matrix)
    assert len(rows) == len(typed) > 0
    for actual, expected in zip(rows, typed):
        assert actual["observation_id"] == expected["observation_id"]
        assert actual["feature"] == expected["feature"]
        assert actual["unit"] == expected["unit"]
        assert json.loads(actual["reasons"]) == expected["reasons"]
        assert json.loads(actual["provenance"]) == expected["provenance"]
        if expected["value"] is None:
            assert actual["value"] == ""
        elif expected["value"] == 0:
            assert actual["value"] == "0" or actual["value"] == "0.0"
    assert any(row["group"] == "performance" and row["reliability"] == "unreliable" for row in rows)


def test_rows_retain_missing_values_real_zero_and_original_document_immutability(matrix):
    snapshot = matrix.to_dict()
    rows = storage.feature_rows(matrix)
    assert any(row["value"] is None for row in rows)
    assert any(type(row["value"]) in (int, float) and row["value"] == 0 for row in rows)
    assert all(tuple(row) == storage.FEATURE_COLUMNS for row in rows)
    rows[0]["value"] = "changed detached row"
    assert matrix.to_dict() == snapshot


def test_fingerprint_rows_use_fingerprint_identity_instead_of_parent_matrix_identity(fingerprint):
    data = fingerprint.to_dict()
    assert data["fingerprint_id"] != data["matrix_id"]
    assert all(row["artifact_id"] == data["fingerprint_id"] for row in storage.feature_rows(fingerprint))


def test_comparison_csv_preserves_used_and_excluded_dimensions_without_scoring_noise(tmp_path, fingerprint):
    comparison = compare(fingerprint, fingerprint)
    path = tmp_path / "comparison.csv"
    storage.save_document(comparison, tmp_path / "comparison.json", csv_path=path)
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == list(storage.COMPARISON_COLUMNS)
    dimensions = [row for row in rows if row["row_type"] == "dimension"]
    assert any(row["usable"] == "true" and float(row["contribution"]) == 0 for row in dimensions)
    excluded = [row for row in dimensions if row["usable"] == "false"]
    assert excluded
    assert all(row["contribution"] == "" for row in excluded)
    assert any(row["group"] == "performance" and json.loads(row["reasons"]) for row in excluded)


@pytest.mark.parametrize("text", [
    '{"schema_version":1,"schema_version":1}',
    '{"schema_version":1,"kind":"codedna.fingerprint","value":NaN}',
    '{"schema_version":1,"kind":"codedna.fingerprint","value":1e999}',
    '{"schema_version":2,"kind":"codedna.fingerprint"}',
    '{"schema_version":1,"kind":"unknown"}',
    '[]', '{broken',
])
def test_invalid_or_ambiguous_json_is_rejected_without_fallback(tmp_path, text):
    path = tmp_path / "invalid.json"
    path.write_text(text)
    with pytest.raises(ValueError):
        storage.load_document(path)


def test_unknown_feature_schema_is_preserved_for_explicit_incompatible_comparison(tmp_path, fingerprint):
    data = fingerprint.to_dict()
    data["feature_schema"] = "unsupported.features.v99"
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps(data))
    restored = storage.load_document(path)
    assert restored.to_dict()["feature_schema"] == "unsupported.features.v99"
    assert compare(fingerprint, restored).to_dict()["status"] == "incompatible"


@pytest.mark.parametrize("alias", ["same", "hardlink", "symlink"])
def test_input_aliases_are_protected_before_any_exports_are_created(tmp_path, matrix, alias):
    source = tmp_path / "input.json"
    source.write_text("protected original")
    destination = source if alias == "same" else tmp_path / "alias.json"
    if alias == "hardlink":
        os.link(source, destination)
    elif alias == "symlink":
        destination.symlink_to(source)
    sidecar = tmp_path / "new" / "features.csv"
    with pytest.raises(ValueError):
        storage.save_document(matrix, destination, csv_path=sidecar, protected_paths=[source])
    assert source.read_text() == "protected original"
    assert not sidecar.parent.exists()


def test_csv_cannot_overwrite_any_protected_input_or_alias_json(tmp_path, matrix):
    source = tmp_path / "source.csv"
    source.write_text("preserved")
    output = tmp_path / "new" / "result.json"
    with pytest.raises(ValueError):
        storage.save_document(matrix, output, csv_path=source, protected_paths=[source])
    assert not output.parent.exists()
    with pytest.raises(ValueError):
        storage.save_document(matrix, output, csv_path=output)
    assert not output.parent.exists()


def test_output_parent_symlink_alias_cannot_redirect_onto_protected_input(tmp_path, matrix):
    actual = tmp_path / "actual"
    actual.mkdir()
    protected = actual / "input.json"
    protected.write_text("preserved")
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError):
        storage.save_document(matrix, alias / "input.json", protected_paths=[protected])
    assert protected.read_text() == "preserved"


@pytest.mark.parametrize("shape", ["directory", "empty", "parent_file", "parent_child"])
def test_invalid_output_shapes_are_preflighted_without_partial_files(tmp_path, matrix, shape):
    output = tmp_path / "new" / "matrix.json"
    sidecar = None
    if shape == "directory":
        output = tmp_path
    elif shape == "empty":
        output = ""
    elif shape == "parent_file":
        tmp_path.joinpath("new").write_text("parent is a file")
    else:
        sidecar = output / "child.csv"
    with pytest.raises((ValueError, OSError)):
        storage.save_document(matrix, output, csv_path=sidecar)
    assert not (tmp_path / "new" / "matrix.json").exists()


def test_existing_regular_outputs_can_be_replaced(tmp_path, fingerprint):
    path = tmp_path / "fingerprint.json"
    path.write_text("old")
    storage.save_document(fingerprint, path)
    assert isinstance(storage.load_document(path), Fingerprint)


def test_prepare_failure_preserves_all_existing_outputs_and_cleans_temporaries(tmp_path, matrix, monkeypatch):
    output, sidecar = tmp_path / "matrix.json", tmp_path / "matrix.csv"
    output.write_text("original JSON")
    sidecar.write_text("original CSV")
    calls = 0
    real_fsync = storage.os.fsync
    def fail_second(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("controlled second-file preparation failure")
        real_fsync(descriptor)
    monkeypatch.setattr(storage.os, "fsync", fail_second)
    with pytest.raises(OSError, match="preparation failure"):
        storage.save_document(matrix, output, csv_path=sidecar)
    assert output.read_text() == "original JSON"
    assert sidecar.read_text() == "original CSV"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["matrix.csv", "matrix.json"]


def test_nonfinite_document_is_rejected_before_parent_creation(tmp_path, matrix):
    data = deepcopy(matrix.to_dict())
    data["observations"][0]["features"][0]["value"] = float("inf")
    output = tmp_path / "not-created" / "matrix.json"
    with pytest.raises(ValueError):
        storage.save_document(data, output)
    assert not output.parent.exists()

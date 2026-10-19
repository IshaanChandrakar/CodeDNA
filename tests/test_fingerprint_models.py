"""Saved reports must fail clearly instead of loading broken references/values."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from fingerprint.extraction import extract_fingerprint
from fingerprint.matrix import build_matrix
from fingerprint.models import ComparisonResult, Fingerprint, ResponseMatrix, strict_loads
from fingerprint.similarity import compare


@pytest.fixture
def matrix():
    report = Path(__file__).resolve().parents[1] / "examples/observations/phase5/constants-O0.json"
    return build_matrix([json.loads(report.read_text())])


@pytest.mark.parametrize("mutation", [
    lambda d: d.pop("matrix_id"),
    lambda d: d.update(schema_version=True),
    lambda d: d.update(feature_definitions={}),
    lambda d: d["sources"].append(deepcopy(d["sources"][0])),
    lambda d: d["observations"][0].update(source_id="unknown"),
    lambda d: d["observations"][0].update(source_id=[]),
    lambda d: d["observations"][0].pop("benchmark_id"),
    lambda d: d["observations"][0].update(provenance={}),
    lambda d: d["observations"][0]["features"].append(deepcopy(d["observations"][0]["features"][0])),
    lambda d: d["observations"][0]["features"][0].update(name=[]),
    lambda d: d["observations"][0]["features"][0].update(validity="invented"),
    lambda d: d["observations"][0]["features"][0].update(reliability="proven"),
    lambda d: d["observations"][0]["features"][0].update(reasons="not a list"),
    lambda d: d["observations"][0]["features"][0].update(provenance={}),
    lambda d: d["observations"][0]["features"][0].update(value=None, validity="valid"),
])
def test_signature_schema_rejects_broken_saved_interfaces(matrix, mutation):
    data = matrix.to_dict()
    mutation(data)
    with pytest.raises(ValueError):
        ResponseMatrix(data)


@pytest.mark.parametrize("value", [True, "12", float("inf"), float("nan")])
def test_numeric_features_cannot_silently_coerce_invalid_values(matrix, value):
    data = matrix.to_dict()
    feature = next(item for item in data["observations"][0]["features"] if item["name"] == "tac.original.operations")
    feature["value"] = value
    with pytest.raises(ValueError):
        ResponseMatrix(data)


def test_fingerprint_record_refuses_mixed_configuration_even_after_manual_json_edit(matrix):
    data = extract_fingerprint(matrix).to_dict()
    data["configurations"].append({"id": "different", "identity": {}})
    with pytest.raises(ValueError):
        Fingerprint(data)


@pytest.mark.parametrize("mutation", [
    lambda d: d.pop("comparison_id"),
    lambda d: d.pop("inputs"),
    lambda d: d.update(status="proved_equivalent"),
    lambda d: d.update(usable_dimensions=True),
    lambda d: d.update(requested_dimensions=999),
    lambda d: d.update(distance=None),
    lambda d: d.update(similarity=1.1),
    lambda d: d.update(coverage=None),
    lambda d: d.update(status="insufficient_evidence"),
    lambda d: d["dimensions"][0].pop("feature"),
    lambda d: d["dimensions"][0].update(contribution=float("inf")),
    lambda d: d.update(excluded_observations=[{}]),
])
def test_comparison_round_trip_rejects_broken_counts_and_invented_scores(matrix, mutation):
    fingerprint = extract_fingerprint(matrix)
    data = compare(fingerprint, fingerprint).to_dict()
    mutation(data)
    with pytest.raises(ValueError):
        ComparisonResult(data)


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}', 'null'])
def test_strict_json_rejects_ambiguous_or_nonfinite_documents(text):
    with pytest.raises(ValueError):
        strict_loads(text)

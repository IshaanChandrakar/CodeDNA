"""Configuration-isolated fingerprint extraction from authentic saved evidence."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from fingerprint.extraction import extract_fingerprint
from fingerprint.matrix import build_matrix
from fingerprint.models import Fingerprint


FIXTURES = Path(__file__).resolve().parents[1] / "examples/observations/phase5"


def saved(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def configuration(matrix, optimization):
    return next(entry["id"] for entry in matrix.to_dict()["configurations"] if entry["identity"]["settings"]["optimization"] == optimization)


def features(observation):
    return {feature["name"]: feature for feature in observation["features"]}


def test_one_configuration_is_selected_automatically_and_preserves_all_evidence():
    report = saved("constants-O0")
    matrix = build_matrix([report])
    fingerprint = extract_fingerprint(matrix)
    data = fingerprint.to_dict()
    original = matrix.to_dict()
    assert data["schema_version"] == 1 and data["kind"] == "codedna.fingerprint"
    assert data["feature_schema"] == original["feature_schema"]
    assert len(data["configurations"]) == len(data["observations"]) == 1
    for axis in ("sources", "pipelines", "configurations", "observations", "feature_definitions"):
        assert data[axis] == original[axis]
    assert data["matrix_id"] == original["matrix_id"]
    assert data["observations"][0]["provenance"]["report"] == report
    assert json.loads(fingerprint.to_json()) == data
    assert Fingerprint.from_json(fingerprint.to_json()).to_dict() == data


def test_no_observations_cannot_be_extracted_as_a_fingerprint():
    with pytest.raises(ValueError):
        extract_fingerprint(build_matrix([]))


def test_optimization_settings_cannot_be_silently_mixed_in_one_fingerprint():
    matrix = build_matrix([saved("constants-O0"), saved("constants-O2")])
    assert len(matrix.to_dict()["configurations"]) == 2
    with pytest.raises(ValueError):
        extract_fingerprint(matrix)
    for optimization in ("O0", "O2"):
        selected = configuration(matrix, optimization)
        fingerprint = extract_fingerprint(matrix, configuration_id=selected).to_dict()
        assert [entry["id"] for entry in fingerprint["configurations"]] == [selected]
        assert len(fingerprint["observations"]) == 1
        assert fingerprint["configurations"][0]["identity"]["settings"]["optimization"] == optimization


def test_sources_and_pipelines_can_share_a_configuration_without_fabricating_combinations():
    matrix = build_matrix([saved("constants-O0"), saved("unroll-O0"), saved("combined-O0")])
    data = extract_fingerprint(matrix).to_dict()
    assert len(data["configurations"]) == 1
    assert len(data["sources"]) == len(data["pipelines"]) == len(data["observations"]) == 3
    assert len(data["observations"]) != len(data["sources"]) * len(data["pipelines"])
    assert len({entry["id"] for entry in data["observations"]}) == 3


@pytest.mark.parametrize("filter_name,axis,observation_field", [
    ("source_ids", "sources", "source_id"),
    ("pipeline_ids", "pipelines", "pipeline_id"),
    ("observation_ids", "observations", "id"),
])
def test_each_filter_retains_only_referenced_axes_and_complete_matching_observations(filter_name, axis, observation_field):
    matrix = build_matrix([saved("constants-O0"), saved("unroll-O0"), saved("combined-O0")])
    original = matrix.to_dict()
    chosen = original[axis][0]["id"]
    expected = [entry for entry in original["observations"] if entry[observation_field] == chosen]
    data = extract_fingerprint(matrix, **{filter_name: [chosen]}).to_dict()
    assert data["observations"] == expected and len(expected) == 1
    for retained_axis, field in (("sources", "source_id"), ("pipelines", "pipeline_id"), ("configurations", "configuration_id")):
        assert {entry["id"] for entry in data[retained_axis]} == {entry[field] for entry in expected}


def test_selecting_an_observation_can_resolve_an_ambiguous_configuration():
    matrix = build_matrix([saved("constants-O0"), saved("constants-O2")])
    observation = matrix.to_dict()["observations"][0]
    data = extract_fingerprint(matrix, observation_ids=[observation["id"]]).to_dict()
    assert len(data["configurations"]) == 1
    assert data["configurations"][0]["id"] == observation["configuration_id"]


@pytest.mark.parametrize("filter_name", ["source_ids", "pipeline_ids", "observation_ids"])
def test_unknown_filter_identifiers_are_reported_instead_of_creating_empty_features(filter_name):
    matrix = build_matrix([saved("constants-O0")])
    with pytest.raises(ValueError):
        extract_fingerprint(matrix, **{filter_name: ["unknown-id"]})


def test_unknown_configuration_is_rejected():
    with pytest.raises(ValueError):
        extract_fingerprint(build_matrix([saved("constants-O0")]), configuration_id="unknown-config")


@pytest.mark.parametrize("filter_name", ["source_ids", "pipeline_ids", "observation_ids"])
def test_explicit_empty_selections_cannot_produce_a_scored_empty_fingerprint(filter_name):
    with pytest.raises(ValueError):
        extract_fingerprint(build_matrix([saved("constants-O0")]), **{filter_name: []})


def test_existing_but_disjoint_observation_and_configuration_selections_fail_clearly():
    matrix = build_matrix([saved("constants-O0"), saved("constants-O2")])
    first, second = matrix.to_dict()["observations"]
    assert first["configuration_id"] != second["configuration_id"]
    with pytest.raises(ValueError):
        extract_fingerprint(matrix, configuration_id=first["configuration_id"], observation_ids=[second["id"]])


def test_repeated_experiments_keep_separate_evidence_and_are_never_averaged():
    first = saved("constants-O0")
    repeated = deepcopy(first)
    repeated["benchmark_id"] = "another-run"
    matrix = build_matrix([first, repeated])
    data = extract_fingerprint(matrix).to_dict()
    assert len(data["observations"]) == 2
    assert {entry["benchmark_id"] for entry in data["observations"]} == {first["benchmark_id"], "another-run"}
    for observation in data["observations"]:
        assert features(observation)["performance.median_ratio"]["value"] == first["benchmark"]["comparison"]["speedup"]


@pytest.mark.parametrize("name", ["constants-O0", "unroll-O0", "combined-O0", "negative"])
def test_unreliable_performance_values_and_reasons_survive_extraction(name):
    report = saved(name)
    data = extract_fingerprint(build_matrix([report])).to_dict()
    observation = data["observations"][0]
    extracted = features(observation)
    ratio = extracted["performance.median_ratio"]
    assert ratio["value"] == report["benchmark"]["comparison"]["speedup"]
    assert ratio["validity"] == "valid" and ratio["reliability"] == "unreliable"
    assert "process_startup_scope" in ratio["reasons"]
    assert extracted["tac.original.operations"]["reliability"] == "deterministic"
    hardware = extracted["performance.hardware_instructions"]
    assert hardware["value"] is None and hardware["reliability"] == "unavailable"
    assert hardware["reasons"]


def test_extraction_cannot_promote_tampered_reliability_into_valid_evidence():
    report = saved("constants-O0")
    report["benchmark"]["comparison"].update(status="available", issues=[])
    data = extract_fingerprint(build_matrix([report])).to_dict()
    ratio = features(data["observations"][0])["performance.median_ratio"]
    assert ratio["value"] == report["benchmark"]["comparison"]["speedup"]
    assert ratio["validity"] == "invalid"
    assert "inconsistent_reliability_or_ratio" in ratio["reasons"]


@pytest.mark.parametrize("name,expected", [
    ("rejected", "no_transformation"), ("inapplicable", "no_transformation"),
    ("undefined", "undefined_behavior"), ("inconclusive", "inconclusive"),
    ("timeout", "timeout"), ("mismatch", "different_behavior"),
])
def test_failed_or_unaccepted_evidence_can_be_described_without_a_performance_vector(name, expected):
    data = extract_fingerprint(build_matrix([saved(name)])).to_dict()
    extracted = features(data["observations"][0])
    assert extracted["compiler.equivalence"]["value"] == expected
    assert extracted["performance.median_ratio"]["value"] is None
    assert extracted["performance.median_ratio"]["validity"] != "valid"
    assert extracted["performance.median_ratio"]["reasons"]


def test_feature_definitions_separate_structural_compiler_and_performance_units():
    definitions = extract_fingerprint(build_matrix([saved("constants-O0")])).to_dict()["feature_definitions"]
    by_name = {definition["name"]: definition for definition in definitions}
    assert by_name["tac.original.operations"]["group"] == "structural"
    assert by_name["tac.original.operations"]["unit"] == "tac_operations"
    assert by_name["pipeline.status"]["kind"] == "categorical"
    assert by_name["compiler.equivalence"]["group"] == "compiler"
    assert by_name["performance.median_ratio"]["group"] == "performance"
    assert by_name["performance.median_ratio"]["unit"] == "ratio"
    assert by_name["performance.original.median_ns"]["unit"] == "ns"
    assert by_name["performance.hardware_instructions"]["unit"] == "hardware_instructions"


def test_reversed_inputs_and_filter_order_produce_identical_fingerprints():
    reports = [saved("constants-O0"), saved("unroll-O0"), saved("combined-O0")]
    first_matrix, second_matrix = build_matrix(reports), build_matrix(reversed(reports))
    ids = [entry["id"] for entry in first_matrix.to_dict()["observations"]]
    first = extract_fingerprint(first_matrix, observation_ids=ids)
    second = extract_fingerprint(second_matrix, observation_ids=reversed(ids))
    assert first.to_dict() == second.to_dict()
    assert first.to_json() == second.to_json()


def test_exported_fingerprint_mutations_cannot_change_evidence_or_parent_matrix():
    matrix = build_matrix([saved("constants-O0")])
    matrix_snapshot = matrix.to_json()
    fingerprint = extract_fingerprint(matrix)
    original = fingerprint.to_json()
    exported = fingerprint.to_dict()
    exported["observations"][0]["provenance"]["report"]["analysis"]["source"]["name"] = "changed"
    exported["configurations"][0]["identity"]["settings"]["optimization"] = "O2"
    assert fingerprint.to_json() == original
    assert matrix.to_json() == matrix_snapshot


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 99), ("kind", "codedna.response_matrix"),
])
def test_unsupported_fingerprint_schema_and_wrong_document_kind_are_rejected(field, value):
    data = extract_fingerprint(build_matrix([saved("constants-O0")])).to_dict()
    data[field] = value
    with pytest.raises(ValueError):
        Fingerprint.from_json(json.dumps(data))


def test_a_serialized_fingerprint_cannot_silently_contain_two_configurations():
    matrix = build_matrix([saved("constants-O0"), saved("constants-O2")])
    data = extract_fingerprint(matrix, configuration_id=configuration(matrix, "O0")).to_dict()
    data["configurations"] = matrix.to_dict()["configurations"]
    with pytest.raises(ValueError):
        Fingerprint.from_json(json.dumps(data))


def test_serialized_feature_values_cannot_convert_boolean_or_missing_to_valid_numeric_evidence():
    data = extract_fingerprint(build_matrix([saved("constants-O0")])).to_dict()
    numeric = next(feature for feature in data["observations"][0]["features"] if feature["name"] == "pipeline.changed_nodes")
    for invalid in (True, None):
        changed = deepcopy(data)
        feature = next(item for item in changed["observations"][0]["features"] if item["name"] == numeric["name"])
        feature["value"] = invalid
        with pytest.raises(ValueError):
            Fingerprint.from_json(json.dumps(changed))

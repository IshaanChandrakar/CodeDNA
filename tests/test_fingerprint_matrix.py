"""Pure ingestion of genuine Phase 5 reports and explicit matrix dimensions."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

import pytest

from fingerprint.matrix import build_matrix, normalize_response
from fingerprint.models import ResponseMatrix, canonical_json


FIXTURES = Path(__file__).resolve().parents[1] / "examples/observations/phase5"
NAMES = (
    "constants-O0", "constants-O2", "unroll-O0", "unroll-O2", "combined-O0", "combined-O2",
    "negative", "inapplicable", "rejected", "mismatch", "undefined", "inconclusive", "timeout",
)
BYTE_HASHES = (
    "5a9329dd960b656fb919d5d7312d0f9de3c0caf34374974ce668910242df8c7c",
    "0a429ced8aaec072c8391a749c7f51fd2a46cd801ae60c7b6db5ff279b888391",
    "9f12e99ee300ecaff36ad12c8a73927b5d6a6903805e5d7c2e65a87e83e1fa96",
    "6e0975bffbf59ac78cb79f5b58838444ac2ad48b5a3cd86c1bc15311baefb54c",
    "b66594d1b5f2a9f0e6e5dccb1fe7adb53a6df23cfdfd6b80a16d1b38056110a5",
    "b743acd8c2e3c03a1b50df81457ffdbc8faecd40e92e812d05d3facda5ad7cdd",
    "36fd0f0ca64a2af48b6d9a362f0e900d8b600f0939790ae6a5460ae53ba28f46",
    "42447c0116751e5c5d90fc4f4afa6665e8f6452ddd212a3f125d407eb1940b11",
    "6597419fe6292f56e99a5e051c53c00b347465648d17ad8df4e4d7d880af7db9",
    "0cffad3de29beea2541c129cbeeea7d6b99373b08ec1b0a26df15a7f53e1e145",
    "ec4bb2eb96e306f7176c34a47397de1f46badd18fb93c27065d49d1254fc7029",
    "ebe738ac147e834c80f2f07e864ba9294e256d0662c4659523201ffc450c0df5",
    "a6652c87e64d49d9eb061b5f6aa660483570cc7429c1edb0e63017126f6bb739",
)


def saved(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def feature_map(observation):
    return {feature["name"]: feature for feature in observation["features"]}


def single(name):
    data = build_matrix([saved(name)]).to_dict()
    return data, data["observations"][0], feature_map(data["observations"][0])


@pytest.mark.parametrize("name,digest", tuple(zip(NAMES, BYTE_HASHES)))
def test_curated_reports_preserve_the_authentic_complete_file_bytes(name, digest):
    raw = (FIXTURES / f"{name}.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    assert json.loads(raw)["schema_version"] == 1


def test_all_genuine_observations_align_into_deterministic_axes_without_running_tools():
    reports = [saved(name) for name in NAMES]
    matrix = build_matrix(reports)
    data = matrix.to_dict()
    assert data["schema_version"] == 1 and data["kind"] == "codedna.response_matrix"
    assert data["feature_schema"] == "codedna.features.v1"
    assert len(data["observations"]) == 13
    assert len(data["configurations"]) == 5
    assert len(data["sources"]) == 9
    assert len(data["pipelines"]) == 4
    assert build_matrix(reversed(reports)).to_dict() == data
    assert ResponseMatrix.from_json(matrix.to_json()).to_dict() == data
    assert json.loads(matrix.to_json()) == data
    for axis in ("sources", "pipelines", "configurations", "observations"):
        ids = [entry["id"] for entry in data[axis]]
        assert len(ids) == len(set(ids))
        if axis != "observations":
            assert ids == sorted(ids)
        assert all(re.fullmatch(r".+_[0-9a-f]{64}", value) for value in ids)
    positions = [(entry["source_id"], entry["pipeline_id"], entry["configuration_id"], entry["id"]) for entry in data["observations"]]
    assert positions == sorted(positions)
    known = {axis: {entry["id"] for entry in data[axis]} for axis in ("sources", "pipelines", "configurations")}
    definitions = [entry["name"] for entry in data["feature_definitions"]]
    assert definitions == sorted(definitions) and len(definitions) == len(set(definitions))
    for observation in data["observations"]:
        assert observation["source_id"] in known["sources"]
        assert observation["pipeline_id"] in known["pipelines"]
        assert observation["configuration_id"] in known["configurations"]
        assert [feature["name"] for feature in observation["features"]] == definitions


def test_no_input_evidence_produces_empty_axes_without_fabricated_observations():
    data = build_matrix([]).to_dict()
    assert data["observations"] == data["sources"] == data["pipelines"] == data["configurations"] == []
    assert data == build_matrix(iter(())).to_dict()


@pytest.mark.parametrize("name,original,transformed,response,folds,propagations,unrolls,iterations", [
    ("constants-O0", 4, 2, -0.5, 2, 1, 0, 0),
    ("constants-O2", 4, 2, -0.5, 2, 1, 0, 0),
    ("unroll-O0", 12, 21, 0.75, 0, 0, 1, 4),
    ("unroll-O2", 12, 21, 0.75, 0, 0, 1, 4),
    ("combined-O0", 16, 13, -0.1875, 12, 16, 1, 4),
    ("combined-O2", 16, 13, -0.1875, 12, 16, 1, 4),
    ("negative", 9, 6, -1 / 3, 6, 2, 0, 0),
])
def test_real_structural_features_come_from_saved_canonical_c_and_committed_reports(name, original, transformed, response, folds, propagations, unrolls, iterations):
    _, _, features = single(name)
    expected = {
        "tac.original.operations": original, "tac.transformed.operations": transformed,
        "tac.delta.operations": transformed - original, "tac.response.operations": response,
        "pipeline.expressions_folded": folds, "pipeline.references_propagated": propagations,
        "pipeline.loops_unrolled": unrolls, "pipeline.iterations_expanded": iterations,
    }
    for name, value in expected.items():
        assert features[name]["value"] == pytest.approx(value)
        assert features[name]["validity"] == "valid"
        assert features[name]["reliability"] == "deterministic"


@pytest.mark.parametrize("name", NAMES[:7])
def test_real_noisy_process_observations_are_preserved_and_marked_unreliable(name):
    report = saved(name)
    _, observation, features = single(name)
    ratio = features["performance.median_ratio"]
    assert ratio["value"] == report["benchmark"]["comparison"]["speedup"]
    assert ratio["reliability"] == "unreliable"
    assert ratio["validity"] == "valid" and ratio["reasons"]
    for variant in ("original", "transformed"):
        assert features[f"performance.{variant}.median_ns"]["value"] == report["benchmark"]["groups"][variant]["summary"]["median_ns"]
    baseline = report["benchmark"]["groups"]["original"]["summary"]["median_ns"]
    transformed = report["benchmark"]["groups"]["transformed"]["summary"]["median_ns"]
    assert features["performance.duration_response"]["value"] == pytest.approx((transformed - baseline) / baseline)
    assert observation["provenance"]["report"] == report


@pytest.mark.parametrize("name,status,equivalence,operations", [
    ("inapplicable", "not_applicable", "no_transformation", 1),
    ("rejected", "rejected", "no_transformation", 11),
])
def test_rejected_and_inapplicable_are_distinct_categories_with_factual_zero_edits(name, status, equivalence, operations):
    _, _, features = single(name)
    assert features["pipeline.status"]["value"] == status
    assert features["pipeline.changed_nodes"]["value"] == 0
    assert features["tac.original.operations"]["value"] == operations
    assert features["tac.transformed.operations"]["value"] == operations
    assert features["tac.delta.operations"]["value"] == 0
    assert features["tac.response.operations"]["value"] is None
    assert features["tac.response.operations"]["validity"] == "not_applicable"
    assert features["compiler.equivalence"]["value"] == equivalence
    assert features["performance.median_ratio"]["value"] is None
    assert features["performance.median_ratio"]["reasons"]


@pytest.mark.parametrize("name,outcome", [
    ("mismatch", "different_behavior"), ("undefined", "undefined_behavior"),
    ("inconclusive", "inconclusive"), ("timeout", "timeout"),
])
def test_real_failed_or_unvalidated_experiments_keep_outcomes_and_missing_performance(name, outcome):
    _, observation, features = single(name)
    assert features["compiler.equivalence"]["value"] == outcome
    assert features["compiler.benchmark_status"]["value"] == outcome
    for name in ("performance.median_ratio", "performance.duration_response", "performance.hardware_instructions"):
        assert features[name]["value"] is None
        assert features[name]["validity"] in ("missing", "invalid", "not_applicable")
        assert features[name]["reasons"]
    if outcome == "different_behavior":
        assert observation["provenance"]["report"]["analysis"]["original"]["execution"]["return_value"] == 1
        assert observation["provenance"]["report"]["analysis"]["transformed"]["execution"]["return_value"] == 257
        assert features["pipeline.status"]["value"] == "not_applicable"
        assert features["pipeline.changed_nodes"]["value"] is None
        assert features["pipeline.changed_nodes"]["validity"] == "not_applicable"


def test_combined_pass_order_and_versions_are_not_collapsed_by_repeated_names():
    data, _, features = single("combined-O0")
    pipeline = data["pipelines"][0]
    assert pipeline["sequence"] == ["constants", "unroll", "constants"]
    assert [entry["name"] for entry in pipeline["passes"]] == ["constant_propagation_folding", "loop_unrolling", "constant_propagation_folding"]
    assert [entry["version"] for entry in pipeline["passes"]] == ["1"] * 3
    assert pipeline["passes"][1]["parameters"] == {"max_iterations": 32}
    assert features["pipeline.status"]["value"] == "applied > applied > applied"


def test_actual_toolchain_environment_and_complete_measurement_protocol_are_identified():
    report = saved("constants-O0")
    data, _, _ = single("constants-O0")
    identity = data["configurations"][0]["identity"]
    assert identity["compiler"]["path"] == "/usr/bin/clang"
    assert "Apple clang version 21.0.0" in identity["compiler"]["version"]
    assert identity["environment"]["machine"] == "arm64"
    assert identity["environment"]["platform"].startswith("macOS-26.6.2")
    assert identity["settings"] == {key: value for key, value in report["analysis"]["settings"].items() if key != "max_unroll_iterations"}
    assert identity["measurement"] == report["benchmark"]["settings"]


def test_raw_input_hash_is_not_incorrectly_required_to_match_canonical_emission():
    report = saved("constants-O0")
    canonical = report["analysis"]["original"]["canonical_source"]
    assert hashlib.sha256(canonical.encode()).hexdigest() != report["analysis"]["source"]["sha256"]
    data, _, _ = single("constants-O0")
    assert data["sources"][0]["sha256"] == report["analysis"]["source"]["sha256"]
    assert data["sources"][0]["canonical_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()


def test_feature_provenance_points_back_to_the_complete_imported_observation():
    report = saved("constants-O0")
    _, observation, features = single("constants-O0")
    digest = hashlib.sha256(canonical_json(report).encode()).hexdigest()
    assert observation["provenance"]["report_sha256"] == digest
    assert observation["benchmark_id"] == report["benchmark_id"]
    assert observation["provenance"]["report"] == report
    for feature in features.values():
        assert feature["provenance"]["observation_id"] == observation["id"]
        assert feature["provenance"]["report_sha256"] == digest
        assert isinstance(feature["provenance"]["pointer"], str) and feature["provenance"]["pointer"]


def test_exact_duplicates_deduplicate_but_repeated_experiments_never_auto_average():
    report = saved("constants-O0")
    duplicate = json.loads(json.dumps(report, sort_keys=True))
    assert len(build_matrix([report, duplicate]).to_dict()["observations"]) == 1
    repeat = deepcopy(report)
    repeat["benchmark_id"] = "another-real-experiment-identifier"
    data = build_matrix([report, repeat]).to_dict()
    assert len(data["observations"]) == 2
    assert len(data["sources"]) == len(data["pipelines"]) == len(data["configurations"]) == 1
    assert len({entry["id"] for entry in data["observations"]}) == 2


def test_historical_workspace_paths_are_provenance_rather_than_configuration_identity():
    report = saved("constants-O0")
    relocated = deepcopy(report)
    relocated["benchmark_id"] = "relocated-copy"
    relocated["environment_metadata"]["workspace"] = "/does/not/exist/historical-artifact"
    data = build_matrix([report, relocated]).to_dict()
    assert len(data["observations"]) == 2
    assert len(data["configurations"]) == 1


@pytest.mark.parametrize("tampering,reason", [
    ("median", "inconsistent_summary"),
    ("reliability", "inconsistent_reliability_or_ratio"),
    ("execution", "observation_drift"),
    ("order", "invalid_sample_schedule"),
])
def test_import_audits_raw_samples_instead_of_trusting_promoted_timing_claims(tampering, reason):
    report = saved("constants-O0")
    if tampering == "median":
        report["benchmark"]["groups"]["original"]["summary"]["median_ns"] += 1_000_000
    elif tampering == "reliability":
        report["benchmark"]["comparison"].update(status="available", issues=[])
    elif tampering == "execution":
        report["benchmark"]["samples"][0]["execution"]["return_value"] = 1
    else:
        report["benchmark"]["samples"].reverse()
    data = build_matrix([report]).to_dict()
    observation = data["observations"][0]
    features = feature_map(observation)
    assert observation["provenance"]["report"] == report
    assert features["performance.median_ratio"]["value"] == report["benchmark"]["comparison"]["speedup"]
    assert features["performance.median_ratio"]["validity"] == "invalid"
    assert reason in features["performance.median_ratio"]["reasons"]
    assert features["tac.original.operations"]["validity"] == "valid"


@pytest.mark.parametrize("contradiction", ["different_full_returns", "compilation_failure", "capability_failure"])
def test_timing_cannot_be_validated_by_a_contradictory_equivalence_category(contradiction):
    report = saved("constants-O0")
    if contradiction == "different_full_returns":
        report["analysis"]["transformed"]["execution"]["return_value"] = 1
        # Every observation still agrees with its own group's validation run.
        # The importer must also compare the two complete validation results.
        for sample in report["benchmark"]["samples"]:
            if sample["variant"] == "transformed":
                sample["execution"]["return_value"] = 1
    elif contradiction == "compilation_failure":
        report["analysis"]["original"]["compilation"].update(status="compilation_failure", returncode=1)
    else:
        report["analysis"]["capability"]["execution"].update(status="execution_failure", process_returncode=1, return_value=None)
    assert report["analysis"]["outcome"] == "observed_equivalent"
    data = build_matrix(report).to_dict()
    observation = data["observations"][0]
    features = feature_map(observation)
    assert observation["provenance"]["report"] == report
    for name in ("performance.original.median_ns", "performance.transformed.median_ns", "performance.median_ratio", "performance.duration_response"):
        assert features[name]["value"] is not None
        assert features[name]["validity"] == "invalid"
        assert features[name]["reasons"]
    assert features["performance.median_ratio"]["value"] == report["benchmark"]["comparison"]["speedup"]
    assert features["tac.original.operations"]["validity"] == "valid"


def test_conflicting_canonical_programs_cannot_silently_share_a_raw_source_identity():
    original = saved("constants-O0")
    conflict = deepcopy(original)
    conflict["benchmark_id"] = "conflicting-source"
    conflict["analysis"]["original"]["canonical_source"] = "int main(void){return 0;}\n"
    with pytest.raises(ValueError):
        build_matrix([original, conflict])


@pytest.mark.parametrize("baseline,variant,expected", [
    (4, 2, -0.5), (12, 21, 0.75), (16, 13, -0.1875), (10, 10, 0.0), (10, 0, -1.0),
])
def test_response_normalization_has_a_positive_original_baseline(baseline, variant, expected):
    assert normalize_response(baseline, variant) == pytest.approx(expected)


@pytest.mark.parametrize("baseline,variant", [
    (0, 1), (-1, 1), (None, 1), (True, 1), (1, True), (1, None), (1, -1),
    (float("nan"), 1), (1, float("inf")), (1, "2"),
])
def test_missing_invalid_or_nonpositive_baselines_do_not_create_fake_responses(baseline, variant):
    assert normalize_response(baseline, variant) is None


@pytest.mark.parametrize("path,value", [
    (("schema_version",), True), (("schema_version",), 2),
    (("analysis", "source", "sha256"), "not-a-sha256"),
    (("analysis", "original", "source_sha256"), "0" * 64),
    (("analysis", "transformation_reports", 0, "statistics", "expressions_folded"), True),
    (("analysis", "transformation_reports", 0, "statistics", "changed_nodes"), -1),
    (("analysis", "transformation_reports", 0, "status"), "invented_status"),
    (("analysis", "settings", "sanitizer_requested"), "yes"),
    (("benchmark", "groups", "original", "summary", "median_ns"), float("nan")),
])
def test_malformed_imported_fields_are_rejected_without_silently_defaulting(path, value):
    report = saved("constants-O0")
    target = report
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        build_matrix([report])


def test_export_mutation_cannot_change_matrix_identities_or_original_reports():
    report = saved("constants-O0")
    snapshot = deepcopy(report)
    matrix = build_matrix([report])
    exported = matrix.to_dict()
    exported["observations"][0]["features"][0]["value"] = "edited export"
    assert matrix.to_dict() != exported
    assert report == snapshot

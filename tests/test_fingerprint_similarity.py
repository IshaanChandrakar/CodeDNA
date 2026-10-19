"""Hand-checkable synthetic comparison evidence; no compiled measurements."""

from copy import deepcopy
import hashlib
import json
import math

import pytest

from fingerprint.models import ComparisonResult, Fingerprint, stable_id
from fingerprint.similarity import ComparisonConfig, compare


def definition(name, *, kind="numeric", group="structural", unit="count"):
    return {"name": name, "kind": kind, "group": group, "unit": unit,
            "rule": "relative" if kind == "numeric" else "categorical", "description": f"Synthetic unit-test {name}."}


DEFINITIONS = {
    "count": definition("count"), "delta": definition("delta"),
    "status": definition("status", kind="categorical", group="compiler", unit="status"),
    "ratio": definition("ratio", group="performance", unit="ratio"),
}


def identity(optimization="O0"):
    return {
        "compiler": {"status": "available", "path": "/fixture/clang", "version": "synthetic clang v1\nTarget: fixture-target", "target": "fixture-target"},
        "settings": {"compiler": "/fixture/clang", "standard": "c11", "optimization": optimization,
                     "flags": ["-std=c11", "-" + optimization, "-fsanitize=undefined"],
                     "compile_timeout_seconds": 10, "execution_timeout_seconds": 2,
                     "sanitizer_requested": True, "max_output_bytes": 65536, "memory_limit_mb": None,
                     "target": "signed-32-bit-int", "observation_protocol": 1,
                     "case": {"stdin": "", "arguments": [], "environment": {
                         "LC_ALL": "C", "LANG": "C", "TZ": "UTC",
                         "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=0:exitcode=86"}}},
        "environment": {"platform": "synthetic-platform", "machine": "synthetic-arch", "python": "synthetic-python",
                        "clock": {"name": "perf_counter_ns", "implementation": "synthetic clock", "monotonic": True,
                                  "adjustable": False, "reported_resolution_seconds": 1e-9}},
        "measurement": {"warmups_per_variant": 5, "measurements_per_variant": 30,
                        "order": "alternating_pairs", "order_definition": "AB/BA",
                        "measurement_scope": "end_to_end_process_execution", "duration_unit": "ns",
                        "timing_definition": "Synthetic timing contract for unit tests only.",
                        "clock_backend": "time.perf_counter_ns", "warmups_timed": False, "compilation_timed": False},
    }


def feature(name, value, *, validity="valid", reliability="deterministic", reasons=()):
    return {"name": name, "value": value, "validity": validity, "reliability": reliability,
            "reasons": list(reasons), "provenance": {"observation_id": "unit-observation", "report_sha256": "a" * 64, "pointer": "/synthetic"}}


def fingerprint(features=None, *, source="source-A", optimization="O0", sequence=("constants",), definitions=None):
    if features is None:
        features = [feature("count", 10), feature("delta", 0)]
    digest = hashlib.sha256(source.encode()).hexdigest()
    source_record = {"id": "src_" + digest, "sha256": digest, "names": [source]}
    reports = {"constants": "constant_propagation_folding", "unroll": "loop_unrolling"}
    pipeline_record = {"sequence": list(sequence), "passes": [{"name": reports[name], "version": "1", "parameters": {}} for name in sequence],
                       "max_unroll_iterations": 32, "comparison_kind": "transformation_pipeline", "comparison_source": None}
    pipeline_record["id"] = stable_id("pipe", pipeline_record)
    configuration = {"identity": identity(optimization)}
    configuration["id"] = stable_id("config", configuration)
    observation = {"id": stable_id("obs", {"source": source, "sequence": sequence, "features": features}),
                   "benchmark_id": "synthetic-unit-fixture", "source_id": source_record["id"],
                   "pipeline_id": pipeline_record["id"], "configuration_id": configuration["id"],
                   "features": deepcopy(features), "provenance": {"report_sha256": "a" * 64,
                    "benchmark_id": "synthetic-unit-fixture", "report": {"synthetic_unit_fixture": True}}}
    payload = {"schema_version": 1, "kind": "codedna.fingerprint", "feature_schema": "codedna.features.v1",
               "feature_definitions": deepcopy(definitions if definitions is not None else [DEFINITIONS[item["name"]] for item in features]),
               "sources": [source_record], "pipelines": [pipeline_record], "configurations": [configuration], "observations": [observation]}
    return Fingerprint({**payload, "fingerprint_id": stable_id("fingerprint", payload)})


def changed(original, mutate):
    payload = original.to_dict()
    mutate(payload)
    payload.pop("fingerprint_id", None)
    return Fingerprint({**payload, "fingerprint_id": stable_id("fingerprint", payload)})


def result(left, right=None, **settings):
    return compare(left, left if right is None else right, ComparisonConfig(**settings)).to_dict()


def dimension(report, name):
    return next(item for item in report["dimensions"] if item["feature"] == name)


def test_identical_mixed_evidence_has_zero_distance_and_full_coverage():
    left = fingerprint([feature("count", 10), feature("delta", -3), feature("status", "success", reliability="observed")])
    report = result(left)
    assert report["status"] == "comparable"
    assert report["distance"] == 0 and report["similarity"] == 1
    assert (report["usable_dimensions"], report["requested_dimensions"], report["coverage"]) == (3, 3, 1)
    assert report["inputs"]["left"] == report["inputs"]["right"] == left.to_dict()


def test_numeric_and_categorical_rules_have_hand_derived_mean_and_contributions():
    left = fingerprint([feature("count", 10), feature("delta", 0), feature("status", "success")])
    right = fingerprint([feature("count", 20), feature("delta", 0), feature("status", "failure")])
    report = result(left, right)
    assert dimension(report, "count")["difference"] == pytest.approx(1 / 3)
    assert dimension(report, "delta")["difference"] == 0
    assert dimension(report, "status")["difference"] == 1
    assert report["distance"] == pytest.approx(4 / 9)
    assert report["similarity"] == pytest.approx(5 / 9)
    assert sum(item["contribution"] for item in report["dimensions"]) == pytest.approx(report["distance"])


def test_explicit_feature_weights_are_normalized_across_usable_evidence():
    left = fingerprint([feature("count", 10), feature("status", "success")])
    right = fingerprint([feature("count", 20), feature("status", "failure")])
    report = result(left, right, weights=(("count", 3), ("status", 1)))
    assert report["distance"] == pytest.approx(0.5)
    assert dimension(report, "count")["contribution"] == pytest.approx(0.25)
    assert dimension(report, "status")["contribution"] == pytest.approx(0.25)


@pytest.mark.parametrize("left_value,right_value,expected", [
    (0, 0, 0), (0, 4, 1), (-4, 0, 1), (-3, -9, 0.5), (-1, 1, 1),
    (1e308, -1e308, 1), (1e308, 1e308, 0),
    (5e-324, 1e-323, 1 / 3), (10**300, 10**300 + 1, 1 / (2 * 10**300 + 1)),
])
def test_relative_difference_handles_signed_zero_extreme_and_close_large_values(left_value, right_value, expected):
    left = fingerprint([feature("count", left_value), feature("delta", 0)])
    right = fingerprint([feature("count", right_value), feature("delta", 0)])
    report = result(left, right)
    assert dimension(report, "count")["difference"] == pytest.approx(expected)
    if expected:
        assert dimension(report, "count")["difference"] > 0
    assert math.isfinite(report["distance"]) and 0 <= report["distance"] <= 1
    assert result(right, left)["distance"] == report["distance"]


def test_large_finite_weights_do_not_overflow_the_weighted_mean():
    left = fingerprint([feature("count", 0), feature("delta", 1)])
    right = fingerprint([feature("count", 1), feature("delta", 1)])
    report = result(left, right, weights=(("count", 1e308), ("delta", 1e308)))
    assert report["distance"] == 0.5
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("validity", ["missing", "invalid", "not_applicable"])
def test_invalidity_excludes_dimensions_instead_of_filling_them_with_zero(validity):
    left = fingerprint([feature("count", None, validity=validity, reliability="unavailable", reasons=("no evidence",)), feature("delta", 2)])
    report = result(left)
    assert report["status"] == "insufficient_evidence"
    assert report["distance"] is report["similarity"] is None
    assert (report["usable_dimensions"], report["requested_dimensions"], report["coverage"]) == (1, 2, 0.5)
    cell = dimension(report, "count")
    assert not cell["usable"] and cell["difference"] is None
    assert f"left_{validity}" in cell["reasons"]
    assert cell["left_reasons"] == ["no evidence"]


@pytest.mark.parametrize("reliability", ["unreliable", "descriptive_only", "unavailable"])
def test_unreliable_or_descriptive_numbers_never_contribute_even_with_high_weight(reliability):
    left = fingerprint([feature("ratio", 1.002011, reliability=reliability, reasons=("startup dominated",)), feature("count", 2)])
    report = result(left, groups=("performance",), weights=(("ratio", 1e308),), min_dimensions=1)
    assert report["status"] == "insufficient_evidence"
    assert report["usable_dimensions"] == 0 and report["coverage"] == 0
    cell = dimension(report, "ratio")
    assert cell["left_value"] == 1.002011
    assert cell["left_reliability"] == reliability and cell["contribution"] is None
    assert cell["left_reasons"] == ["startup dominated"]


def test_explicit_available_numeric_backend_evidence_can_be_used():
    left = fingerprint([feature("ratio", 1, reliability="available"), feature("count", 2)])
    assert result(left)["usable_dimensions"] == 2


@pytest.mark.parametrize("reliability", ["unreliable", "descriptive_only", "unavailable", "available"])
def test_categorical_evidence_requires_deterministic_or_observed_reliability(reliability):
    left = fingerprint([feature("status", "success", reliability=reliability), feature("count", 2)])
    assert result(left)["status"] == "insufficient_evidence"


def test_missing_feature_definition_and_values_are_explicit_union_exclusions():
    left = fingerprint([feature("count", 2)])
    right = fingerprint([feature("count", 2), feature("delta", 0)])
    report = result(left, right, min_dimensions=1)
    assert report["status"] == "comparable" and report["distance"] == 0
    assert report["coverage"] == 0.5
    assert dimension(report, "delta")["reasons"] == ["left_feature_missing"]


def test_structural_group_selection_does_not_score_available_compiler_categories():
    left = fingerprint([feature("count", 2), feature("status", "success")])
    report = result(left, groups=("structural",), min_dimensions=1)
    assert [item["feature"] for item in report["dimensions"]] == ["count"]
    assert report["requested_dimensions"] == report["usable_dimensions"] == 1


@pytest.mark.parametrize("field,value", [("unit", "different-unit"), ("description", "different meaning"), ("group", "performance")])
def test_feature_definition_mismatches_reject_comparison(field, value):
    left = fingerprint()
    right = changed(left, lambda data: data["feature_definitions"][0].__setitem__(field, value))
    report = result(left, right)
    assert report["status"] == "incompatible" and report["distance"] is None
    assert any("feature_definition_mismatch" in reason for reason in report["incompatibilities"])


@pytest.mark.parametrize("both_unknown", [False, True])
def test_unknown_feature_schema_cannot_gain_a_self_similarity_score(both_unknown):
    left = fingerprint()
    right = changed(left, lambda data: data.__setitem__("feature_schema", "codedna.future.v2"))
    report = result(right if both_unknown else left, right)
    assert report["status"] == "incompatible"
    assert report["distance"] is report["similarity"] is None


def test_strict_alignment_rejects_optimization_changes_and_explicit_configuration_mode_allows_them():
    left, right = fingerprint(), fingerprint(optimization="O2")
    assert result(left, right)["status"] == "incompatible"
    report = result(left, right, alignment="configuration")
    assert report["status"] == "comparable" and report["distance"] == 0
    assert any("O0 and O2" in text for text in report["interpretation"])


def test_configuration_alignment_allows_known_compiler_identity_changes_only():
    left = fingerprint()
    def change(data):
        config = data["configurations"][0]["identity"]
        config["compiler"].update(path="/other/clang", version="different version; same target")
        config["settings"]["compiler"] = "/other/clang"
    right = changed(left, change)
    assert result(left, right, alignment="configuration")["status"] == "comparable"
    assert result(left, right)["status"] == "incompatible"


@pytest.mark.parametrize("section,field,value", [
    ("compiler", "target", "different-target"), ("environment", "platform", "different OS"),
    ("environment", "machine", "different CPU"), ("environment", "python", "different Python"),
    ("measurement", "measurements_per_variant", 20), ("measurement", "warmups_per_variant", 3),
    ("settings", "sanitizer_requested", False), ("settings", "execution_timeout_seconds", 9),
    ("settings", "target", "other-int-model"), ("settings", "max_output_bytes", 1024),
])
def test_configuration_alignment_does_not_relax_environment_target_or_other_conditions(section, field, value):
    left = fingerprint()
    right = changed(left, lambda data: data["configurations"][0]["identity"][section].__setitem__(field, value))
    assert result(left, right, alignment="configuration")["status"] == "incompatible"


@pytest.mark.parametrize("section,field,value", [
    ("compiler", "target", None), ("compiler", "version", None), ("compiler", "path", None),
    ("compiler", "status", "missing"), ("environment", "machine", ""), ("environment", "clock", {}),
    ("measurement", "duration_unit", "unknown"), ("settings", "case", {}),
])
def test_unknown_configuration_fields_cannot_be_compared_to_themselves_as_evidence(section, field, value):
    original = fingerprint()
    unknown = changed(original, lambda data: data["configurations"][0]["identity"][section].__setitem__(field, value))
    report = result(unknown)
    assert report["status"] == "incompatible" and report["similarity"] is None


def test_clock_or_case_changes_remain_incompatible_in_configuration_mode():
    left = fingerprint()
    for change in (
        lambda data: data["configurations"][0]["identity"]["environment"]["clock"].__setitem__("reported_resolution_seconds", 1e-6),
        lambda data: data["configurations"][0]["identity"]["settings"]["case"].__setitem__("stdin", "different input"),
    ):
        assert result(left, changed(left, change), alignment="configuration")["status"] == "incompatible"


@pytest.mark.parametrize("case", [
    {}, {"arguments": [], "environment": {}}, {"stdin": "", "environment": {}},
    {"stdin": "", "arguments": []}, {"stdin": False, "arguments": [], "environment": {}},
    {"stdin": "", "arguments": "", "environment": {}},
    {"stdin": "", "arguments": [1], "environment": {}},
    {"stdin": "", "arguments": [], "environment": []},
    {"stdin": "", "arguments": [], "environment": {"LC_ALL": 1}},
])
def test_missing_or_malformed_execution_cases_cannot_create_self_similarity(case):
    unknown = changed(fingerprint(), lambda data: data["configurations"][0]["identity"]["settings"].__setitem__("case", case))
    report = result(unknown)
    assert report["status"] == "incompatible" and report["similarity"] is None
    assert any("Execution case identity" in reason for reason in report["incompatibilities"])


@pytest.mark.parametrize("control", ["LC_ALL", "LANG", "TZ", "UBSAN_OPTIONS"])
def test_missing_enforced_control_environment_is_not_compatibility_evidence(control):
    unknown = changed(fingerprint(), lambda data: data["configurations"][0]["identity"]["settings"]["case"]["environment"].pop(control))
    report = result(unknown)
    assert report["status"] == "incompatible" and report["similarity"] is None
    assert any("Controlled execution environment" in reason for reason in report["incompatibilities"])


@pytest.mark.parametrize("sequence,passes", [
    (["constants"], []),
    ([], [{"name": "constant_propagation_folding", "version": "1", "parameters": {}}]),
    (["constants", "constants"], [{"name": "constant_propagation_folding", "version": "1", "parameters": {}}]),
    (["constants"], [{"name": "loop_unrolling", "version": "1", "parameters": {}}]),
    (["unroll"], [{"name": "constant_propagation_folding", "version": "1", "parameters": {}}]),
    (["advanced"], [{"name": "advanced_pass", "version": "1", "parameters": {}}]),
])
def test_sequence_and_pass_records_must_have_matching_supported_identities(sequence, passes):
    def change(data):
        data["pipelines"][0].update(sequence=sequence, passes=passes)
    unknown = changed(fingerprint(), change)
    report = result(unknown)
    assert report["status"] == "incompatible" and report["similarity"] is None
    assert any("Sequence and supported pass identities" in reason for reason in report["incompatibilities"])


def test_explicit_program_alignment_compares_single_sources_without_calling_structure_compiler_behavior():
    left = fingerprint()
    right = fingerprint([feature("count", 20), feature("delta", 0)], source="different-source")
    assert result(left, right)["status"] == "insufficient_evidence"
    report = result(left, right, alignment="program")
    assert report["status"] == "comparable"
    assert report["distance"] == pytest.approx(1 / 6)
    assert any("not be attributed to compiler behavior" in text for text in report["interpretation"])


def test_explicit_pipeline_alignment_compares_different_sequences_for_the_same_source():
    left, right = fingerprint(), fingerprint(sequence=("unroll",))
    assert result(left, right)["status"] == "insufficient_evidence"
    assert result(left, right, alignment="pipeline")["status"] == "comparable"
    assert result(left, right, alignment="program")["status"] == "incompatible"


@pytest.mark.parametrize("mode", ["strict", "configuration", "pipeline"])
@pytest.mark.parametrize("parameter", ["version", "parameters"])
def test_shared_pass_version_or_parameter_mismatch_is_incompatible(mode, parameter):
    left = fingerprint()
    replacement = "2" if parameter == "version" else {"changed": 1}
    right = changed(left, lambda data: data["pipelines"][0]["passes"][0].__setitem__(parameter, replacement))
    report = result(left, right, alignment=mode)
    assert report["status"] == "incompatible" and report["similarity"] is None


@pytest.mark.parametrize("field,value", [("comparison_kind", "independent_sources"), ("comparison_source", "b" * 64)])
def test_pipeline_alignment_cannot_change_independent_comparison_context(field, value):
    left = fingerprint()
    right = changed(left, lambda data: data["pipelines"][0].__setitem__(field, value))
    report = result(left, right, alignment="pipeline")
    assert report["status"] == "incompatible"
    assert "pipeline_comparison_context_mismatch" in report["incompatibilities"]


def test_pipeline_alignment_requires_the_same_source():
    assert result(fingerprint(), fingerprint(source="other"), alignment="pipeline")["status"] == "incompatible"


def duplicate_observation(data):
    duplicate = deepcopy(data["observations"][0])
    duplicate["id"] += "-replicate"
    data["observations"].append(duplicate)


def test_ambiguous_replicates_are_excluded_without_arbitrary_pairing():
    left = changed(fingerprint(), duplicate_observation)
    right = fingerprint()
    report = result(left, right)
    assert report["status"] == "insufficient_evidence"
    assert report["usable_dimensions"] == 0
    assert len(report["excluded_observations"]) == 3
    assert all("ambiguous_left_replicates" in item["reasons"] for item in report["dimensions"])
    assert all(item["left_value"] is None for item in report["dimensions"])


def test_empty_observation_union_has_no_score_and_zero_coverage():
    empty = changed(fingerprint(), lambda data: data.__setitem__("observations", []))
    report = result(empty)
    assert report["status"] == "insufficient_evidence"
    assert report["requested_dimensions"] == report["usable_dimensions"] == 0
    assert report["coverage"] == 0 and report["distance"] is report["similarity"] is None


def test_identical_multi_parameter_fingerprints_align_each_actual_pipeline_row():
    def add_parameter_variant(data):
        pipeline = deepcopy(data["pipelines"][0])
        pipeline["id"] += "-second-setting"
        pipeline["max_unroll_iterations"] = 4
        data["pipelines"].append(pipeline)
        observation = deepcopy(data["observations"][0])
        observation["id"] += "-second-setting"
        observation["pipeline_id"] = pipeline["id"]
        data["observations"].append(observation)
    left = changed(fingerprint(), add_parameter_variant)
    report = result(left)
    assert report["status"] == "comparable"
    assert report["distance"] == 0 and report["usable_dimensions"] == 4


def test_program_alignment_does_not_collapse_boolean_and_integer_pass_parameters():
    original = fingerprint()
    left = changed(original, lambda data: data["pipelines"][0]["passes"][0].__setitem__("parameters", {"setting": True}))
    right = changed(original, lambda data: data["pipelines"][0]["passes"][0].__setitem__("parameters", {"setting": 1}))
    assert result(left, right, alignment="program")["status"] == "incompatible"


@pytest.mark.parametrize("mode", ["program", "pipeline"])
def test_explicit_cross_axis_alignment_rejects_multiple_observations(mode):
    left = changed(fingerprint(), duplicate_observation)
    assert result(left, fingerprint(), alignment=mode)["status"] == "incompatible"


def test_unmatched_sources_reduce_union_coverage_without_erasing_the_matching_row():
    first, extra = fingerprint(), fingerprint(source="other-source")
    def add(data):
        other = extra.to_dict()
        data["sources"].extend(other["sources"])
        data["observations"].extend(other["observations"])
    left = changed(first, add)
    report = result(left, first)
    assert report["status"] == "comparable" and report["distance"] == 0
    assert (report["usable_dimensions"], report["requested_dimensions"], report["coverage"]) == (2, 4, 0.5)
    assert report["excluded_observations"][0]["reason"] == "unmatched_observation"


def test_output_is_detached_deterministic_serializable_and_does_not_mutate_inputs():
    left, right = fingerprint(), fingerprint([feature("count", 20), feature("delta", 3)])
    before = left.to_json(), right.to_json()
    first, second = compare(left, right), compare(left, right)
    assert first.to_json() == second.to_json()
    assert ComparisonResult.from_json(first.to_json()).to_dict() == first.to_dict()
    exported = first.to_dict()
    exported["inputs"]["left"]["observations"].clear()
    assert first.to_dict()["inputs"]["left"]["observations"]
    assert (left.to_json(), right.to_json()) == before


@pytest.mark.parametrize("settings", [
    {"alignment": "unknown"}, {"groups": ["structural"]}, {"groups": ("unknown",)},
    {"groups": ("structural", "structural")}, {"min_dimensions": 0}, {"min_dimensions": -1},
    {"min_dimensions": True}, {"min_dimensions": 1.0}, {"weights": []},
    {"weights": (("count", 0),)}, {"weights": (("count", -1),)}, {"weights": (("count", True),)},
    {"weights": (("count", math.inf),)}, {"weights": (("count", math.nan),)},
    {"weights": (("count", 1), ("count", 2))}, {"weights": (("", 1),)},
    {"weights": (("count",),)},
])
def test_invalid_comparison_configuration_is_rejected(settings):
    with pytest.raises(ValueError):
        ComparisonConfig(**settings)


def test_unknown_weight_and_wrong_input_types_are_configuration_errors():
    with pytest.raises(ValueError, match="Unknown weight"):
        compare(fingerprint(), fingerprint(), ComparisonConfig(weights=(("unknown", 1),)))
    with pytest.raises(ValueError, match="Fingerprint"):
        compare({}, fingerprint())
    with pytest.raises(ValueError, match="ComparisonConfig"):
        compare(fingerprint(), fingerprint(), {})

"""Interpretable, missing-aware comparisons of descriptive fingerprints.

Numerics use bounded symmetric relative differences; categories use equality.
Scores summarize usable aligned evidence, never compiler identity or semantic
equivalence. Unknown configurations and noisy timing data cannot earn scores.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from fingerprint.models import (
    FEATURE_SCHEMA, ComparisonResult, Fingerprint, canonical_json, finite_number, stable_id,
)


GROUPS = ("structural", "compiler", "performance")
PASS_NAMES = {"constants": "constant_propagation_folding", "unroll": "loop_unrolling"}
CONTROL_ENVIRONMENT = {
    "LC_ALL": "C", "LANG": "C", "TZ": "UTC",
    "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=0:exitcode=86",
}


@dataclass(frozen=True, slots=True)
class ComparisonConfig:
    alignment: str = "strict"
    groups: tuple[str, ...] = ()
    weights: tuple[tuple[str, float], ...] = ()
    min_dimensions: int = 2

    def __post_init__(self) -> None:
        if self.alignment not in ("strict", "configuration", "program", "pipeline"):
            raise ValueError("alignment must be strict, configuration, program or pipeline")
        if not isinstance(self.groups, tuple) or any(group not in GROUPS for group in self.groups):
            raise ValueError("groups must be a tuple of structural, compiler or performance")
        if len(self.groups) != len(set(self.groups)):
            raise ValueError("groups must not contain duplicates")
        if not isinstance(self.weights, tuple):
            raise ValueError("weights must be a tuple of (feature, positive finite weight) pairs")
        names = []
        for pair in self.weights:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError("weights must contain (feature, positive finite weight) pairs")
            name, weight = pair
            if not isinstance(name, str) or not name or not finite_number(weight) or weight <= 0:
                raise ValueError("weights require a nonempty feature and positive finite number")
            names.append(name)
        if len(names) != len(set(names)):
            raise ValueError("weights must not repeat a feature")
        if type(self.min_dimensions) is not int or self.min_dimensions < 1:
            raise ValueError("min_dimensions must be a positive integer")


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value)


def _configuration(identity: dict) -> None:
    """Require actual compatibility evidence, not equality of missing fields."""
    for name in ("compiler", "settings", "environment", "measurement"):
        if not isinstance(identity.get(name), dict):
            raise ValueError(f"Incomplete configuration {name}")
    compiler, settings = identity["compiler"], identity["settings"]
    if compiler.get("status") != "available" or not all(_nonempty(compiler.get(key)) for key in ("path", "version", "target")):
        raise ValueError("Compiler identity or target is unavailable")
    required = (
        "compiler", "standard", "optimization", "flags", "compile_timeout_seconds",
        "execution_timeout_seconds", "sanitizer_requested", "max_output_bytes",
        "memory_limit_mb", "target", "observation_protocol", "case",
    )
    if not all(key in settings for key in required):
        raise ValueError("Incomplete compiler settings")
    if (not _nonempty(settings["compiler"]) or settings["standard"] != "c11"
            or settings["optimization"] not in ("O0", "O2")
            or not isinstance(settings["flags"], list) or not settings["flags"]
            or not all(isinstance(flag, str) for flag in settings["flags"])
            or not _nonempty(settings["target"]) or not isinstance(settings["case"], dict)
            or type(settings["sanitizer_requested"]) is not bool
            or type(settings["observation_protocol"]) is not int or settings["observation_protocol"] != 1):
        raise ValueError("Invalid compiler settings")
    for name in ("compile_timeout_seconds", "execution_timeout_seconds"):
        if not finite_number(settings[name]) or settings[name] <= 0:
            raise ValueError(f"Invalid {name}")
    if type(settings["max_output_bytes"]) is not int or settings["max_output_bytes"] <= 0:
        raise ValueError("Invalid output limit")
    if settings["memory_limit_mb"] is not None and (type(settings["memory_limit_mb"]) is not int or settings["memory_limit_mb"] <= 0):
        raise ValueError("Invalid memory limit")
    case = settings["case"]
    if (not isinstance(case.get("stdin"), str) or not isinstance(case.get("arguments"), list)
            or not all(isinstance(argument, str) for argument in case["arguments"])
            or not isinstance(case.get("environment"), dict)
            or not all(isinstance(name, str) and isinstance(value, str) for name, value in case["environment"].items())):
        raise ValueError("Execution case identity is incomplete")
    if any(case["environment"].get(name) != value for name, value in CONTROL_ENVIRONMENT.items()):
        raise ValueError("Controlled execution environment is incomplete or unsupported")
    environment = identity["environment"]
    if not all(_nonempty(environment.get(key)) for key in ("platform", "machine", "python")):
        raise ValueError("Environment identity is incomplete")
    clock = environment.get("clock")
    if (not isinstance(clock, dict) or clock.get("name") != "perf_counter_ns"
            or not _nonempty(clock.get("implementation")) or clock.get("monotonic") is not True
            or type(clock.get("adjustable")) is not bool
            or not finite_number(clock.get("reported_resolution_seconds"))
            or clock["reported_resolution_seconds"] <= 0):
        raise ValueError("Clock identity is incomplete")
    measurement = identity["measurement"]
    for name in ("order", "order_definition", "measurement_scope", "duration_unit", "timing_definition", "clock_backend"):
        if not _nonempty(measurement.get(name)):
            raise ValueError(f"Measurement identity is incomplete: {name}")
    if (type(measurement.get("warmups_per_variant")) is not int or measurement["warmups_per_variant"] < 0
            or type(measurement.get("measurements_per_variant")) is not int or measurement["measurements_per_variant"] < 1
            or type(measurement.get("warmups_timed")) is not bool
            or type(measurement.get("compilation_timed")) is not bool):
        raise ValueError("Measurement settings are incomplete")
    if (measurement["measurement_scope"] != "end_to_end_process_execution"
            or measurement["duration_unit"] != "ns"
            or measurement["clock_backend"] != "time.perf_counter_ns"):
        raise ValueError("Unsupported measurement scope, unit or clock")


def _inspect(data: dict) -> dict:
    if data.get("feature_schema") != FEATURE_SCHEMA:
        raise ValueError(f"Unsupported feature schema: {data.get('feature_schema')!r}")
    if not _nonempty(data.get("fingerprint_id")):
        raise ValueError("Missing fingerprint_id")
    definitions = {item["name"]: item for item in data["feature_definitions"]}
    if any(not isinstance(item.get("description"), str) for item in definitions.values()):
        raise ValueError("Feature definitions require descriptions")
    sources = {item["id"]: item for item in data["sources"]}
    if any(not _nonempty(item.get("sha256")) for item in sources.values()):
        raise ValueError("Source identity is incomplete")
    pipelines = {item["id"]: item for item in data["pipelines"]}
    for pipeline in pipelines.values():
        if (not isinstance(pipeline.get("sequence"), list)
                or not all(_nonempty(name) for name in pipeline["sequence"])
                or not isinstance(pipeline.get("passes"), list)
                or type(pipeline.get("max_unroll_iterations")) is not int
                or not 0 <= pipeline["max_unroll_iterations"] <= 1024
                or pipeline.get("comparison_kind") not in ("transformation_pipeline", "independent_sources")
                or "comparison_source" not in pipeline):
            raise ValueError("Pipeline identity is incomplete")
        for item in pipeline["passes"]:
            if (not isinstance(item, dict) or not _nonempty(item.get("name"))
                    or not _nonempty(item.get("version")) or not isinstance(item.get("parameters"), dict)):
                raise ValueError("Pass version/parameter identity is incomplete")
        if (len(pipeline["sequence"]) != len(pipeline["passes"])
                or any(name not in PASS_NAMES for name in pipeline["sequence"])
                or any(item["name"] != PASS_NAMES[name] for name, item in zip(pipeline["sequence"], pipeline["passes"]))):
            raise ValueError("Sequence and supported pass identities disagree")
    configuration = data["configurations"][0]
    identity = configuration.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("Missing configuration identity")
    _configuration(identity)
    return {"definitions": definitions, "sources": sources, "pipelines": pipelines,
            "configuration": configuration, "observations": data["observations"]}


def _pipeline(pipeline: dict) -> dict:
    return {key: value for key, value in pipeline.items() if key != "id"}


def _configuration_identity(identity: dict, relaxed: bool) -> dict:
    if not relaxed:
        return identity
    return {
        **identity,
        "compiler": {key: value for key, value in identity["compiler"].items() if key not in ("status", "path", "version")},
        "settings": {key: value for key, value in identity["settings"].items() if key not in ("compiler", "optimization", "flags")},
    }


def _shared_passes(left: dict, right: dict) -> bool:
    def by_name(pipeline):
        result = {}
        for item in pipeline["passes"]:
            result.setdefault(item["name"], set()).add(canonical_json({key: value for key, value in item.items() if key != "name"}))
        return result
    left_passes, right_passes = by_name(left), by_name(right)
    return all(left_passes[name] == right_passes[name] for name in left_passes.keys() & right_passes.keys())


def _alignment(left: dict, right: dict, mode: str) -> list[str]:
    relaxed = mode == "configuration"
    if canonical_json(_configuration_identity(left["configuration"]["identity"], relaxed)) != canonical_json(_configuration_identity(right["configuration"]["identity"], relaxed)):
        return ["configuration_mismatch"]
    if mode not in ("program", "pipeline"):
        # Distinct sequences can be unmatched rows. Reusing a sequence name for
        # different pass implementations/parameters is an incompatible contract,
        # even if another row happens to overlap. Sets preserve replicate rows
        # and permit identical multi-parameter fingerprints to compare to self.
        def parameter_sets(info):
            result = {}
            for observation in info["observations"]:
                pipeline = info["pipelines"][observation["pipeline_id"]]
                key = canonical_json({
                    "source": info["sources"][observation["source_id"]]["sha256"],
                    "sequence": pipeline["sequence"],
                    "comparison_kind": pipeline["comparison_kind"],
                    "comparison_source": pipeline["comparison_source"],
                })
                parameters = {"passes": pipeline["passes"], "max_unroll_iterations": pipeline["max_unroll_iterations"]}
                result.setdefault(key, set()).add(canonical_json(parameters))
            return result
        left_parameters, right_parameters = parameter_sets(left), parameter_sets(right)
        if any(left_parameters[key] != right_parameters[key] for key in left_parameters.keys() & right_parameters.keys()):
            return ["pass_version_or_parameters_mismatch"]
        return []
    if len(left["observations"]) != 1 or len(right["observations"]) != 1:
        return [f"{mode}_alignment_requires_single_observation"]
    lo, ro = left["observations"][0], right["observations"][0]
    lp, rp = left["pipelines"][lo["pipeline_id"]], right["pipelines"][ro["pipeline_id"]]
    if mode == "program" and canonical_json(_pipeline(lp)) != canonical_json(_pipeline(rp)):
        return ["program_alignment_requires_same_pipeline"]
    if mode == "pipeline":
        if left["sources"][lo["source_id"]]["sha256"] != right["sources"][ro["source_id"]]["sha256"]:
            return ["pipeline_alignment_requires_same_source"]
        if lp["comparison_kind"] != rp["comparison_kind"] or lp["comparison_source"] != rp["comparison_source"]:
            return ["pipeline_comparison_context_mismatch"]
        if not _shared_passes(lp, rp):
            return ["shared_pass_version_or_parameters_mismatch"]
    return []


def _rows(inspected: dict, explicit: bool) -> dict:
    rows = {}
    for observation in inspected["observations"]:
        key = "explicit_pair" if explicit else canonical_json({
            "source": inspected["sources"][observation["source_id"]]["sha256"],
            "pipeline": _pipeline(inspected["pipelines"][observation["pipeline_id"]]),
        })
        rows.setdefault(key, []).append(observation)
    for records in rows.values():
        records.sort(key=lambda observation: observation["id"])
    return rows


def _relative_difference(left: int | float, right: int | float) -> float:
    if type(left) is int and type(right) is int:
        denominator = abs(left) + abs(right)
        return abs(left - right) / denominator if denominator else 0.0
    scale = max(abs(left), abs(right))
    if scale == 0:
        return 0.0
    left_scaled, right_scaled = left / scale, right / scale
    return abs(left_scaled - right_scaled) / (abs(left_scaled) + abs(right_scaled))


def _dimension(key, name, definition, left_records, right_records, weight):
    reasons = []
    values = []
    for side, records in (("left", left_records), ("right", right_records)):
        if len(records) != 1:
            reasons.append(f"{side}_observation_missing" if not records else f"ambiguous_{side}_replicates")
            feature = None
        else:
            feature = next((item for item in records[0]["features"] if item["name"] == name), None)
            if feature is None:
                reasons.append(f"{side}_feature_missing")
            else:
                if feature["validity"] != "valid":
                    reasons.append(f"{side}_{feature['validity']}")
                eligible = ("deterministic", "observed", "available") if definition["kind"] == "numeric" else ("deterministic", "observed")
                if feature["reliability"] not in eligible:
                    reasons.append(f"{side}_{feature['reliability']}")
                if feature["value"] is None:
                    reasons.append(f"{side}_value_missing")
        values.append(feature)
    left, right = values
    difference = None
    if not reasons:
        difference = (_relative_difference(left["value"], right["value"]) if definition["kind"] == "numeric"
                      else float(left["value"] != right["value"]))
    result = {
        "key": stable_id("dimension", {"row": key, "feature": name}),
        "left_observation_ids": [item["id"] for item in left_records],
        "right_observation_ids": [item["id"] for item in right_records],
        "feature": name, "group": definition["group"], "kind": definition["kind"], "unit": definition["unit"],
        "weight": weight, "usable": not reasons, "reasons": reasons,
        "difference": difference, "contribution": None,
    }
    for side, feature in (("left", left), ("right", right)):
        result.update({f"{side}_{field}": feature[field] if feature else None for field in ("value", "validity", "reliability")})
        result[f"{side}_reasons"] = feature["reasons"] if feature else []
    return result


def compare(left: Fingerprint, right: Fingerprint, config: ComparisonConfig | None = None) -> ComparisonResult:
    """Compare aligned common evidence, exposing every requested exclusion.

    Strict/configuration modes align source SHA-256 and the full ordered pass
    identity. Configuration mode relaxes only compiler path/version and selected
    optimization/flags; target, environment and all other settings remain exact.
    Program/pipeline modes explicitly compare a single observation on each side.
    Replicates sharing an alignment key are excluded instead of silently picked
    or averaged. Coverage counts selected feature definitions over the union of
    row keys. No unreliable or descriptive-only number is ever scored.
    """
    if not isinstance(left, Fingerprint) or not isinstance(right, Fingerprint):
        raise ValueError("compare requires two Fingerprint records")
    config = ComparisonConfig() if config is None else config
    if not isinstance(config, ComparisonConfig):
        raise ValueError("config must be a ComparisonConfig")
    left_data, right_data = left.to_dict(), right.to_dict()
    groups = tuple(group for group in GROUPS if group in (config.groups or GROUPS))
    settings = {"groups": list(groups), "weights": dict(sorted(config.weights)), "min_dimensions": config.min_dimensions}
    result = {
        "schema_version": 1, "kind": ComparisonResult.KIND,
        "feature_schema": FEATURE_SCHEMA, "inputs": {"left": left_data, "right": right_data},
        "comparison_id": stable_id("comparison", {"left": left_data, "right": right_data, "alignment": config.alignment, "settings": settings}),
        "left_fingerprint_id": left_data.get("fingerprint_id"), "right_fingerprint_id": right_data.get("fingerprint_id"),
        "alignment": config.alignment, "method": "weighted_mixed_relative_v1", "settings": settings,
        "status": "incompatible", "distance": None, "similarity": None,
        "usable_dimensions": 0, "requested_dimensions": 0, "coverage": 0.0,
        "dimensions": [], "excluded_observations": [], "incompatibilities": [],
        "interpretation": [
            "Structural features characterize the source program and transformation pipeline, not compiler identity.",
            "Scores describe usable aligned evidence, not semantic equivalence or proof of compiler identification.",
            "Unreliable, descriptive-only, invalid and missing observations do not contribute to a score.",
            "O0 and O2 are optimization configurations and do not establish different compiler products.",
        ],
    }
    inspected = []
    for side, data in (("left", left_data), ("right", right_data)):
        try:
            inspected.append(_inspect(data))
        except ValueError as error:
            result["incompatibilities"].append(f"{side}: {error}")
    if result["incompatibilities"]:
        return ComparisonResult(result)
    left_info, right_info = inspected
    definitions = {**left_info["definitions"], **right_info["definitions"]}
    for name in sorted(left_info["definitions"].keys() & right_info["definitions"].keys()):
        if canonical_json(left_info["definitions"][name]) != canonical_json(right_info["definitions"][name]):
            result["incompatibilities"].append(f"feature_definition_mismatch: {name}")
    result["incompatibilities"].extend(_alignment(left_info, right_info, config.alignment))
    if result["incompatibilities"]:
        return ComparisonResult(result)
    weights = dict(config.weights)
    if weights.keys() - definitions.keys():
        raise ValueError(f"Unknown weight features: {sorted(weights.keys() - definitions.keys())}")
    selected = {name: item for name, item in definitions.items() if item["group"] in groups}
    left_rows = _rows(left_info, config.alignment in ("program", "pipeline"))
    right_rows = _rows(right_info, config.alignment in ("program", "pipeline"))
    for key in sorted(left_rows.keys() | right_rows.keys()):
        lo, ro = left_rows.get(key, []), right_rows.get(key, [])
        if len(lo) != 1 or len(ro) != 1:
            reason = "ambiguous_replicates" if len(lo) > 1 or len(ro) > 1 else "unmatched_observation"
            for side, observations in (("left", lo), ("right", ro)):
                result["excluded_observations"].extend({"side": side, "observation_id": item["id"], "reason": reason} for item in observations)
        for name, definition in sorted(selected.items()):
            result["dimensions"].append(_dimension(key, name, definition, lo, ro, weights.get(name, 1.0)))
    usable = [item for item in result["dimensions"] if item["usable"]]
    result["usable_dimensions"], result["requested_dimensions"] = len(usable), len(result["dimensions"])
    if result["requested_dimensions"]:
        result["coverage"] = len(usable) / result["requested_dimensions"]
    if len(usable) < config.min_dimensions:
        result["status"] = "insufficient_evidence"
    else:
        maximum = max(item["weight"] for item in usable)
        denominator = math.fsum(item["weight"] / maximum for item in usable)
        for item in usable:
            item["contribution"] = (item["weight"] / maximum) * item["difference"] / denominator
        distance = min(1.0, max(0.0, math.fsum(item["contribution"] for item in usable)))
        result.update(status="comparable", distance=distance, similarity=1.0 - distance)
    if config.alignment in ("program", "pipeline"):
        result["interpretation"].append("Explicit cross-program/pipeline differences must not be attributed to compiler behavior.")
    return ComparisonResult(result)

"""Versioned, detached JSON records for descriptive CodeDNA fingerprints.

Records freeze a strict canonical JSON snapshot. Callers receive detached
dictionaries, so modifying an export cannot change its identities or evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

SCHEMA_VERSION = 1
FEATURE_SCHEMA = "codedna.features.v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def stable_id(prefix: str, value: Any) -> str:
    return prefix + "_" + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def finite_number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def strict_loads(text: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    canonical_json(value)  # Also catches overflowing exponent literals.
    if not isinstance(value, dict):
        raise ValueError("A report must be a JSON object")
    return value


class Document:
    KIND = ""

    def __init__(self, data: dict):
        if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION:
            raise ValueError("Unsupported document schema_version")
        if data.get("kind") != self.KIND:
            raise ValueError(f"Expected document kind {self.KIND}")
        if self.KIND in ("codedna.response_matrix", "codedna.fingerprint"):
            _validate_signature(data)
        elif self.KIND == "codedna.comparison":
            _validate_comparison(data)
        self._json = canonical_json(data)

    def to_dict(self) -> dict:
        return json.loads(self._json)

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=True, allow_nan=False)

    @classmethod
    def from_json(cls, text: str):
        return cls(strict_loads(text))


class ResponseMatrix(Document):
    KIND = "codedna.response_matrix"


class Fingerprint(Document):
    KIND = "codedna.fingerprint"


class ComparisonResult(Document):
    KIND = "codedna.comparison"


def _validate_signature(data):
    """Validate shapes, feature types and references before loading saved data.

    Unknown feature-schema strings are retained so comparison can explain a
    schema incompatibility. They cannot acquire compatibility by sharing names.
    """
    if not isinstance(data.get("feature_schema"), str) or not data["feature_schema"]:
        raise ValueError("Missing feature_schema")
    artifact_key = "matrix_id" if data["kind"] == "codedna.response_matrix" else "fingerprint_id"
    if not isinstance(data.get(artifact_key), str) or not data[artifact_key]:
        raise ValueError(f"Missing {artifact_key}")
    for key in ("feature_definitions", "sources", "pipelines", "configurations", "observations"):
        if not isinstance(data.get(key), list) or not all(isinstance(item, dict) for item in data[key]):
            raise ValueError(f"Invalid {key} container")
    definitions = {}
    for definition in data["feature_definitions"]:
        name = definition.get("name")
        if not isinstance(name, str) or not name or name in definitions:
            raise ValueError("Invalid or duplicate feature definition")
        if (definition.get("group") not in ("structural", "compiler", "performance")
                or definition.get("kind") not in ("numeric", "categorical")
                or not isinstance(definition.get("unit"), str)
                or definition.get("rule") != ("relative" if definition["kind"] == "numeric" else "categorical")):
            raise ValueError(f"Invalid feature definition: {name}")
        definitions[name] = definition
    identifiers = {}
    for axis in ("sources", "pipelines", "configurations", "observations"):
        values = [item.get("id") for item in data[axis]]
        if any(not isinstance(value, str) or not value for value in values) or len(values) != len(set(values)):
            raise ValueError(f"Invalid or duplicate {axis} identifiers")
        identifiers[axis] = set(values)
    if data["kind"] == "codedna.fingerprint" and len(data["configurations"]) != 1:
        raise ValueError("A fingerprint must contain exactly one configuration")
    for observation in data["observations"]:
        if not isinstance(observation.get("benchmark_id"), str) or not observation["benchmark_id"]:
            raise ValueError("Missing observation benchmark_id")
        provenance = observation.get("provenance")
        if (not isinstance(provenance, dict) or not isinstance(provenance.get("report_sha256"), str)
                or not isinstance(provenance.get("report"), dict)
                or provenance.get("benchmark_id") != observation["benchmark_id"]):
            raise ValueError("Missing or inconsistent observation provenance")
        for field, axis in (("source_id", "sources"), ("pipeline_id", "pipelines"), ("configuration_id", "configurations")):
            if not isinstance(observation.get(field), str) or observation[field] not in identifiers[axis]:
                raise ValueError(f"Unknown observation {field}")
        if not isinstance(observation.get("features"), list):
            raise ValueError("Missing observation features")
        names = set()
        for feature in observation["features"]:
            if not isinstance(feature, dict) or not isinstance(feature.get("name"), str) or feature["name"] not in definitions or feature["name"] in names:
                raise ValueError("Unknown or duplicate observation feature")
            names.add(feature["name"])
            if feature.get("validity") not in ("valid", "missing", "invalid", "not_applicable"):
                raise ValueError("Invalid feature validity")
            if feature.get("reliability") not in ("deterministic", "observed", "unreliable", "descriptive_only", "unavailable", "available"):
                raise ValueError("Invalid feature reliability")
            reasons = feature.get("reasons")
            if not isinstance(reasons, list) or not all(isinstance(reason, str) for reason in reasons):
                raise ValueError("Invalid feature reasons")
            value = feature.get("value")
            kind = definitions[feature["name"]]["kind"]
            if value is not None and ((kind == "numeric" and not finite_number(value)) or (kind == "categorical" and not isinstance(value, str))):
                raise ValueError("Invalid feature value type")
            if feature["validity"] == "valid" and value is None:
                raise ValueError("A valid feature cannot have a missing value")
            feature_provenance = feature.get("provenance")
            if (not isinstance(feature_provenance, dict)
                    or any(not isinstance(feature_provenance.get(key), str) or not feature_provenance[key] for key in ("observation_id", "report_sha256", "pointer"))):
                raise ValueError("Missing feature provenance")


def _validate_comparison(data):
    for key in ("comparison_id", "left_fingerprint_id", "right_fingerprint_id", "alignment", "method"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValueError(f"Missing comparison {key}")
    if data.get("status") not in ("comparable", "insufficient_evidence", "incompatible"):
        raise ValueError("Invalid comparison status")
    for key in ("dimensions", "excluded_observations", "incompatibilities", "interpretation"):
        if not isinstance(data.get(key), list):
            raise ValueError(f"Invalid comparison {key}")
    if not isinstance(data.get("settings"), dict):
        raise ValueError("Missing comparison settings")
    inputs = data.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("Missing comparison inputs")
    for side in ("left", "right"):
        if not isinstance(inputs.get(side), dict) or inputs[side].get("kind") != Fingerprint.KIND:
            raise ValueError("Comparison inputs must be complete fingerprints")
        _validate_signature(inputs[side])
    for key in ("usable_dimensions", "requested_dimensions"):
        if type(data.get(key)) is not int or data[key] < 0:
            raise ValueError(f"Invalid comparison {key}")
    if data["requested_dimensions"] != len(data["dimensions"]) or data["usable_dimensions"] > data["requested_dimensions"]:
        raise ValueError("Inconsistent comparison dimension counts")
    for key in ("coverage", "distance", "similarity"):
        value = data.get(key)
        if value is not None and (not finite_number(value) or not 0 <= value <= 1):
            raise ValueError(f"Invalid comparison {key}")
    if data.get("coverage") is None:
        raise ValueError("Missing comparison coverage")
    if data["status"] == "comparable":
        if data.get("distance") is None or data.get("similarity") is None:
            raise ValueError("Comparable evidence requires defined scores")
    elif data.get("distance") is not None or data.get("similarity") is not None:
        raise ValueError("Unavailable comparisons cannot have scores")
    usable = 0
    for dimension in data["dimensions"]:
        if not isinstance(dimension, dict):
            raise ValueError("Invalid comparison dimension")
        if any(key not in dimension for key in ("key", "feature", "group", "kind", "unit", "usable", "reasons", "difference", "contribution")):
            raise ValueError("Incomplete comparison dimension")
        if type(dimension["usable"]) is not bool or not isinstance(dimension["reasons"], list):
            raise ValueError("Invalid comparison dimension availability")
        usable += dimension["usable"]
        for key in ("difference", "contribution"):
            value = dimension[key]
            if value is not None and (not finite_number(value) or not 0 <= value <= 1):
                raise ValueError(f"Invalid comparison dimension {key}")
    if usable != data["usable_dimensions"]:
        raise ValueError("Inconsistent usable dimension count")
    for excluded in data["excluded_observations"]:
        if not isinstance(excluded, dict) or any(not isinstance(excluded.get(key), str) for key in ("side", "observation_id", "reason")):
            raise ValueError("Invalid excluded observation")
    if not all(isinstance(reason, str) for reason in data["incompatibilities"]):
        raise ValueError("Invalid incompatibility reasons")

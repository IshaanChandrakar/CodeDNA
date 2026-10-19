"""Strict Phase 6 documents and long-form CSV with input-preserving exports.

JSON is the lossless interchange format. CSV retains explicit units, validity,
reliability and provenance so missing or excluded evidence stays distinguishable
from a genuine numerical zero. Replacement is atomic per file, not across files.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

from fingerprint.models import (
    ComparisonResult, Document, Fingerprint, ResponseMatrix, canonical_json,
    strict_loads,
)
from runtime.benchmark_storage import validate_output_paths


FEATURE_COLUMNS = (
    "artifact_kind", "artifact_id", "observation_id", "benchmark_id",
    "source_id", "pipeline_id", "configuration_id", "feature", "group",
    "kind", "unit", "value", "validity", "reliability", "reasons", "provenance",
)
COMPARISON_COLUMNS = (
    "artifact_kind", "artifact_id", "status", "row_type", "dimension_key",
    "left_fingerprint_id", "right_fingerprint_id", "left_observation_ids",
    "right_observation_ids", "feature", "group", "kind", "unit", "left_value",
    "right_value", "left_validity", "right_validity", "left_reliability",
    "right_reliability", "left_reasons", "right_reasons", "weight", "usable", "reasons", "difference",
    "contribution", "side", "observation_id", "distance", "similarity",
    "usable_dimensions", "requested_dimensions", "coverage",
)


@dataclass(frozen=True, slots=True)
class ExportPaths:
    json_path: Path
    csv_path: Path | None = None


def _document(data: dict) -> Document:
    classes = {cls.KIND: cls for cls in (ResponseMatrix, Fingerprint, ComparisonResult)}
    document_class = classes.get(data.get("kind"))
    if document_class is None:
        raise ValueError("Unsupported Phase 6 document kind")
    return document_class(data)


def load_document(path: Path | str) -> Document:
    """Read a strict versioned matrix, fingerprint or comparison JSON document."""
    return _document(strict_loads(Path(path).read_text(encoding="utf-8")))


def _data(document: Document | dict) -> dict:
    # Revalidate even a caller-supplied object rather than trusting duck typing.
    data = document if isinstance(document, dict) else document.to_dict()
    return _document(data).to_dict()


def feature_rows(document: Document | dict) -> list[dict]:
    """Return one typed row per observation/feature, retaining unavailable data."""
    data = _data(document)
    if data["kind"] not in (ResponseMatrix.KIND, Fingerprint.KIND):
        raise ValueError("Feature rows require a response matrix or fingerprint")
    definitions = {definition["name"]: definition for definition in data["feature_definitions"]}
    identifier = data["fingerprint_id"] if data["kind"] == Fingerprint.KIND else data["matrix_id"]
    rows = []
    for observation in sorted(data["observations"], key=lambda item: (
        item["source_id"], item["pipeline_id"], item["configuration_id"], item["id"],
    )):
        for feature in sorted(observation["features"], key=lambda item: item["name"]):
            definition = definitions[feature["name"]]
            row = {
                "artifact_kind": data["kind"], "artifact_id": identifier,
                "observation_id": observation["id"],
                "benchmark_id": observation["benchmark_id"],
                **{name: observation[name] for name in ("source_id", "pipeline_id", "configuration_id")},
                "feature": feature["name"],
                **{name: definition[name] for name in ("group", "kind", "unit")},
                **{name: feature[name] for name in ("value", "validity", "reliability", "reasons", "provenance")},
            }
            rows.append({name: row[name] for name in FEATURE_COLUMNS})
    return rows


def comparison_rows(document: Document | dict) -> list[dict]:
    """Expose used/excluded dimensions and observations without inventing scores."""
    data = _data(document)
    if data["kind"] != ComparisonResult.KIND:
        raise ValueError("Comparison rows require a comparison document")
    base = {
        "artifact_kind": data["kind"], "artifact_id": data["comparison_id"],
        **{name: data[name] for name in (
            "status", "left_fingerprint_id", "right_fingerprint_id", "distance",
            "similarity", "usable_dimensions", "requested_dimensions", "coverage",
        )},
    }
    rows = []
    for dimension in sorted(data["dimensions"], key=lambda item: canonical_json(item["key"])):
        row = {**base, "row_type": "dimension", "dimension_key": dimension["key"]}
        row.update({name: dimension.get(name) for name in (
            "left_observation_ids", "right_observation_ids", "feature", "group",
            "kind", "unit", "left_value", "right_value", "left_validity",
            "right_validity", "left_reliability", "right_reliability", "left_reasons", "right_reasons", "weight",
            "usable", "reasons", "difference", "contribution",
        )})
        rows.append(row)
    for excluded in sorted(data["excluded_observations"], key=lambda item: (
        item["side"], item["observation_id"], item["reason"],
    )):
        rows.append({**base, "row_type": "excluded_observation", "usable": False,
                     "side": excluded["side"], "observation_id": excluded["observation_id"],
                     "reasons": [excluded["reason"]]})
    for reason in data["incompatibilities"]:
        rows.append({**base, "row_type": "incompatibility", "usable": False, "reasons": [reason]})
    if not rows:
        rows.append({**base, "row_type": "summary"})
    return [{name: row.get(name) for name in COMPARISON_COLUMNS} for row in rows]


def document_rows(document: Document | dict) -> list[dict]:
    data = _data(document)
    return comparison_rows(data) if data["kind"] == ComparisonResult.KIND else feature_rows(data)


def _cell(value):
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (dict, list, tuple)):
        return canonical_json(value)
    return value


def _csv_payload(data: dict) -> str:
    columns = COMPARISON_COLUMNS if data["kind"] == ComparisonResult.KIND else FEATURE_COLUMNS
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    for row in document_rows(data):
        writer.writerow({key: _cell(value) for key, value in row.items()})
    return stream.getvalue()


def _atomic_write(payloads: Iterable[tuple[Path, str]]) -> None:
    prepared = []
    try:
        for destination, payload in payloads:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=destination.parent,
                prefix=f".{destination.name}.", suffix=".tmp", delete=False,
            )
            temporary_path = Path(temporary.name)
            prepared.append((temporary_path, destination))
            with temporary:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
        for temporary_path, destination in prepared:
            os.replace(temporary_path, destination)
    finally:
        for temporary_path, _ in prepared:
            temporary_path.unlink(missing_ok=True)


def save_document(
    document: Document | dict, json_path: Path | str, *,
    csv_path: Path | str | None = None, protected_paths: Iterable[Path | str] = (),
) -> ExportPaths:
    """Preflight and serialize every export before creating or replacing files."""
    paths = validate_output_paths(
        [json_path, *([csv_path] if csv_path is not None else [])], protected_paths,
    )
    data = _data(document)
    validated = _document(data)
    payloads = [(paths[0], validated.to_json() + "\n")]
    if csv_path is not None:
        payloads.append((paths[1], _csv_payload(data)))
    _atomic_write(payloads)
    return ExportPaths(paths[0], paths[1] if csv_path is not None else None)

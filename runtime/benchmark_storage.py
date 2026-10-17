"""Benchmark report persistence with explicit schemas and safe atomic files.

Every destination is checked before parent directories or temporary files are
created.  All files are prepared before replacement.  Replacement is atomic per
file; exporting several files is deliberately not a cross-file transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
import csv
from io import StringIO
import json
import os
from pathlib import Path
import stat
from tempfile import NamedTemporaryFile
from typing import Iterable


SAMPLE_COLUMNS = (
    "benchmark_id", "phase", "order_index", "round_index", "variant",
    "duration_ns", "duration_unit", "measurement_scope", "status",
    "matches_expected", "valid", "return_value", "process_returncode", "signal",
    "stdout", "stderr", "detail", "issue",
)
SUMMARY_COLUMNS = (
    "benchmark_id", "benchmark_status", "variant", "expected_samples",
    "attempted_samples", "successful_samples", "summary_status", "median_ns",
    "mean_ns", "min_ns", "max_ns", "stdev_ns", "q1_ns", "q3_ns", "iqr_ns",
    "coefficient_of_variation", "duration_unit", "comparison_status", "speedup",
    "percentage_change", "issues", "hardware_instructions", "hardware_instructions_status",
)


@dataclass(frozen=True, slots=True)
class ExportPaths:
    json_path: Path
    samples_csv: Path | None = None
    summary_csv: Path | None = None


def _destination(path: Path | str) -> Path:
    destination = Path(path)
    if destination.name in {"", ".", ".."}:
        raise ValueError("An export destination must include a filename")
    try:
        information = destination.lstat()
    except FileNotFoundError:
        information = None
    if information is not None:
        if stat.S_ISLNK(information.st_mode):
            raise ValueError(f"Export destinations must not be symlinks: {destination}")
        if not stat.S_ISREG(information.st_mode):
            raise ValueError(f"An export destination must be a regular file, not a directory or special file: {destination}")
    for parent in (destination.parent, *destination.parent.parents):
        try:
            information = parent.stat()
        except FileNotFoundError:
            if parent.is_symlink():
                raise ValueError(f"An export parent must be a directory: {parent}")
            continue
        if not stat.S_ISDIR(information.st_mode):
            raise ValueError(f"An export parent must be a directory: {parent}")
    return destination


def _aliases(left: Path, right: Path) -> bool:
    if left.resolve() == right.resolve():
        return True
    try:
        return left.samefile(right)
    except FileNotFoundError:
        return False


def _preflight_paths(
    destinations: Iterable[Path | str], protected_paths: Iterable[Path | str] = (),
) -> tuple[Path, ...]:
    paths = tuple(_destination(path) for path in destinations)
    protected = tuple(Path(path) for path in protected_paths)
    resolved = tuple(path.resolve() for path in paths)
    for index, path in enumerate(paths):
        if any(_aliases(path, source) for source in protected):
            raise ValueError(f"Export would overwrite a protected input: {path}")
        for earlier_index, earlier in enumerate(paths[:index]):
            if _aliases(path, earlier):
                raise ValueError(f"Export destinations must not alias one another: {earlier} and {path}")
            if resolved[index] in resolved[earlier_index].parents or resolved[earlier_index] in resolved[index].parents:
                raise ValueError(f"An export destination cannot contain another export destination: {earlier} and {path}")
    return paths


def validate_output_paths(
    paths: Iterable[Path | str], protected_paths: Iterable[Path | str] = (),
) -> tuple[Path, ...]:
    """Validate all output aliases and file types without changing the filesystem.

    Protected inputs may themselves be symlinks or hardlinks.  Existing regular
    output files can be replaced, but final output symlinks are always refused.
    Parent-directory symlinks are resolved for collision checks; no filesystem
    security sandbox or protection against concurrent hostile path changes is
    implied.
    """
    return _preflight_paths(paths, protected_paths)


def _atomic_write(payloads: Iterable[tuple[Path, str]]) -> None:
    """Prepare every sibling temp before replacing any validated destination."""
    prepared: list[tuple[Path, Path]] = []
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


def _raw_rows(data: dict) -> list[dict]:
    rows = []
    for sample in data["benchmark"]["samples"]:
        execution = sample["execution"]
        row = {
            "benchmark_id": data["benchmark_id"],
            **{name: sample[name] for name in (
                "phase", "order_index", "round_index", "variant", "duration_ns",
                "duration_unit", "measurement_scope", "matches_expected", "valid", "issue",
            )},
            **{name: execution[name] for name in (
                "status", "return_value", "process_returncode", "signal", "stdout", "stderr", "detail",
            )},
        }
        rows.append({name: row[name] for name in SAMPLE_COLUMNS})
    return rows


def raw_rows(report) -> list[dict]:
    """Return warmup and measured observations in their recorded execution order.

    Values retain their Python types: missing durations remain ``None`` and real
    zero measurements remain zero.  No observation is filtered or synthesized.
    """
    return _raw_rows(report.to_dict())


def _summary_rows(data: dict) -> list[dict]:
    benchmark = data["benchmark"]
    comparison = benchmark["comparison"]
    hardware = benchmark["metrics"]["hardware_instructions"]
    rows = []
    for variant in ("original", "transformed"):
        if variant not in benchmark["groups"]:
            continue
        group = benchmark["groups"][variant]
        summary = group["summary"]
        # Preserve source order of issue codes, with shared codes listed once.
        issues = dict.fromkeys((*comparison["issues"], *summary["issues"]))
        row = {
            "benchmark_id": data["benchmark_id"],
            "benchmark_status": benchmark["status"],
            "variant": variant,
            **{name: group[name] for name in (
                "expected_samples", "attempted_samples", "successful_samples",
            )},
            "summary_status": summary["status"],
            **{name: summary[name] for name in (
                "median_ns", "mean_ns", "min_ns", "max_ns", "stdev_ns", "q1_ns",
                "q3_ns", "iqr_ns", "coefficient_of_variation",
            )},
            "duration_unit": benchmark["settings"]["duration_unit"],
            "comparison_status": comparison["status"],
            "speedup": comparison["speedup"],
            "percentage_change": comparison["percentage_change"],
            "issues": ";".join(issues),
            "hardware_instructions": hardware["value"],
            "hardware_instructions_status": hardware["status"],
        }
        rows.append({name: row[name] for name in SUMMARY_COLUMNS})
    return rows


def summary_rows(report) -> list[dict]:
    """Return original then transformed aggregate groups with explicit missing data."""
    return _summary_rows(report.to_dict())


def _csv_payload(columns: tuple[str, ...], rows: list[dict]) -> str:
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            name: "" if value is None else "true" if value is True else "false" if value is False else value
            for name, value in row.items()
        })
    return stream.getvalue()


def save_report(
    report, json_path: Path | str, *, samples_csv: Path | str | None = None,
    summary_csv: Path | str | None = None, protected_paths: Iterable[Path | str] = (),
) -> ExportPaths:
    """Save canonical JSON and optional raw/summary CSV without losing observations.

    The report is read once through ``to_dict``.  JSON uses the typed report's
    canonical formatting with ``allow_nan=False``; CSV uses fixed columns,
    lowercase booleans and blank missing values.  Serialization and all path
    checks complete before any directory is created.  All temporary files are
    prepared before the first per-file atomic replacement; several replacements
    are not an all-or-nothing transaction.
    """
    requested = [json_path]
    if samples_csv is not None:
        requested.append(samples_csv)
    if summary_csv is not None:
        requested.append(summary_csv)
    validated = iter(validate_output_paths(requested, protected_paths))
    destinations = ExportPaths(
        next(validated), next(validated) if samples_csv is not None else None,
        next(validated) if summary_csv is not None else None,
    )
    data = report.to_dict()
    payloads = [(destinations.json_path, json.dumps(data, indent=2, ensure_ascii=True, allow_nan=False) + "\n")]
    if destinations.samples_csv is not None:
        payloads.append((destinations.samples_csv, _csv_payload(SAMPLE_COLUMNS, _raw_rows(data))))
    if destinations.summary_csv is not None:
        payloads.append((destinations.summary_csv, _csv_payload(SUMMARY_COLUMNS, _summary_rows(data))))
    _atomic_write(payloads)
    return destinations

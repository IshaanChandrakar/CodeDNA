"""Report-only Phase 6 commands on the established ``python -m compiler`` CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from fingerprint.models import ComparisonResult, Fingerprint, ResponseMatrix, strict_loads
from fingerprint.storage import feature_rows, load_document, save_document
from runtime.benchmark_storage import validate_output_paths


def add_arguments(parser: argparse.ArgumentParser, modes) -> None:
    modes.add_argument("--matrix", action="store_true", help="Build a response matrix from saved benchmark reports; no compilation")
    modes.add_argument("--fingerprint", action="store_true", help="Extract one configuration's fingerprint from a matrix or saved benchmark reports")
    modes.add_argument("--compare-fingerprints", action="store_true", help="Compare saved fingerprints using explicit feature alignment")
    parser.add_argument("--benchmark-report", action="append", type=Path, default=[], help="Saved Phase 5 JSON; repeat to import multiple observations")
    parser.add_argument("--configuration", help="Configuration identifier to select when extracting a fingerprint")
    parser.add_argument("--source-id", action="append", default=[], help="Filter extracted observations by source identifier; repeat for a union")
    parser.add_argument("--pipeline-id", action="append", default=[], help="Filter extracted observations by pipeline identifier; repeat for a union")
    parser.add_argument("--observation-id", action="append", default=[], help="Filter extracted observations by observation identifier; repeat for a union")
    parser.add_argument("--alignment", choices=("strict", "configuration", "program", "pipeline"), help="Fingerprint dimensions to align (default strict)")
    parser.add_argument("--feature-group", action="append", choices=("structural", "compiler", "performance"), default=[], help="Comparison feature group; repeat to select multiple groups")
    parser.add_argument("--weight", action="append", default=[], metavar="FEATURE=NUMBER", help="Positive finite comparison weight for a named feature")
    parser.add_argument("--min-dimensions", type=int, help="Minimum usable comparison dimensions (default 2)")
    parser.add_argument("--inspect-features", action="store_true", help="Also display readable feature validity/reliability and exclusion reasons")


def _summary(document) -> str:
    data = document.to_dict()
    if data["kind"] == ComparisonResult.KIND:
        score = "unavailable" if data["similarity"] is None else str(data["similarity"])
        return (f"Fingerprint comparison: {data['status']}; {data['usable_dimensions']}/"
                f"{data['requested_dimensions']} usable dimensions; similarity {score}.\n"
                "Similarity is descriptive evidence, not semantic equivalence or compiler identification.")
    label = "Response matrix" if data["kind"] == ResponseMatrix.KIND else "Fingerprint"
    identifier = data["fingerprint_id"] if data["kind"] == Fingerprint.KIND else data["matrix_id"]
    rows = feature_rows(document)
    missing = sum(row["value"] is None for row in rows)
    unreliable = sum(row["reliability"] in ("unreliable", "descriptive_only", "unavailable") for row in rows)
    lines = [f"{label} {identifier}: {len(data['observations'])} observations, {len(rows)} features; "
             f"{missing} missing values, {unreliable} features marked unreliable/descriptive/unavailable."]
    for configuration in data["configurations"]:
        identity = configuration["identity"]
        version = identity["compiler"].get("version")
        compiler = version.splitlines()[0] if version else identity["compiler"].get("status", "unavailable")
        optimization = identity["settings"].get("optimization", "unavailable")
        lines.append(f"Configuration {configuration['id']}: opt={optimization}; compiler={compiler}.")
    return "\n".join(lines)


def _inspection(document) -> str:
    data = document.to_dict()
    if data["kind"] == ComparisonResult.KIND:
        lines = []
        for dimension in data["dimensions"]:
            left = dimension["left_value"] if dimension["left_value"] is not None else "missing"
            right = dimension["right_value"] if dimension["right_value"] is not None else "missing"
            difference = dimension["difference"] if dimension["difference"] is not None else "unavailable"
            lines.append(
                f"{dimension['feature']}: {'used' if dimension['usable'] else 'excluded'}; "
                f"left={left}; right={right}; unit={dimension['unit']}; difference={difference}; "
                f"reasons={dimension['reasons']}; left_reasons={dimension.get('left_reasons', [])}; "
                f"right_reasons={dimension.get('right_reasons', [])}"
            )
        lines.extend(f"{item['side']} observation {item['observation_id']}: excluded; {item['reason']}"
                     for item in data["excluded_observations"])
        lines.extend(f"Incompatible: {reason}" for reason in data["incompatibilities"])
    else:
        lines = [f"{row['observation_id']} / {row['feature']}: "
                 f"{row['value'] if row['value'] is not None else 'missing'} {row['unit']}; "
                 f"validity={row['validity']}; reliability={row['reliability']}; "
                 f"reasons={row['reasons']}" for row in feature_rows(document)]
    return "\n".join(lines) if lines else "No feature observations are present."


def handle_if_requested(options, parser: argparse.ArgumentParser) -> int | None:
    """Dispatch before legacy C-source validation; return None for old modes."""
    active = options.matrix or options.fingerprint or options.compare_fingerprints
    dedicated = (options.benchmark_report or options.configuration is not None
                 or options.source_id or options.pipeline_id or options.observation_id
                 or options.alignment is not None or options.feature_group or options.weight
                 or options.min_dimensions is not None or options.inspect_features)
    if not active:
        if dedicated:
            parser.error("matrix/fingerprint options require --matrix, --fingerprint or --compare-fingerprints")
        return None
    if options.transform or any(value is not None for value in (
        options.max_unroll, options.format, options.clang, options.opt,
        options.compile_timeout, options.execution_timeout, options.sanitize,
        options.warmups, options.repetitions, options.samples_csv, options.summary_csv,
    )):
        parser.error("Phase 6 report commands cannot use C transformation, graph or execution options")
    if options.csv and options.output is None:
        parser.error("Phase 6 --csv requires --output for JSON and its CSV sidecar")
    extracting = options.fingerprint
    if not extracting and (options.configuration is not None or options.source_id
                           or options.pipeline_id or options.observation_id):
        parser.error("configuration/source/pipeline/observation selection requires --fingerprint")
    if not options.compare_fingerprints and (options.alignment is not None or options.feature_group
                                            or options.weight or options.min_dimensions is not None):
        parser.error("alignment, feature-group, weight and minimum-dimension options require --compare-fingerprints")
    if options.matrix:
        if options.source is not None or options.against is not None or not options.benchmark_report:
            parser.error("--matrix requires --benchmark-report and accepts no positional source or --against")
    elif options.fingerprint:
        if options.against is not None:
            parser.error("--against requires --compare-fingerprints in Phase 6")
        if bool(options.source) == bool(options.benchmark_report):
            parser.error("--fingerprint requires either a matrix JSON file or --benchmark-report inputs")
    elif options.source is None or options.against is None or options.benchmark_report:
        parser.error("--compare-fingerprints requires a left fingerprint JSON and --against right JSON")

    inputs = [*options.benchmark_report,
              *([options.source] if options.source is not None else []),
              *([options.against] if options.against is not None else [])]
    csv_path = options.output.with_suffix(".csv") if options.csv else None
    try:
        if options.output is not None:
            validate_output_paths([options.output, *([csv_path] if csv_path is not None else [])], inputs)
        if options.compare_fingerprints:
            from fingerprint.similarity import ComparisonConfig, compare

            weights = []
            for specification in options.weight:
                name, separator, number = specification.partition("=")
                if not separator or not name or not number:
                    raise ValueError("--weight must be FEATURE=NUMBER")
                try:
                    weights.append((name, float(number)))
                except ValueError as error:
                    raise ValueError("--weight must be FEATURE=NUMBER with a positive finite number") from error
            config = ComparisonConfig(
                alignment=options.alignment or "strict",
                groups=tuple(options.feature_group) if options.feature_group else ("structural", "compiler", "performance"),
                weights=tuple(weights), min_dimensions=2 if options.min_dimensions is None else options.min_dimensions,
            )
            left, right = load_document(options.source), load_document(options.against)
            if not isinstance(left, Fingerprint) or not isinstance(right, Fingerprint):
                raise ValueError("--compare-fingerprints inputs must both be fingerprint documents")
            document = compare(left, right, config)
        else:
            from fingerprint.extraction import extract_fingerprint
            from fingerprint.matrix import build_matrix

            if options.benchmark_report:
                matrix = build_matrix(strict_loads(path.read_text(encoding="utf-8")) for path in options.benchmark_report)
            else:
                matrix = load_document(options.source)
                if not isinstance(matrix, ResponseMatrix):
                    raise ValueError("--fingerprint positional input must be a response matrix")
            document = matrix if options.matrix else extract_fingerprint(
                matrix, configuration_id=options.configuration,
                source_ids=options.source_id or None, pipeline_ids=options.pipeline_id or None,
                observation_ids=options.observation_id or None,
            )
        if options.output is None:
            print(document.to_json())
            if options.inspect_features:
                print(_summary(document), file=sys.stderr)
                print(_inspection(document), file=sys.stderr)
        else:
            exports = save_document(document, options.output, csv_path=csv_path, protected_paths=inputs)
            print(_summary(document))
            if options.inspect_features:
                print(_inspection(document))
            print(f"Saved {exports.json_path}")
            if exports.csv_path is not None:
                print(f"Saved {exports.csv_path}")
        if isinstance(document, ComparisonResult):
            return 0 if document.to_dict()["status"] == "comparable" else 6
        return 0
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
        print(f"Phase 6 report error: {error}", file=sys.stderr)
        return 2
    except RecursionError:
        print("Phase 6 report error: document nesting exceeds Python's recursion limit", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Phase 6 report operation interrupted", file=sys.stderr)
        return 130

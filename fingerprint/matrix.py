"""Import Phase 5 evidence without compiling, executing or changing its schema."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import re

from compiler.cfg import build_cfg
from compiler.diagnostics import FrontendError
from compiler.ir import Binary, Label, lower_ir
from compiler.parser import parse
from fingerprint.models import FEATURE_SCHEMA, ResponseMatrix, canonical_json, finite_number, stable_id
from runtime.benchmark_statistics import compare_summaries, summarize
from runtime.models import CompileConfig

STATISTICS = ("expressions_folded", "references_propagated", "loops_unrolled", "iterations_expanded", "changed_nodes")
PASS_REPORT_NAMES = {"constants": "constant_propagation_folding", "unroll": "loop_unrolling"}


def _definition(name, group, kind, unit, description):
    return {"name": name, "group": group, "kind": kind, "unit": unit,
            "description": description, "rule": "relative" if kind == "numeric" else "categorical"}


FEATURE_DEFINITIONS = tuple(sorted([
    _definition("pipeline.status", "structural", "categorical", "status_sequence", "Ordered reported pass statuses; no pass is not_applicable."),
    *[_definition(f"pipeline.{name}", "structural", "numeric", "count", f"Sum of committed {name} across the ordered reports; no selected pass is missing.") for name in STATISTICS],
    _definition("tac.original.operations", "structural", "numeric", "tac_operations", "Non-Label TAC instructions lowered from saved original canonical C."),
    _definition("tac.transformed.operations", "structural", "numeric", "tac_operations", "Non-Label TAC instructions lowered from saved transformed canonical C."),
    _definition("tac.delta.operations", "structural", "numeric", "tac_operations", "Transformed minus original static TAC operations; never hardware instructions."),
    _definition("tac.response.operations", "structural", "numeric", "fraction", "(transformed-original)/positive original TAC count; missing without an applied pass."),
    *[_definition(f"tac.{variant}.binary", "structural", "numeric", "tac_binary_operations", f"Binary instructions in TAC reparsed from saved {variant} canonical C.") for variant in ("original", "transformed")],
    *[_definition(f"cfg.{variant}.blocks", "structural", "numeric", "basic_blocks", f"Real basic blocks, excluding synthetic entry/exit, from saved {variant} canonical C.") for variant in ("original", "transformed")],
    *[_definition(f"compiler.{variant}.{stage}", "compiler", "categorical", "status", f"Recorded {variant} {stage} status, including failures.") for variant in ("original", "transformed") for stage in ("compilation", "execution")],
    _definition("compiler.equivalence", "compiler", "categorical", "status", "Phase 4 observed-equivalence outcome, not a proof."),
    _definition("compiler.benchmark_status", "compiler", "categorical", "status", "Phase 5 benchmark schedule outcome, not performance reliability."),
    *[_definition(f"performance.{variant}.median_ns", "performance", "numeric", "ns", f"Observed {variant} end-to-end process median; startup/harness included.") for variant in ("original", "transformed")],
    _definition("performance.median_ratio", "performance", "numeric", "ratio", "Recorded original/transformed process median ratio, not computational speedup."),
    _definition("performance.duration_response", "performance", "numeric", "fraction", "(transformed-original)/positive original process median; inherits timing reliability."),
    _definition("performance.hardware_instructions", "performance", "numeric", "hardware_instructions", "Unavailable: Phase 5 has no reliable hardware-counter backend."),
], key=lambda item: item["name"]))


def normalize_response(baseline, variant) -> float | None:
    """A fractional response needs a positive finite baseline and finite v>=0."""
    if not finite_number(baseline) or not finite_number(variant) or baseline <= 0 or variant < 0:
        return None
    try:
        result = (variant - baseline) / baseline
        return result if math.isfinite(result) else None
    except (OverflowError, ZeroDivisionError):
        return None


def _require(condition, description):
    if not condition:
        raise ValueError(f"Invalid Phase 5 benchmark report: {description}")


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_report(data):
    _require(isinstance(data, dict), "expected an object")
    canonical_json(data)
    _require(type(data.get("schema_version")) is int and data["schema_version"] == 1, "unsupported schema_version")
    _require(isinstance(data.get("benchmark_id"), str) and bool(data["benchmark_id"]), "benchmark_id")
    for name in ("analysis", "environment_metadata", "benchmark"):
        _require(isinstance(data.get(name), dict), name)
    analysis, environment, benchmark = data["analysis"], data["environment_metadata"], data["benchmark"]
    _require(isinstance(analysis.get("source"), dict) and _hash(analysis["source"].get("sha256")), "source SHA-256")
    _require(isinstance(analysis["source"].get("name"), str), "source name")
    _require(isinstance(analysis.get("outcome"), str), "equivalence outcome")
    _require(analysis.get("comparison_kind") in ("transformation_pipeline", "independent_sources"), "comparison kind")
    _require(type(analysis.get("accepted_transformation")) is bool, "accepted_transformation")
    sequence, reports = analysis.get("sequence"), analysis.get("transformation_reports")
    _require(isinstance(sequence, list) and all(isinstance(name, str) and name in PASS_REPORT_NAMES for name in sequence), "transformation sequence")
    _require(isinstance(reports, list) and len(reports) == len(sequence), "ordered transformation reports")
    for name, report in zip(sequence, reports):
        _require(isinstance(report, dict) and report.get("name") == PASS_REPORT_NAMES[name], "pass name/order")
        _require(isinstance(report.get("version"), str) and bool(report["version"]), "pass version")
        _require(report.get("status") in ("applied", "rejected", "not_applicable"), "pass status")
        _require(isinstance(report.get("parameters"), dict), "pass parameters")
        _require(isinstance(report.get("statistics"), dict), "pass statistics")
        for statistic in STATISTICS:
            value = report["statistics"].get(statistic)
            _require(type(value) is int and value >= 0, f"nonnegative integer {statistic}")
            if report["status"] != "applied":
                _require(value == 0, "non-applied pass has committed statistics")
    _require(analysis["accepted_transformation"] == any(report["status"] == "applied" for report in reports), "accepted pass status disagreement")
    _require(isinstance(analysis.get("settings"), dict), "analysis settings")
    settings = analysis["settings"]
    required = ("compiler", "standard", "optimization", "flags", "compile_timeout_seconds", "execution_timeout_seconds", "sanitizer_requested", "max_output_bytes", "memory_limit_mb", "max_unroll_iterations", "target", "observation_protocol", "case")
    _require(all(key in settings for key in required), "incomplete configuration")
    _require(settings["optimization"] in ("O0", "O2") and settings["standard"] == "c11", "supported compiler configuration")
    _require(isinstance(settings["flags"], list) and all(isinstance(flag, str) for flag in settings["flags"]), "compiler flags")
    _require(type(settings["sanitizer_requested"]) is bool, "sanitizer request")
    _require(type(settings["max_unroll_iterations"]) is int and 0 <= settings["max_unroll_iterations"] <= 1024, "max_unroll_iterations")
    for key in ("compile_timeout_seconds", "execution_timeout_seconds"):
        _require(finite_number(settings[key]) and settings[key] > 0, key)
    _require(isinstance(settings["case"], dict), "execution case")
    _require(type(settings["observation_protocol"]) is int and settings["observation_protocol"] == 1, "observation protocol")
    _require(type(settings["max_output_bytes"]) is int and settings["max_output_bytes"] > 0, "output limit")
    _require(settings["memory_limit_mb"] is None or type(settings["memory_limit_mb"]) is int and settings["memory_limit_mb"] > 0, "memory limit")
    _require(all(isinstance(settings[key], str) and settings[key] for key in ("compiler", "target")), "compiler/target identity")
    prefix_length = 4 if settings["sanitizer_requested"] else 2
    try:
        compile_config = CompileConfig(
            compiler=settings["compiler"], optimization=settings["optimization"],
            compile_timeout=settings["compile_timeout_seconds"], execution_timeout=settings["execution_timeout_seconds"],
            sanitize=settings["sanitizer_requested"], max_output_bytes=settings["max_output_bytes"],
            memory_limit_mb=settings["memory_limit_mb"], extra_flags=tuple(settings["flags"][prefix_length:]),
        )
        _require(list(compile_config.flags) == settings["flags"], "flags disagree with configuration")
    except ValueError as error:
        raise ValueError(f"Invalid Phase 5 benchmark report: compiler flags/configuration: {error}") from error
    _require(all(key in environment for key in ("compiler", "platform", "machine", "python", "clock")), "incomplete environment")
    _require(isinstance(environment["compiler"], dict) and isinstance(environment["compiler"].get("status"), str), "compiler discovery")
    _require(all(environment["compiler"].get(key) is None or isinstance(environment["compiler"][key], str) for key in ("path", "version")), "compiler path/version")
    _require(isinstance(environment["clock"], dict), "clock metadata")
    for key in ("platform", "machine", "python"):
        _require(isinstance(environment[key], str) and bool(environment[key]), key)
    for variant in ("original", "transformed"):
        record = analysis.get(variant)
        _require(record is None or isinstance(record, dict), f"{variant} record")
        if record is not None:
            _require(record.get("canonical_source") is None or isinstance(record["canonical_source"], str), "canonical source")
            _require(_hash(record.get("source_sha256")), "variant input hash")
            _require(record.get("compilation") is None or isinstance(record["compilation"], dict), "compilation")
            _require(record.get("execution") is None or isinstance(record["execution"], dict), "execution")
    if analysis.get("original"):
        _require(analysis["original"]["source_sha256"] == analysis["source"]["sha256"], "original source hash mismatch")
    comparison = analysis.get("comparison_source")
    if analysis["comparison_kind"] == "independent_sources":
        _require(not sequence and isinstance(comparison, dict) and _hash(comparison.get("sha256")), "independent source identity")
        if analysis.get("transformed"):
            _require(analysis["transformed"]["source_sha256"] == comparison["sha256"], "comparison source hash mismatch")
    else:
        _require(comparison is None, "pipeline with independent source")
    for key in ("settings", "groups", "comparison", "metrics"):
        _require(isinstance(benchmark.get(key), dict), f"benchmark {key}")
    _require(isinstance(benchmark.get("status"), str) and isinstance(benchmark.get("samples"), list), "benchmark status/samples")
    _require(all(isinstance(item, dict) for item in benchmark["samples"]), "sample objects")
    _require(all(isinstance(benchmark["groups"].get(variant), dict) and isinstance(benchmark["groups"][variant].get("summary"), dict) for variant in ("original", "transformed")), "summary groups")
    _require(benchmark["comparison"].get("status") in ("available", "descriptive_only", "unreliable", "unavailable"), "comparison reliability")
    _require(isinstance(benchmark["comparison"].get("issues"), list) and all(isinstance(item, str) for item in benchmark["comparison"]["issues"]), "comparison reasons")
    _require(isinstance(benchmark["metrics"].get("hardware_instructions"), dict), "hardware availability")


def _same_number(left, right):
    if type(left) in (int, float) and type(right) in (int, float):
        return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
    return left == right


def _timing_audit(data):
    """Keep raw values but refuse summaries inconsistent with the actual samples."""
    benchmark, analysis = data["benchmark"], data["analysis"]
    if benchmark["status"] != "completed" or analysis["outcome"] != "observed_equivalent" or analysis["settings"]["sanitizer_requested"] is not True:
        return ["validation_not_accepted"]
    if analysis["comparison_kind"] == "transformation_pipeline" and not analysis["accepted_transformation"]:
        return ["no_accepted_transformation"]
    if data["environment_metadata"]["compiler"].get("status") != "available":
        return ["compiler_unavailable"]
    if not all(isinstance(data["environment_metadata"]["compiler"].get(key), str) and data["environment_metadata"]["compiler"][key] for key in ("path", "version")):
        return ["compiler_identity_incomplete"]
    try:
        for variant in ("original", "transformed", "capability"):
            record = analysis[variant]
            compilation, execution = record["compilation"], record["execution"]
            if compilation["status"] != "success" or type(compilation["returncode"]) is not int or compilation["returncode"] != 0:
                return [f"{variant}_compilation_not_successful"]
            if (execution["status"] != "success" or type(execution["return_value"]) is not int
                    or not -2147483648 <= execution["return_value"] <= 2147483647
                    or type(execution["process_returncode"]) is not int or execution["process_returncode"] != 0
                    or execution["signal"] is not None
                    or not all(isinstance(execution[key], str) for key in ("stdout", "stderr"))):
                return [f"{variant}_validation_not_successful"]
        if analysis["capability"]["execution"]["return_value"] != 0:
            return ["capability_validation_not_successful"]
        if any(analysis["original"]["execution"][key] != analysis["transformed"]["execution"][key]
               for key in ("status", "return_value", "process_returncode", "signal", "stdout", "stderr")):
            return ["validation_observations_differ"]
    except (KeyError, TypeError):
        return ["incomplete_validation_evidence"]
    settings = benchmark["settings"]
    if (settings.get("measurement_scope") != "end_to_end_process_execution" or settings.get("duration_unit") != "ns"
            or settings.get("compilation_timed") is not False or settings.get("warmups_timed") is not False
            or settings.get("clock_backend") != "time.perf_counter_ns" or settings.get("order") != "alternating_pairs"):
        return ["unsupported_measurement_contract"]
    clock = data["environment_metadata"]["clock"]
    if clock.get("name") != "perf_counter_ns" or clock.get("monotonic") is not True or clock.get("adjustable") is not False:
        return ["unsupported_clock"]
    warmups, repetitions = settings.get("warmups_per_variant"), settings.get("measurements_per_variant")
    if type(warmups) is not int or not 0 <= warmups <= 10000 or type(repetitions) is not int or not 1 <= repetitions <= 10000:
        return ["invalid_sample_counts"]
    schedule = [(phase, round_index, variant) for phase, count in (("warmup", warmups), ("measurement", repetitions))
                for round_index in range(count) for variant in (("original", "transformed") if round_index % 2 == 0 else ("transformed", "original"))]
    samples = benchmark["samples"]
    if len(schedule) != len(samples):
        return ["incomplete_sample_schedule"]
    try:
        for order, ((phase, round_index, variant), sample) in enumerate(zip(schedule, samples)):
            expected = analysis[variant]["execution"]
            execution = sample["execution"]
            if (sample["phase"], sample["round_index"], sample["variant"], sample["order_index"]) != (phase, round_index, variant, order):
                return ["invalid_sample_schedule"]
            if sample["valid"] is not True or sample["matches_expected"] is not True or execution["status"] != "success":
                return ["invalid_execution_sample"]
            if type(execution["return_value"]) is not int or not -2147483648 <= execution["return_value"] <= 2147483647 or type(execution["process_returncode"]) is not int or execution["process_returncode"] != 0 or execution["signal"] is not None:
                return ["invalid_full_observation"]
            if sample.get("duration_unit") != "ns" or sample.get("measurement_scope") != "end_to_end_process_execution":
                return ["inconsistent_sample_units"]
            if any(execution[key] != expected[key] for key in ("status", "return_value", "process_returncode", "signal", "stdout", "stderr")):
                return ["observation_drift"]
            if phase == "warmup" and sample["duration_ns"] is not None:
                return ["timed_warmup"]
        summaries = {}
        for variant in ("original", "transformed"):
            group = benchmark["groups"][variant]
            durations = [sample["duration_ns"] for sample in samples if sample["variant"] == variant and sample["phase"] == "measurement"]
            recomputed = summarize(durations)
            summaries[variant] = recomputed
            if any(type(group[key]) is not int or group[key] != repetitions for key in ("expected_samples", "attempted_samples", "successful_samples")):
                return ["inconsistent_sample_counts"]
            if recomputed.status != "available" or any(not _same_number(group["summary"].get(key), value) for key, value in recomputed.to_dict().items()):
                return ["inconsistent_summary"]
        comparison = compare_summaries(summaries["original"], summaries["transformed"])
        if any(not _same_number(benchmark["comparison"].get(key), value) for key, value in comparison.to_dict().items()):
            return ["inconsistent_reliability_or_ratio"]
    except (KeyError, TypeError, ValueError, OverflowError):
        return ["malformed_measurement_evidence"]
    return []


def _features(data, observation_id, digest):
    analysis, benchmark = data["analysis"], data["benchmark"]
    values = []

    def add(name, value, pointer, *, validity=None, reliability="deterministic", reasons=(), derivation=None):
        provenance = {"observation_id": observation_id, "report_sha256": digest, "pointer": pointer}
        if derivation:
            provenance["derivation"] = derivation
        values.append({"name": name, "value": value, "validity": validity or ("missing" if value is None else "valid"),
                       "reliability": reliability, "reasons": list(reasons), "provenance": provenance})

    reports = analysis["transformation_reports"]
    add("pipeline.status", " > ".join(report["status"] for report in reports) or "not_applicable", "/analysis/transformation_reports")
    for name in STATISTICS:
        add(f"pipeline.{name}", sum(report["statistics"][name] for report in reports) if reports else None,
            "/analysis/transformation_reports", validity="valid" if reports else "not_applicable",
            reasons=() if reports else ("no_selected_pass",), derivation=f"sum(statistics.{name})")
    counts = {}
    for variant in ("original", "transformed"):
        record = analysis.get(variant)
        reason = None
        try:
            if not record or not record.get("canonical_source"):
                reason = "canonical_source_unavailable"
            else:
                ir = lower_ir(parse(record["canonical_source"]))
                counts[variant] = sum(not isinstance(instruction, Label) for instruction in ir.instructions)
                binary = sum(isinstance(instruction, Binary) for instruction in ir.instructions)
                blocks = len(build_cfg(ir).blocks)
        except (FrontendError, RecursionError, ValueError):
            reason = "canonical_source_invalid"
        pointer = f"/analysis/{variant}/canonical_source"
        for name, value in ((f"tac.{variant}.operations", counts.get(variant)),
                            (f"tac.{variant}.binary", None if reason else binary),
                            (f"cfg.{variant}.blocks", None if reason else blocks)):
            add(name, value, pointer, reliability="unavailable" if reason else "deterministic", reasons=(reason,) if reason else (), derivation="parse -> validate -> TAC/CFG; exclude Label instructions and synthetic CFG nodes")
        for stage in ("compilation", "execution"):
            status = (record or {}).get(stage)
            add(f"compiler.{variant}.{stage}", status.get("status") if status else None,
                f"/analysis/{variant}/{stage}/status", reliability="observed" if status else "unavailable",
                reasons=() if status else ("not_observed",))
    original, transformed = counts.get("original"), counts.get("transformed")
    delta = transformed - original if original is not None and transformed is not None else None
    add("tac.delta.operations", delta, "/analysis", reasons=() if delta is not None else ("missing_tac_count",), derivation="transformed.operations - original.operations")
    response = normalize_response(original, transformed) if analysis["accepted_transformation"] else None
    add("tac.response.operations", response, "/analysis", validity="valid" if response is not None else "not_applicable" if not analysis["accepted_transformation"] else "missing",
        reasons=() if response is not None else ("no_applied_pass" if not analysis["accepted_transformation"] else "nonpositive_or_missing_baseline",), derivation="(transformed-original)/positive original")
    add("compiler.equivalence", analysis["outcome"], "/analysis/outcome", reliability="observed")
    add("compiler.benchmark_status", benchmark["status"], "/benchmark/status", reliability="observed")
    issues = _timing_audit(data)
    reliability = benchmark["comparison"]["status"]
    reasons = tuple(dict.fromkeys([*issues, *benchmark["comparison"]["issues"]]))
    medians = {}
    for variant in ("original", "transformed"):
        summary = benchmark["groups"][variant]["summary"]
        value = summary.get("median_ns")
        medians[variant] = value
        valid = finite_number(value) and value >= 0 and summary.get("status") == "available" and not issues
        add(f"performance.{variant}.median_ns", value, f"/benchmark/groups/{variant}/summary/median_ns",
            validity="valid" if valid else "missing" if value is None else "invalid", reliability=reliability,
            reasons=reasons or (() if valid else ("summary_unavailable",)))
    ratio = benchmark["comparison"].get("speedup")
    ratio_valid = finite_number(ratio) and ratio >= 0 and not issues
    add("performance.median_ratio", ratio, "/benchmark/comparison/speedup", validity="valid" if ratio_valid else "missing" if ratio is None else "invalid", reliability=reliability, reasons=reasons or (() if ratio_valid else ("ratio_unavailable",)))
    response = normalize_response(medians["original"], medians["transformed"])
    add("performance.duration_response", response, "/benchmark/groups", validity="valid" if response is not None and not issues else "missing" if response is None else "invalid", reliability=reliability,
        reasons=reasons or (() if response is not None else ("nonpositive_or_missing_baseline",)), derivation="(transformed.median_ns-original.median_ns)/positive original.median_ns")
    hardware = benchmark["metrics"]["hardware_instructions"]
    add("performance.hardware_instructions", None, "/benchmark/metrics/hardware_instructions", reliability="unavailable", reasons=(hardware.get("reason") or "hardware_backend_unavailable",))
    return sorted(values, key=lambda item: item["name"])


def build_matrix(reports) -> ResponseMatrix:
    """Build sparse, deterministic axes from existing schema-1 benchmark reports.

    Exact duplicate JSON evidence is deduplicated. Repeated experiments remain
    distinct observations, never averaged or selected arbitrarily. Unknown axis
    combinations have no row; no Cartesian product or zero-fill is generated.
    """
    if isinstance(reports, dict) or hasattr(reports, "to_dict"):
        reports = [reports]
    sources, pipelines, configurations, observations = {}, {}, {}, {}
    for report in reports:
        data = deepcopy(report.to_dict() if hasattr(report, "to_dict") else report)
        _validate_report(data)
        digest = hashlib.sha256(canonical_json(data).encode()).hexdigest()
        observation_id = "obs_" + digest
        if observation_id in observations:
            continue
        analysis, environment = data["analysis"], data["environment_metadata"]
        source_hash = analysis["source"]["sha256"]
        source_id = "src_" + source_hash
        original = analysis.get("original") or {}
        canonical = original.get("canonical_source")
        canonical_hash = hashlib.sha256(canonical.encode()).hexdigest() if canonical is not None else None
        if source_id in sources:
            _require(not sources[source_id]["canonical_sha256"] or not canonical_hash or sources[source_id]["canonical_sha256"] == canonical_hash, "conflicting canonical source for same raw source identity")
            if canonical_hash:
                sources[source_id]["canonical_sha256"] = canonical_hash
            sources[source_id]["names"] = sorted(set([*sources[source_id]["names"], analysis["source"]["name"]]))
        else:
            sources[source_id] = {"id": source_id, "sha256": source_hash, "canonical_sha256": canonical_hash, "names": [analysis["source"]["name"]]}
        pipeline = {"sequence": analysis["sequence"], "passes": [{key: item[key] for key in ("name", "version", "parameters")} for item in analysis["transformation_reports"]],
                    "max_unroll_iterations": analysis["settings"]["max_unroll_iterations"], "comparison_kind": analysis["comparison_kind"],
                    "comparison_source": (analysis.get("comparison_source") or {}).get("sha256")}
        pipeline_id = stable_id("pipe", pipeline)
        pipelines[pipeline_id] = {"id": pipeline_id, **pipeline}
        compiler = environment["compiler"]
        version = compiler.get("version")
        target = next((line.removeprefix("Target:").strip() for line in (version or "").splitlines() if line.startswith("Target:")), None)
        identity = {"compiler": {key: compiler.get(key) for key in ("status", "path", "version")},
                    "settings": {key: value for key, value in analysis["settings"].items() if key != "max_unroll_iterations"},
                    "environment": {key: environment[key] for key in ("platform", "machine", "python", "clock")},
                    "measurement": data["benchmark"]["settings"]}
        identity["compiler"]["target"] = target
        configuration_id = stable_id("config", identity)
        configurations[configuration_id] = {"id": configuration_id, "identity": identity}
        observations[observation_id] = {"id": observation_id, "benchmark_id": data["benchmark_id"], "source_id": source_id,
                                        "pipeline_id": pipeline_id, "configuration_id": configuration_id,
                                        "features": _features(data, observation_id, digest),
                                        "provenance": {"report_sha256": digest, "benchmark_id": data["benchmark_id"], "report": data}}
    payload = {"schema_version": 1, "kind": ResponseMatrix.KIND, "feature_schema": FEATURE_SCHEMA,
               "feature_definitions": list(FEATURE_DEFINITIONS),
               "sources": [sources[key] for key in sorted(sources)], "pipelines": [pipelines[key] for key in sorted(pipelines)],
               "configurations": [configurations[key] for key in sorted(configurations)],
               "observations": sorted(observations.values(), key=lambda item: (item["source_id"], item["pipeline_id"], item["configuration_id"], item["id"])),
               "interpretation": "Descriptive source/pipeline signatures and recorded compiler outcomes. No compiler-identity or semantic-equivalence proof. Missing combinations are absent; unreliable timings remain observations and are excluded from scores."}
    return ResponseMatrix({**payload, "matrix_id": stable_id("matrix", payload)})

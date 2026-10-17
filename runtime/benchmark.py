"""Equivalence-gated repeated measurements using the Phase 4 executables."""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Sequence
from uuid import uuid4

from runtime.benchmark_models import BenchmarkConfig, BenchmarkReport, BenchmarkSample
from runtime.benchmark_statistics import compare_summaries, summarize
from runtime.equivalence import prepared_equivalence
from runtime.models import ExecutionResult


def measurement_order(rounds: int):
    """Yield reproducible AB/BA pairs; each round executes both variants once."""
    for round_index in range(rounds):
        pair = ("original", "transformed") if round_index % 2 == 0 else ("transformed", "original")
        for variant in pair:
            yield round_index, variant


def _observation(execution: ExecutionResult) -> tuple:
    return (execution.status, execution.return_value, execution.process_returncode,
            execution.signal, execution.stdout, execution.stderr)


def _execution_failure(execution: ExecutionResult) -> tuple[str, str]:
    status = execution.status
    if status in ("timeout", "undefined_behavior", "interrupted"):
        return status, execution.detail or f"Execution status: {status}."
    return "execution_failure", execution.detail or f"Execution failed with status {status}."


def _summaries(samples: list[BenchmarkSample], completed: bool):
    groups = []
    for variant in ("original", "transformed"):
        measured = [sample for sample in samples if sample.phase == "measurement" and sample.variant == variant]
        if completed:
            result = summarize(sample.duration_ns for sample in measured)
        elif measured:
            # Preserve all individual records, but do not average a successful
            # prefix or the other variant after a failed comparison.
            result = replace(summarize([None] * len(measured)), issues=("comparison_invalid",))
        else:
            result = summarize(())
        groups.append((variant, result))
    return tuple(groups)


def benchmark(
    source: str, sequence: Sequence[str] = ("constants",), *,
    config: BenchmarkConfig | None = None, source_name: str = "<input>",
    comparison_source: str | None = None, comparison_source_name: str = "<transformed>",
    benchmark_id: str | None = None,
) -> BenchmarkReport:
    """Compile once per variant, validate, warm up, measure, and validate each run.

    The same sanitized executables used by the Phase 4 gate remain alive for all
    repetitions. Any bad observation or interruption stops the schedule and
    invalidates all comparative summaries; raw successful and failed rows remain.
    """
    config = BenchmarkConfig() if config is None else config
    if not isinstance(config, BenchmarkConfig):
        raise ValueError("config must be a BenchmarkConfig")
    identifier = uuid4().hex if benchmark_id is None else benchmark_id
    if not isinstance(identifier, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", identifier) is None:
        raise ValueError("benchmark_id must be 1..128 letters, digits, dots, underscores or hyphens, starting with a letter or digit")
    samples = []
    with prepared_equivalence(
        source, sequence, config=config.compile_config, max_iterations=config.max_iterations,
        source_name=source_name, comparison_source=comparison_source,
        comparison_source_name=comparison_source_name,
    ) as (runner, validation):
        status, explanation = validation.outcome, validation.explanation
        if validation.outcome == "observed_equivalent":
            variants = {"original": validation.original, "transformed": validation.transformed}
            status, explanation = "completed", "All warm-up and measured executions matched the validated full observations. Ratios describe observed end-to-end process durations."
            for phase, rounds in (("warmup", config.warmups), ("measurement", config.repetitions)):
                for round_index, variant in measurement_order(rounds):
                    expected = variants[variant].execution
                    try:
                        if phase == "warmup":
                            execution = runner.execute(variants[variant].compilation.artifact)
                            duration = None
                        else:
                            timed = runner.timed_execute(variants[variant].compilation.artifact)
                            execution, duration = timed.execution, timed.duration_ns
                    except KeyboardInterrupt:
                        execution = ExecutionResult("interrupted", detail="Execution interrupted; its process group was terminated.")
                        duration = None
                    matches = _observation(execution) == _observation(expected)
                    issue = None
                    if execution.status != "success":
                        status, explanation = _execution_failure(execution)
                        issue = execution.status
                    elif not matches:
                        status, explanation = "different_behavior", "A repeated execution diverged from the validated full return value, streams or process status; comparative statistics are invalid."
                        issue = "observation_changed"
                    elif phase == "measurement" and (type(duration) is not int or duration < 0):
                        status, explanation = "measurement_failure", "A measured execution has no valid nonnegative integer clock duration."
                        issue = "invalid_duration"
                    # Preserve execution/drift failure precedence while ensuring
                    # every failed row, including one with a bad clock value,
                    # can round-trip through strict JSON without NaN/Inf/bool.
                    if type(duration) is not int:
                        duration = None
                    samples.append(BenchmarkSample(
                        phase, len(samples), round_index, variant, duration, execution,
                        matches, issue is None, issue,
                    ))
                    if issue is not None:
                        break
                if status != "completed":
                    break
    summaries = _summaries(samples, completed=status == "completed")
    comparison = compare_summaries(summaries[0][1], summaries[1][1], short_program=True)
    return BenchmarkReport(identifier, status, explanation, config, validation,
                           tuple(samples), summaries, comparison)


def format_benchmark_summary(report: BenchmarkReport) -> str:
    """Concise honest CLI presentation; complete samples remain in exports."""
    data = report.to_dict()["benchmark"]
    lines = [f"Benchmark {report.benchmark_id}: {report.status}",
             f"Validation: {report.validation.outcome}; optimization: {report.config.compile_config.optimization}; UBSan: {report.config.compile_config.sanitize}",
             f"Warm-ups: {report.config.warmups} per variant; requested measured executions: {report.config.repetitions} per variant.",
             "Duration scope: end-to-end process execution (startup, sanitizer/harness and runner overhead included)."]
    for variant, group in data["groups"].items():
        summary = group["summary"]
        value = "unavailable" if summary["median_ns"] is None else f"median {summary['median_ns'] / 1_000_000:.3f} ms, mean {summary['mean_ns'] / 1_000_000:.3f} ms"
        lines.append(f"{variant}: {group['successful_samples']}/{group['expected_samples']} successful measured executions; {value}.")
    comparison = data["comparison"]
    if comparison["speedup"] is not None:
        change = "unavailable" if comparison["percentage_change"] is None else f"{comparison['percentage_change']:+.2f}%"
        lines.append(f"Observed process median ratio (original/transformed): {comparison['speedup']:.4f}; duration change: {change}.")
    lines.extend([f"Interpretation: {comparison['status']}; " + ", ".join(comparison["issues"]),
                  "No computational speedup or statistical significance is established. Hardware instructions: unavailable."])
    if report.status != "completed":
        lines.append(report.explanation)
    return "\n".join(lines)

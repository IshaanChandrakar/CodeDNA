"""Benchmark configuration and records, separate from deterministic analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import time
from typing import TYPE_CHECKING

from runtime.models import CompileConfig, ExecutionResult

if TYPE_CHECKING:
    from runtime.benchmark_statistics import ComparativeStatistics, SummaryStatistics
    from runtime.equivalence import EquivalenceReport


MEASUREMENT_SCOPE = "end_to_end_process_execution"
TIMING_DESCRIPTION = (
    "perf_counter_ns immediately before Popen through process reap, process-group cleanup "
    "and bounded capture-thread completion. Includes process creation/startup, sanitizer, "
    "computation, C result-file write, capture and runner supervision. Excludes compilation, "
    "run-directory/input preparation, Python capture decoding and observation JSON parsing."
)
LIMITATIONS = (
    "Durations include process startup, sanitizer/harness and runner overhead; computation is not isolated.",
    "No overhead correction or calibration is applied; short fixtures can be dominated by startup.",
    "Nanosecond units describe clock readings, not nanosecond measurement accuracy.",
    "Ratios describe observed process medians, not algorithmic speedups or statistical significance.",
    "IQR/CV reliability flags are descriptive heuristics, not a hypothesis test or confidence interval.",
    "An optimizing compiler may already perform the same source transformations, especially at O2.",
    "Background load, scheduling, filesystem/cache state, thermal state and execution order affect samples.",
    "Inherited environment is consistent within the comparison but is not fully serialized.",
    "Execution uses trusted local fixtures and resource limits, not filesystem/network isolation.",
    "No reliable hardware performance-counter backend is implemented; hardware instructions are unavailable.",
)


@dataclass(frozen=True, slots=True)
class TimedExecution:
    execution: ExecutionResult
    duration_ns: int | None


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    compile_config: CompileConfig = field(default_factory=CompileConfig)
    warmups: int = 5
    repetitions: int = 30
    max_iterations: int = 32

    def __post_init__(self) -> None:
        if not isinstance(self.compile_config, CompileConfig):
            raise ValueError("compile_config must be a CompileConfig")
        if type(self.warmups) is not int or not 0 <= self.warmups <= 10000:
            raise ValueError("warmups must be an integer from 0 to 10000")
        if type(self.repetitions) is not int or not 1 <= self.repetitions <= 10000:
            raise ValueError("repetitions must be an integer from 1 to 10000")
        if type(self.max_iterations) is not int or not 0 <= self.max_iterations <= 1024:
            raise ValueError("max_iterations must be an integer from 0 to 1024")


@dataclass(frozen=True, slots=True)
class BenchmarkSample:
    phase: str
    order_index: int
    round_index: int
    variant: str
    duration_ns: int | None
    execution: ExecutionResult
    matches_expected: bool
    valid: bool
    issue: str | None = None

    def to_dict(self) -> dict:
        return {
            "phase": self.phase, "order_index": self.order_index,
            "round_index": self.round_index, "variant": self.variant,
            "duration_ns": self.duration_ns, "duration_unit": "ns",
            "measurement_scope": MEASUREMENT_SCOPE,
            "execution": {**asdict(self.execution), "command": list(self.execution.command)},
            "matches_expected": self.matches_expected, "valid": self.valid,
            "issue": self.issue,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    benchmark_id: str
    status: str
    explanation: str
    config: BenchmarkConfig
    validation: EquivalenceReport
    samples: tuple[BenchmarkSample, ...]
    summaries: tuple[tuple[str, SummaryStatistics], ...]
    comparison: ComparativeStatistics
    limitations: tuple[str, ...] = LIMITATIONS

    def to_dict(self) -> dict:
        validation = self.validation.to_dict()
        clock = time.get_clock_info("perf_counter")
        groups = {}
        for variant, summary in self.summaries:
            measured = [sample for sample in self.samples if sample.phase == "measurement" and sample.variant == variant]
            groups[variant] = {
                "expected_samples": self.config.repetitions,
                "attempted_samples": len(measured),
                "successful_samples": sum(sample.valid for sample in measured),
                "summary": summary.to_dict(),
            }
        return {
            "schema_version": 1,
            "benchmark_id": self.benchmark_id,
            "analysis": validation["result"],
            "environment_metadata": {
                **validation["environment_metadata"],
                "clock": {"name": "perf_counter_ns", "implementation": clock.implementation,
                          "monotonic": clock.monotonic, "adjustable": clock.adjustable,
                          "reported_resolution_seconds": clock.resolution},
            },
            "benchmark": {
                "status": self.status, "explanation": self.explanation,
                "settings": {
                    "warmups_per_variant": self.config.warmups,
                    "measurements_per_variant": self.config.repetitions,
                    "order": "alternating_pairs", "order_definition": "Round 0: original/transformed; round 1: transformed/original; repeat independently per phase.",
                    "measurement_scope": MEASUREMENT_SCOPE, "duration_unit": "ns",
                    "timing_definition": TIMING_DESCRIPTION,
                    "clock_backend": "time.perf_counter_ns",
                    "warmups_timed": False, "compilation_timed": False,
                },
                "samples": [sample.to_dict() for sample in self.samples],
                "groups": groups,
                "comparison": self.comparison.to_dict(),
                "metrics": {"hardware_instructions": {
                    "value": None, "unit": "instructions", "scope": "executed_hardware_instructions",
                    "backend": None,
                    "status": "unavailable", "reason": "No reliable hardware-counter backend is implemented.",
                }},
                "limitations": list(self.limitations),
            },
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=True, allow_nan=False)

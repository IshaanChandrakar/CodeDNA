"""Real compilation and observed equivalence for the supported, closed C subset.

Successful comparison describes these executions, never a proof over arbitrary
programs. Source errors continue to use the compiler's source-located exceptions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import platform
import sys
from types import MappingProxyType
from typing import Mapping, Sequence

from compiler.codegen import emit_c
from compiler.parser import parse
from compiler.semantic import analyze
from runtime.compiler_runner import CompilerRunner
from runtime.harness import make_harness
from runtime.models import CompilationResult, CompileConfig, CompilerInfo, ExecutionResult
from transformations.common import TransformationReport
from transformations.pipeline import apply_transformations


def _sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class VariantReport:
    canonical_source: str
    source_sha256: str
    compilation: CompilationResult
    execution: ExecutionResult | None


@dataclass(frozen=True, slots=True)
class EquivalenceReport:
    outcome: str
    explanation: str
    comparison_kind: str
    source_name: str
    source_sha256: str
    sequence: tuple[str, ...]
    transformation_reports: tuple[TransformationReport, ...]
    origins: Mapping[str, str]
    config: CompileConfig
    compiler_info: CompilerInfo
    original: VariantReport
    transformed: VariantReport | None = None
    capability: VariantReport | None = None
    workspace: str = ""
    max_iterations: int = 32
    comparison_source_name: str | None = None

    @property
    def accepted_transformation(self) -> bool:
        return any(report.status == "applied" for report in self.transformation_reports)

    def _normalize(self, value):
        if isinstance(value, str) and self.workspace:
            # macOS may spell the same temporary directory through /var or
            # /private/var. Both spellings are environmental, not source facts.
            for spelling in sorted({self.workspace, str(Path(self.workspace).resolve())}, key=len, reverse=True):
                value = value.replace(spelling, "<workspace>")
            return value
        if isinstance(value, dict):
            return {key: self._normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._normalize(item) for item in value]
        return value

    def _variant(self, variant: VariantReport | None) -> dict | None:
        if variant is None:
            return None
        compilation = variant.compilation
        execution = variant.execution
        return self._normalize({
            "canonical_source": variant.canonical_source,
            "source_sha256": variant.source_sha256,
            "compilation": {
                "status": compilation.status,
                "returncode": compilation.returncode,
                "stdout": compilation.stdout,
                "stderr": compilation.stderr,
                "detail": compilation.detail,
                "harness_sha256": compilation.source_sha256,
            },
            "execution": None if execution is None else {
                "status": execution.status,
                "process_returncode": execution.process_returncode,
                "signal": execution.signal,
                "return_value": execution.return_value,
                "stdout": execution.stdout,
                "stderr": execution.stderr,
                "detail": execution.detail,
            },
        })

    def to_dict(self) -> dict:
        variants = {"original": self.original, "transformed": self.transformed, "capability": self.capability}
        return {
            "schema_version": 1,
            "result": {
                "outcome": self.outcome,
                "explanation": self.explanation,
                "comparison_kind": self.comparison_kind,
                "source": {"name": self.source_name, "sha256": self.source_sha256},
                "comparison_source": None if self.comparison_source_name is None else {
                    "name": self.comparison_source_name,
                    "sha256": self.transformed.source_sha256,
                },
                "sequence": list(self.sequence),
                "transformation_reports": [report.to_dict() for report in self.transformation_reports],
                "accepted_transformation": self.accepted_transformation,
                "origins": dict(sorted(self.origins.items())),
                "settings": {
                    "compiler": self.config.compiler,
                    "standard": "c11",
                    "optimization": self.config.optimization,
                    "flags": list(self.config.flags),
                    "compile_timeout_seconds": self.config.compile_timeout,
                    "execution_timeout_seconds": self.config.execution_timeout,
                    "sanitizer_requested": self.config.sanitize,
                    "max_output_bytes": self.config.max_output_bytes,
                    "memory_limit_mb": self.config.memory_limit_mb,
                    "max_unroll_iterations": self.max_iterations,
                    "target": "CHAR_BIT=8, sizeof(int)=4, INT_MIN=-2147483648, INT_MAX=2147483647",
                    "observation_protocol": 1,
                    "case": {"stdin": "", "arguments": [], "environment": {
                        "LC_ALL": "C", "LANG": "C", "TZ": "UTC",
                        "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=0:exitcode=86",
                    }},
                },
                **{name: self._variant(variant) for name, variant in variants.items()},
            },
            "environment_metadata": {
                "compiler": asdict(self.compiler_info),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": sys.version,
                "workspace": self.workspace,
                "artifacts": {
                    name: {
                        "compile_command": list(variant.compilation.command),
                        "artifact_path": str(variant.compilation.artifact.path) if variant.compilation.artifact else None,
                        "execution_command": list(variant.execution.command) if variant.execution else None,
                    } for name, variant in variants.items() if variant is not None
                },
                "artifact_lifetime": "Temporary artifacts were removed when the runner context closed.",
            },
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=True)


def _compile_variant(runner: CompilerRunner, program, *, label: str, source_sha256: str) -> VariantReport:
    analyze(program)
    harness = make_harness(program)
    compiled = runner.compile_source(harness.source, label=label, observation_file=harness.observation_file)
    return VariantReport(emit_c(program), source_sha256, compiled, None)


def _execute_variant(runner: CompilerRunner, variant: VariantReport) -> VariantReport:
    execution = runner.execute(variant.compilation.artifact) if variant.compilation.artifact else None
    return VariantReport(variant.canonical_source, variant.source_sha256, variant.compilation, execution)


def _failure(variants: Sequence[VariantReport]) -> tuple[str, str] | None:
    compilations = [variant.compilation for variant in variants]
    executions = [variant.execution for variant in variants if variant.execution is not None]
    if any(item.status == "unavailable" for item in compilations):
        return "unavailable", "Clang is unavailable; validation could not be performed."
    if any(item.status == "timeout" for item in compilations):
        return "timeout", "Compilation exceeded its configured timeout."
    if any(item.status != "success" for item in compilations):
        return "compilation_failure", "At least one program failed to compile; see the compiler diagnostics."
    if any(item.status == "undefined_behavior" for item in executions):
        return "undefined_behavior", "The undefined-behavior sanitizer reported a runtime violation; comparison is invalid."
    if any(item.status == "timeout" for item in executions):
        return "timeout", "At least one execution exceeded its configured timeout."
    if any(item.status != "success" for item in executions):
        return "execution_failure", "At least one execution failed; no equivalence conclusion is possible."
    if len(executions) != len(variants) or any(item.return_value is None for item in executions):
        return "inconclusive", "Complete signed integer observations are unavailable."
    return None


def _compare(original: VariantReport, transformed: VariantReport, *, accepted: bool, pipeline: bool, sanitize: bool) -> tuple[str, str]:
    failure = _failure((original, transformed))
    if failure:
        return failure
    left, right = original.execution, transformed.execution
    observations = lambda item: (item.return_value, item.stdout, item.stderr, item.process_returncode)
    if observations(left) != observations(right):
        return "different_behavior", "The full return value, stdout, stderr or process status differs."
    if pipeline and not accepted:
        return "no_transformation", "No selected pass applied an accepted change; matching unchanged executions do not validate a transformation."
    if not sanitize:
        return "inconclusive", "The observations match, but UBSan was disabled; unchecked undefined behavior prevents an equivalence acceptance."
    return "observed_equivalent", "Full return values, stdout, stderr and normal process status match for these executions. No UBSan violation was observed. This is observed equivalence, not a formal proof."


def _evaluate_pair(
    original_program, transformed_program, *, source: str, transformed_source: str,
    source_name: str, config: CompileConfig, sequence: tuple[str, ...],
    reports: tuple[TransformationReport, ...], origins: Mapping[str, str],
    comparison_kind: str, max_iterations: int,
    comparison_source_name: str | None = None,
) -> EquivalenceReport:
    with CompilerRunner(config) as runner:
        # A known-valid program checks the target assertions and the configured
        # sanitizer/link/runtime capability. No silent unsanitized fallback.
        probe_source = "int main(void) { return 0; }"
        capability = _compile_variant(runner, parse(probe_source), label="capability", source_sha256=_sha256(probe_source))
        if capability.compilation.status == "success":
            capability = _execute_variant(runner, capability)
        original = _compile_variant(runner, original_program, label="original", source_sha256=_sha256(source))
        transformed = _compile_variant(runner, transformed_program, label="transformed", source_sha256=_sha256(transformed_source))
        probe_failure = _failure((capability,))
        if probe_failure:
            if probe_failure[0] in ("timeout", "unavailable"):
                outcome, explanation = probe_failure
            elif capability.compilation.status != "success":
                # Bad flags and ordinary compiler diagnostics remain compilation
                # failures; missing sanitizer support/target assumptions are an
                # explicitly unavailable validation environment.
                diagnostics = capability.compilation.stderr.lower()
                unsupported = "codedna_target_int32" in diagnostics or (config.sanitize and any(
                    marker in diagnostics for marker in ("sanitizer", "ubsan", "unsupported argument 'undefined'", "unsupported option '-fsanitize")
                ))
                outcome = "unavailable" if unsupported else "compilation_failure"
                explanation = "The known-valid target/sanitizer capability program could not compile; inspect capability diagnostics."
            else:
                outcome, explanation = "unavailable", "The known-valid capability program could not execute successfully; validation is unavailable."
        else:
            if original.compilation.status == "success":
                original = _execute_variant(runner, original)
            if transformed.compilation.status == "success":
                transformed = _execute_variant(runner, transformed)
            outcome, explanation = _compare(
                original, transformed, accepted=any(report.status == "applied" for report in reports),
                pipeline=comparison_kind == "transformation_pipeline", sanitize=config.sanitize,
            )
        return EquivalenceReport(
            outcome, explanation, comparison_kind, source_name, _sha256(source), sequence, reports,
            MappingProxyType(dict(origins)), config, runner.compiler_info, original, transformed,
            capability, str(runner.root), max_iterations, comparison_source_name,
        )


def check_equivalence(
    source: str, sequence: Sequence[str] = ("constants",), *, config: CompileConfig | None = None,
    max_iterations: int = 32, source_name: str = "<input>",
) -> EquivalenceReport:
    """Validate, transform, independently compile/run, and compare a source case."""
    original = parse(source)
    analyze(original)
    transformed = apply_transformations(original, sequence, max_iterations=max_iterations)
    analyze(transformed.program)
    return _evaluate_pair(
        original, transformed.program, source=source, transformed_source=emit_c(transformed.program),
        source_name=source_name, config=config or CompileConfig(), sequence=transformed.sequence,
        reports=transformed.reports, origins=transformed.origins, comparison_kind="transformation_pipeline",
        max_iterations=max_iterations,
    )


def compare_sources(
    original_source: str, transformed_source: str, *, config: CompileConfig | None = None,
    original_name: str = "<original>", transformed_name: str = "<transformed>",
) -> EquivalenceReport:
    """Compare two independently validated sources, including negative controls."""
    original, transformed = parse(original_source), parse(transformed_source)
    analyze(original)
    analyze(transformed)
    # Keep independent source identification separate from AST origin IDs.
    return _evaluate_pair(
        original, transformed, source=original_source, transformed_source=transformed_source,
        source_name=original_name, config=config or CompileConfig(), sequence=(), reports=(),
        origins={}, comparison_kind="independent_sources", max_iterations=32,
        comparison_source_name=transformed_name,
    )


def evaluate_source(
    source: str, *, execute: bool = True, sequence: Sequence[str] = (),
    config: CompileConfig | None = None, max_iterations: int = 32, source_name: str = "<input>",
) -> EquivalenceReport:
    """Compile or run one validated source; temporary binaries are context-owned."""
    original = parse(source)
    analyze(original)
    pipeline = apply_transformations(original, sequence, max_iterations=max_iterations)
    config = config or CompileConfig()
    with CompilerRunner(config) as runner:
        variant = _compile_variant(runner, pipeline.program, label="program", source_sha256=_sha256(source))
        if execute and variant.compilation.status == "success":
            variant = _execute_variant(runner, variant)
        if not execute and variant.compilation.status == "success":
            outcome, explanation = "compiled", "Clang compiled the validated program and target assertions successfully. The temporary binary has been removed."
        else:
            failure = _failure((variant,))
            outcome, explanation = failure if failure else ("executed", "The harness observed the complete signed integer result; inspect the execution record.")
        return EquivalenceReport(
            outcome, explanation, "run" if execute else "compile", source_name, _sha256(source),
            pipeline.sequence, pipeline.reports, pipeline.origins, config, runner.compiler_info,
            variant, workspace=str(runner.root), max_iterations=max_iterations,
        )

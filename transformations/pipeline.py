"""Explicit ordered transformation sequences, with original-source provenance."""

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Mapping, Sequence

from compiler.ast_nodes import Program, walk
from compiler.semantic import analyze
from transformations.common import CloneFactory, MAX_UNROLL_LIMIT, TransformationReport
from transformations.constant_folding import propagate_and_fold
from transformations.loop_unrolling import unroll_loops


PASS_NAMES = ("constants", "unroll")


@dataclass(frozen=True, slots=True)
class PipelineResult:
    program: Program
    sequence: tuple[str, ...]
    reports: tuple[TransformationReport, ...]
    origins: Mapping[str, str]

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "sequence": list(self.sequence),
            "reports": [report.to_dict() for report in self.reports],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def apply_transformations(
    program: Program,
    sequence: Sequence[str] = ("constants", "unroll"),
    *,
    max_iterations: int = 32,
) -> PipelineResult:
    """Apply named passes in exactly the requested order; retain every report.

    A rejected pass preserves its input; subsequent passes still operate on that
    valid tree. Empty sequences are allowed and return a fresh baseline tree.
    """
    if isinstance(sequence, str):
        sequence = (sequence,)
    sequence = tuple(sequence)
    if any(name not in PASS_NAMES for name in sequence):
        raise ValueError(f"Transformation names must be chosen from {PASS_NAMES}")
    if type(max_iterations) is not int or not 0 <= max_iterations <= MAX_UNROLL_LIMIT:
        raise ValueError(f"max_iterations must be an integer from 0 to {MAX_UNROLL_LIMIT}")
    analyze(program)
    factory = CloneFactory(program)
    current = factory.clone(program)
    origins = {node.node_id: node.node_id for node in walk(program)}
    reports = []
    for name in sequence:
        result = propagate_and_fold(current) if name == "constants" else unroll_loops(current, max_iterations)
        origins = {node_id: origins.get(parent_id, parent_id) for node_id, parent_id in result.origins.items()}
        current = result.program
        reports.append(result.report)
    return PipelineResult(current, sequence, tuple(reports), MappingProxyType(origins))

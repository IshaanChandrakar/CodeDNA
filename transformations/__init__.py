"""Fresh-AST constant propagation/folding and conservative full loop unrolling."""

from transformations.common import TransformationResult
from transformations.constant_folding import propagate_and_fold
from transformations.loop_unrolling import unroll_loops
from transformations.pipeline import PipelineResult, apply_transformations

__all__ = [
    "TransformationResult", "PipelineResult", "propagate_and_fold",
    "unroll_loops", "apply_transformations",
]

"""Pure descriptive statistics for complete groups of integer nanosecond samples.

Standard deviation uses the sample estimator (n - 1). Quartiles use inclusive
linear interpolation, conventionally called R7: the zero-based index for a
probability p is (n - 1) * p. One sample has Q1 == Q3 and IQR == 0, but no sample
standard deviation. These calculations do not establish statistical significance.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Iterable


@dataclass(frozen=True, slots=True)
class SummaryStatistics:
    status: str
    count: int
    median_ns: float | None
    mean_ns: float | None
    min_ns: int | None
    max_ns: int | None
    stdev_ns: float | None
    q1_ns: float | None
    q3_ns: float | None
    iqr_ns: float | None
    coefficient_of_variation: float | None
    issues: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "count": self.count,
            "median_ns": self.median_ns,
            "mean_ns": self.mean_ns,
            "min_ns": self.min_ns,
            "max_ns": self.max_ns,
            "stdev_ns": self.stdev_ns,
            "q1_ns": self.q1_ns,
            "q3_ns": self.q3_ns,
            "iqr_ns": self.iqr_ns,
            "coefficient_of_variation": self.coefficient_of_variation,
            "issues": list(self.issues),
        }


@dataclass(frozen=True, slots=True)
class ComparativeStatistics:
    status: str
    speedup: float | None
    percentage_change: float | None
    issues: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "speedup": self.speedup,
            "percentage_change": self.percentage_change,
            "issues": list(self.issues),
        }


def _missing(status: str, count: int, issue: str) -> SummaryStatistics:
    return SummaryStatistics(status, count, None, None, None, None, None, None, None, None, None, (issue,))


def _quartile_numerator(ordered: list[int], quarter: int) -> int:
    """Return four times an R7 quartile, retaining exact integer arithmetic."""
    index, remainder = divmod((len(ordered) - 1) * quarter, 4)
    if remainder == 0:
        return ordered[index] * 4
    return ordered[index] * (4 - remainder) + ordered[index + 1] * remainder


def summarize(durations: Iterable[int | None]) -> SummaryStatistics:
    """Summarize a complete group, refusing to silently drop invalid samples.

    Durations must be nonnegative built-in integers; booleans, floats (including
    infinities/NaN), missing values and negative durations invalidate the entire
    group. Count retains all supplied entries. A genuine zero remains zero and
    flags clock resolution. Numeric results that cannot be represented as finite
    JSON numbers produce an invalid group rather than fabricated measurements.
    """
    try:
        samples = tuple(durations)
    except TypeError:
        return _missing("invalid", 0, "invalid_duration")
    count = len(samples)
    if not samples:
        return _missing("unavailable", 0, "no_samples")
    if any(type(value) is not int or value < 0 for value in samples):
        return _missing("invalid", count, "invalid_duration")
    ordered = sorted(samples)
    try:
        median = float(statistics.median(ordered))
        mean = float(statistics.mean(ordered))
        stdev = statistics.stdev(ordered) if count > 1 else None
        q1_numerator = _quartile_numerator(ordered, 1)
        q3_numerator = _quartile_numerator(ordered, 3)
        q1 = q1_numerator / 4
        q3 = q3_numerator / 4
        # Subtract before float conversion: large absolute durations must not
        # erase small, genuine dispersion through cancellation of rounded floats.
        iqr = (q3_numerator - q1_numerator) / 4
        coefficient = stdev / mean if stdev is not None and mean > 0 else None
        numbers = (median, mean, stdev, q1, q3, iqr, coefficient)
        if any(value is not None and not math.isfinite(value) for value in numbers):
            return _missing("invalid", count, "numeric_overflow")
    except (OverflowError, ValueError):
        return _missing("invalid", count, "numeric_overflow")
    issues: list[str] = []
    if ordered[0] == 0:
        issues.append("clock_resolution")
    if count == 1:
        issues.append("insufficient_samples_for_stdev")
    if mean == 0:
        issues.append("zero_mean")
    return SummaryStatistics(
        "available", count, median, mean, ordered[0], ordered[-1], stdev,
        q1, q3, iqr, coefficient, tuple(issues),
    )


def _usable(summary: SummaryStatistics) -> bool:
    if not isinstance(summary, SummaryStatistics) or summary.status != "available" or summary.count < 1:
        return False
    required = (summary.median_ns, summary.q1_ns, summary.q3_ns, summary.iqr_ns)
    return all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 for value in required)


def compare_summaries(
    original: SummaryStatistics, transformed: SummaryStatistics, *, short_program: bool = True,
) -> ComparativeStatistics:
    """Compare medians descriptively, exposing scope and simple noise flags.

    Speedup is original/transformed; percentage change is
    (transformed-original)/original*100. Each denominator is checked separately.
    Heuristics flag fewer than five samples, CV > 0.1, overlapping IQRs, or a
    median gap no larger than the larger IQR. These are caution flags, not a
    hypothesis test. End-to-end process timing includes startup/harness overhead;
    by default even a large difference is descriptive, never algorithmic evidence.
    """
    issues: list[str] = ["process_startup_scope"] if short_program else []
    if not _usable(original) or not _usable(transformed):
        return ComparativeStatistics("unavailable", None, None, (*issues, "invalid_summary"))
    clock_resolution = "clock_resolution" in original.issues or "clock_resolution" in transformed.issues
    if clock_resolution:
        issues.append("clock_resolution")
    original_median = original.median_ns
    transformed_median = transformed.median_ns
    if original_median == 0:
        issues.append("zero_original_median")
    if transformed_median == 0:
        issues.append("zero_transformed_median")
    try:
        speedup = original_median / transformed_median if transformed_median != 0 else None
        percentage = (transformed_median - original_median) / original_median * 100 if original_median != 0 else None
        if any(value is not None and not math.isfinite(value) for value in (speedup, percentage)):
            return ComparativeStatistics("unavailable", None, None, (*issues, "numeric_overflow"))
    except (OverflowError, ZeroDivisionError):
        return ComparativeStatistics("unavailable", None, None, (*issues, "numeric_overflow"))
    if speedup is None or percentage is None:
        return ComparativeStatistics("unavailable", speedup, percentage, tuple(issues))
    noisy = clock_resolution
    if min(original.count, transformed.count) < 5:
        issues.append("undersampled")
        noisy = True
    if any(summary.coefficient_of_variation is not None and summary.coefficient_of_variation > 0.1 for summary in (original, transformed)):
        issues.append("high_variability")
        noisy = True
    if max(original.q1_ns, transformed.q1_ns) <= min(original.q3_ns, transformed.q3_ns):
        issues.append("iqr_overlap")
        noisy = True
    if abs(original_median - transformed_median) <= max(original.iqr_ns, transformed.iqr_ns):
        issues.append("dispersion_exceeds_difference")
        noisy = True
    status = "unreliable" if noisy else "descriptive_only" if short_program else "available"
    return ComparativeStatistics(status, speedup, percentage, tuple(issues))

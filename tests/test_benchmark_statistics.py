"""Hand-computed summaries and cautious comparisons; no timing-speed assertions."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
import json
import math

import pytest

from runtime.benchmark_statistics import compare_summaries, summarize


METRICS = (
    "median_ns", "mean_ns", "min_ns", "max_ns", "stdev_ns", "q1_ns", "q3_ns",
    "iqr_ns", "coefficient_of_variation",
)


def assert_missing(summary):
    assert all(getattr(summary, name) is None for name in METRICS)


def test_four_samples_have_exact_r7_quartiles_and_sample_standard_deviation():
    summary = summarize([1, 2, 3, 4])
    assert summary.status == "available" and summary.count == 4
    assert summary.median_ns == 2.5
    assert summary.mean_ns == 2.5
    assert summary.min_ns == 1 and summary.max_ns == 4
    assert summary.stdev_ns == pytest.approx(math.sqrt(5 / 3))
    assert summary.q1_ns == 1.75
    assert summary.q3_ns == 3.25
    assert summary.iqr_ns == 1.5
    assert summary.coefficient_of_variation == pytest.approx(math.sqrt(5 / 3) / 2.5)
    assert summary.issues == ()


def test_large_integer_offsets_do_not_erase_the_interquartile_range():
    base = 2**60
    summary = summarize([base + 1, base + 2, base + 3, base + 4])
    assert summary.status == "available" and summary.count == 4
    assert summary.min_ns == base + 1 and summary.max_ns == base + 4
    # The reported float quartiles round at this scale. Their exact R7
    # difference is still (base+3.25) - (base+1.75) = 1.5 ns.
    assert summary.iqr_ns == 1.5
    assert summary.stdev_ns == pytest.approx(math.sqrt(5 / 3))
    json.dumps(summary.to_dict(), allow_nan=False)


@pytest.mark.parametrize("values,median,mean,q1,q3,iqr", [
    ([10, 20], 15, 15, 12.5, 17.5, 5),
    ([1, 2, 9], 2, 4, 1.5, 5.5, 4),
    ([1, 2, 3, 4, 5], 3, 3, 2, 4, 2),
    ([2, 2, 2, 8, 8], 2, 4.4, 2, 8, 6),
    ([5, 1, 9, 3, 7], 5, 5, 3, 7, 4),
])
def test_even_odd_repeated_and_unsorted_samples_use_inclusive_linear_interpolation(values, median, mean, q1, q3, iqr):
    summary = summarize(values)
    assert summary.median_ns == median
    assert summary.mean_ns == mean
    assert summary.q1_ns == q1
    assert summary.q3_ns == q3
    assert summary.iqr_ns == iqr
    assert type(summary.min_ns) is int and type(summary.max_ns) is int
    assert all(type(getattr(summary, name)) is float for name in ("median_ns", "mean_ns", "q1_ns", "q3_ns", "iqr_ns"))


def test_single_sample_has_descriptive_values_but_no_sample_variance_estimate():
    summary = summarize([17])
    assert summary.status == "available" and summary.count == 1
    assert summary.median_ns == summary.mean_ns == 17.0
    assert summary.min_ns == summary.max_ns == 17
    assert summary.q1_ns == summary.q3_ns == 17.0 and summary.iqr_ns == 0.0
    assert summary.stdev_ns is None and summary.coefficient_of_variation is None
    assert summary.issues == ("insufficient_samples_for_stdev",)


@pytest.mark.parametrize("values", [[], (), iter(())])
def test_empty_groups_are_unavailable_with_missing_metrics(values):
    summary = summarize(values)
    assert summary.status == "unavailable" and summary.count == 0
    assert summary.issues == ("no_samples",)
    assert_missing(summary)


@pytest.mark.parametrize("bad", [
    None, -1, True, False, 1.0, 0.0, float("nan"), float("inf"), -float("inf"),
    "3", Decimal("3"), 3 + 0j, object(),
])
def test_any_invalid_duration_invalidates_the_complete_group_without_filtering(bad):
    summary = summarize([10, bad, 20])
    assert summary.status == "invalid"
    assert summary.count == 3
    assert summary.issues == ("invalid_duration",)
    assert_missing(summary)


@pytest.mark.parametrize("values", [None, 5, True])
def test_noniterable_groups_are_explicitly_invalid(values):
    summary = summarize(values)
    assert summary.status == "invalid" and summary.count == 0
    assert_missing(summary)


def test_unrepresentable_numeric_aggregates_never_emit_nan_or_infinity():
    summary = summarize([10**400, 10**400 + 1])
    assert summary.status == "invalid" and summary.count == 2
    assert summary.issues == ("numeric_overflow",)
    assert_missing(summary)
    json.dumps(summary.to_dict(), allow_nan=False)


@pytest.mark.parametrize("count", [1, 5])
def test_real_zero_durations_remain_zero_instead_of_becoming_missing(count):
    summary = summarize([0] * count)
    assert summary.status == "available" and summary.count == count
    assert summary.min_ns == summary.max_ns == 0
    assert summary.median_ns == summary.mean_ns == summary.iqr_ns == 0.0
    assert summary.q1_ns == summary.q3_ns == 0.0
    assert summary.stdev_ns == (None if count == 1 else 0.0)
    assert summary.coefficient_of_variation is None
    assert "clock_resolution" in summary.issues and "zero_mean" in summary.issues


def test_zero_among_positive_durations_is_preserved_and_flagged():
    summary = summarize([0, 1, 2, 3, 4])
    assert summary.count == 5
    assert summary.median_ns == summary.mean_ns == 2.0
    assert summary.min_ns == 0
    assert summary.q1_ns == 1 and summary.q3_ns == 3
    assert summary.issues == ("clock_resolution",)


def test_sample_standard_deviation_uses_n_minus_one_rather_than_population_n():
    summary = summarize([10, 20])
    assert summary.stdev_ns == pytest.approx(math.sqrt(50))
    assert summary.stdev_ns != 5
    assert summary.coefficient_of_variation == pytest.approx(math.sqrt(50) / 15)


def test_summary_does_not_mutate_input_and_generator_order_cannot_change_results():
    values = [4, 1, 3, 2]
    snapshot = values.copy()
    summary = summarize(values)
    assert values == snapshot
    assert summary == summarize(value for value in reversed(values))
    assert summary == summarize(values)


def test_summary_json_preserves_explicit_names_order_units_nulls_and_zeroes():
    summary = summarize([0])
    data = summary.to_dict()
    assert list(data) == ["status", "count", *METRICS, "issues"]
    assert data["median_ns"] == 0 and data["stdev_ns"] is None
    assert json.loads(json.dumps(data, allow_nan=False)) == data
    data["issues"].append("external change")
    assert "external change" not in summary.issues
    with pytest.raises(FrozenInstanceError):
        summary.count = 100


@pytest.mark.parametrize("original,transformed,speedup,percentage", [
    ([100] * 5, [50] * 5, 2.0, -50.0),
    ([50] * 5, [100] * 5, 0.5, 100.0),
    ([300] * 5, [100] * 5, 3.0, -200 / 3),
])
def test_ratios_use_original_over_transformed_and_percentage_change_uses_original_baseline(original, transformed, speedup, percentage):
    comparison = compare_summaries(summarize(original), summarize(transformed))
    assert comparison.speedup == pytest.approx(speedup)
    assert comparison.percentage_change == pytest.approx(percentage)
    assert comparison.status == "descriptive_only"
    assert comparison.issues == ("process_startup_scope",)


def test_even_a_large_observed_ratio_never_escapes_process_startup_scope_by_default():
    comparison = compare_summaries(summarize([1_000_000] * 30), summarize([1] * 30))
    assert comparison.speedup == 1_000_000
    assert comparison.status == "descriptive_only"
    assert comparison.issues == ("process_startup_scope",)


def test_explicitly_separate_scope_can_expose_descriptive_ratios_without_startup_flag():
    comparison = compare_summaries(summarize([100] * 5), summarize([50] * 5), short_program=False)
    assert comparison.status == "available"
    assert comparison.speedup == 2.0 and comparison.percentage_change == -50.0
    assert comparison.issues == ()


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_small_groups_are_unreliable_even_with_zero_spread_and_large_median_gaps(count):
    comparison = compare_summaries(summarize([100] * count), summarize([50] * count))
    assert comparison.status == "unreliable"
    assert comparison.speedup == 2
    assert "undersampled" in comparison.issues
    assert "process_startup_scope" in comparison.issues


def test_five_samples_avoid_only_the_undersampling_flag():
    comparison = compare_summaries(summarize([100] * 5), summarize([50] * 5))
    assert "undersampled" not in comparison.issues
    assert comparison.status == "descriptive_only"


def test_high_variability_overlapping_iqrs_and_small_differences_are_caution_flags_not_significance_tests():
    comparison = compare_summaries(summarize([1, 2, 3, 4, 5]), summarize([2, 3, 4, 5, 6]))
    assert comparison.status == "unreliable"
    assert comparison.speedup == 0.75
    assert comparison.percentage_change == pytest.approx(100 / 3)
    assert comparison.issues == (
        "process_startup_scope", "high_variability", "iqr_overlap", "dispersion_exceeds_difference",
    )


def test_touching_iqr_endpoints_count_as_overlap_even_when_the_median_gap_exceeds_each_iqr():
    comparison = compare_summaries(summarize([100, 100, 100, 101, 101]), summarize([101, 101, 102, 102, 102]))
    assert comparison.status == "unreliable"
    assert "iqr_overlap" in comparison.issues
    assert "dispersion_exceeds_difference" not in comparison.issues
    assert "high_variability" not in comparison.issues


def test_dispersion_can_exceed_the_median_difference_even_without_iqr_overlap():
    comparison = compare_summaries(summarize([1, 1, 100, 101, 101]), summarize([102] * 5))
    assert comparison.status == "unreliable"
    assert "dispersion_exceeds_difference" in comparison.issues
    assert "iqr_overlap" not in comparison.issues


@pytest.mark.parametrize("values,flagged", [
    ([90, 90, 100, 110, 110], False),
    ([89, 90, 100, 110, 111], True),
])
def test_cv_heuristic_is_strictly_greater_than_ten_percent(values, flagged):
    comparison = compare_summaries(summarize(values), summarize([200] * 5))
    assert ("high_variability" in comparison.issues) is flagged
    assert comparison.status == ("unreliable" if flagged else "descriptive_only")


def test_clock_resolution_flags_unreliability_even_when_positive_medians_allow_ratios():
    comparison = compare_summaries(summarize([0, 10, 10, 10, 10]), summarize([100] * 5))
    assert comparison.status == "unreliable"
    assert comparison.speedup == 0.1
    assert "clock_resolution" in comparison.issues


@pytest.mark.parametrize("original,transformed,speedup,percentage,issue", [
    ([0] * 5, [10] * 5, 0.0, None, "zero_original_median"),
    ([10] * 5, [0] * 5, None, -100.0, "zero_transformed_median"),
    ([0] * 5, [0] * 5, None, None, "zero_original_median"),
])
def test_zero_denominators_stay_missing_independently_and_never_become_infinite(original, transformed, speedup, percentage, issue):
    comparison = compare_summaries(summarize(original), summarize(transformed))
    assert comparison.status == "unavailable"
    assert comparison.speedup == speedup
    assert comparison.percentage_change == percentage
    assert issue in comparison.issues
    assert "clock_resolution" in comparison.issues
    json.dumps(comparison.to_dict(), allow_nan=False)


@pytest.mark.parametrize("values", [[], [1, None, 2], [-1], [float("nan")]])
@pytest.mark.parametrize("invalid_side", ["original", "transformed"])
def test_invalid_or_missing_groups_prevent_comparison_on_either_side(values, invalid_side):
    invalid = summarize(values)
    valid = summarize([10] * 5)
    left, right = (invalid, valid) if invalid_side == "original" else (valid, invalid)
    comparison = compare_summaries(left, right)
    assert comparison.status == "unavailable"
    assert comparison.speedup is None and comparison.percentage_change is None
    assert comparison.issues == ("process_startup_scope", "invalid_summary")


def test_a_manually_incomplete_summary_cannot_produce_a_comparison():
    incomplete = replace(summarize([10] * 5), median_ns=None)
    comparison = compare_summaries(incomplete, summarize([5] * 5))
    assert comparison.status == "unavailable"
    assert "invalid_summary" in comparison.issues


def test_noisy_unreliability_takes_precedence_over_the_process_scope_label():
    comparison = compare_summaries(summarize([100]), summarize([50]))
    assert comparison.status == "unreliable"
    assert "undersampled" in comparison.issues and "process_startup_scope" in comparison.issues


def test_comparison_json_is_deterministic_and_records_are_immutable():
    original, transformed = summarize([100] * 5), summarize([50] * 5)
    comparison = compare_summaries(original, transformed)
    data = comparison.to_dict()
    assert list(data) == ["status", "speedup", "percentage_change", "issues"]
    assert json.loads(json.dumps(data, allow_nan=False)) == data
    assert comparison == compare_summaries(original, transformed)
    with pytest.raises(FrozenInstanceError):
        comparison.speedup = 999
    data["issues"].clear()
    assert comparison.issues == ("process_startup_scope",)

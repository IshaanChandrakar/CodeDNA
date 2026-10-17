# Phase 5 benchmark examples

These use existing validated C fixtures; no new C syntax or transformation is
introduced. Activate the checkout's `.venv`. Benchmark defaults are five untimed
warm-ups and thirty timed executions **per variant**, after Phase 4 validation.
Phase 5 passed its 1384-case acceptance gate; actual serial baseline exports are
recorded in the validation report. Run these six baseline groups serially,
without a concurrent Clang integration suite. They use a ten-second execution deadline, recorded in
each report; the ordinary API/CLI default remains two seconds.

```sh
python -m compiler --benchmark --transform constants --opt O0 --execution-timeout 10 --csv --output results/phase5/constants-O0.json examples/runtime/constants_return257.c
python -m compiler --benchmark --transform constants --opt O2 --execution-timeout 10 --csv --output results/phase5/constants-O2.json examples/runtime/constants_return257.c
python -m compiler --benchmark --transform unroll --opt O0 --execution-timeout 10 --csv --output results/phase5/unroll-O0.json examples/transformations/unroll_positive.c
python -m compiler --benchmark --transform unroll --opt O2 --execution-timeout 10 --csv --output results/phase5/unroll-O2.json examples/transformations/unroll_positive.c
python -m compiler --benchmark --transform constants --transform unroll --transform constants --opt O0 --execution-timeout 10 --csv --output results/phase5/combined-O0.json examples/transformations/combined.c
python -m compiler --benchmark --transform constants --transform unroll --transform constants --opt O2 --execution-timeout 10 --csv --output results/phase5/combined-O2.json examples/transformations/combined.c
```

O0 and O2 are separately labeled conditions. Expected full results are 257, 64
and 146; these expectations are not measured timing results. Each
command exports JSON and separate `.samples.csv` and `.summary.csv` files. The
JSON contains complete compiler/environment/source provenance. CSV rows join to
it through `benchmark_id`. Warm-up durations are missing, not zero.

Other representative cases:

```sh
python -m compiler --benchmark --warmups 1 --repetitions 5 --transform constants --csv --output results/phase5/negative.json examples/runtime/negative_math.c
python -m compiler --benchmark --transform unroll --output results/phase5/inapplicable.json examples/basic/minimal.c
python -m compiler --benchmark --transform unroll --output results/phase5/rejected.json examples/transformations/rejected_declaration.c
python -m compiler --benchmark --against examples/runtime/mismatch_257.c --output results/phase5/mismatch.json examples/runtime/mismatch_one.c
python -m compiler --benchmark --execution-timeout 1 --output results/phase5/timeout.json examples/runtime/timeout.c
python -m compiler --benchmark --output results/phase5/undefined.json examples/runtime/dynamic_divzero.c
python -m compiler --benchmark --no-sanitize --output results/phase5/inconclusive.json examples/runtime/constants_return257.c
```

The negative result is -201. Inapplicable/rejected transformations produce
`no_transformation` (exit 6); the mismatch is `different_behavior` (exit 5);
timeout/undefined behavior exit 4. Matching runs with UBSan disabled are
`inconclusive` (exit 6). These cases retain validation reports and have no timing
samples or invented comparative statistics.

Durations measure end-to-end subprocess execution, including startup, sanitizer,
harness and runner supervision. Tiny fixtures can be dominated by that overhead.
No correction is applied and an observed ratio is not an algorithmic speedup or
significance result. Clang can already perform similar transformations at O2.
Hardware instruction counts are explicitly unavailable. See
[the methodology and real baseline evidence](../../docs/PHASE5_VALIDATION.md).
All six recorded main conditions completed but their timing comparisons were
`unreliable`; the report retains all outliers and makes no speedup claim.

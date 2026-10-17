# Phase 5 — repeated process measurement and structured results

Accepted 2026-10-17 (Asia/Kolkata): **1384 passed, 0 failed, 0 skipped**, including
all **1111** prior cases and **273** new cases. The complete serial suite and
genuine O0/O2 baseline measurements passed the Phase 5 gate; evidence is below.
The accepted historical Phase 4 gate had 1111 passing tests. No Phase 6 or Phase 7
implementation is included in this work.

## Files and integration

New runtime modules:

| File | Responsibility |
| --- | --- |
| `runtime/benchmark_models.py` | Immutable benchmark configuration, timed execution wrapper, raw samples, report schema, clock metadata and limitations |
| `runtime/benchmark.py` | Equivalence gate, repeated execution order, full-observation checks, failure invalidation and concise CLI interpretation |
| `runtime/benchmark_statistics.py` | Pure finite descriptive summaries, quartiles, ratios and reliability flags |
| `runtime/benchmark_storage.py` | Strict JSON, separate raw/summary CSV, all-path preflight and atomic file replacement |

The existing `runtime/compiler_runner.py` gains `timed_execute`; it uses the same
bounded process path as ordinary `execute`. `runtime/equivalence.py` adds
`prepared_equivalence`, keeping the existing owning runner alive while the
benchmark reuses its validated artifacts. `compiler/__main__.py` adds benchmark
configuration and exports to the established CLI. Phase 4 `ExecutionResult`
fields and ordinary public compile/run/equivalence interfaces are retained.
`runtime/__init__.py` describes the completed runtime package. The existing
compiler-runner timeout fixture separates cold discovery (the ordinary ten-second
budget) from its one-second deliberately sleeping compilation; its timeout,
diagnostic and single-probe assertions remain unchanged.
The parser, semantic rules, emitter and transformation algorithms are unchanged.

New tests are `tests/test_timed_runner.py`, `tests/test_benchmark.py`,
`tests/test_benchmark_statistics.py`, `tests/test_benchmark_storage.py` and
`tests/test_phase5_cli.py`. `examples/benchmarks/README.md` catalogs commands over
existing C fixtures; it does not add a language feature or a new native harness.
The README, architecture, compiler design, plan and progress documents describe
the current phase. No new dependency is required.

The resume audit preserved all four saved benchmark modules, the timing/equivalence
seams, CLI, example catalog and five test modules. The first deterministic audit
had 170 passing cases. Narrow completion repairs cover interrupted discovery and
capture-thread startup cleanup, strict serialization of failed clock readings,
and exact IQR subtraction before float conversion. Existing working execution,
storage and statistical code was retained; actual baseline exports, documentation
and the complete acceptance run were then finished.

## Correctness gate and repetition strategy

`benchmark(source, sequence=("constants",), config=..., comparison_source=...,
benchmark_id=...)` starts with the Phase 4 frontend and observed-equivalence
service. A known-valid capability program checks target width and configured
sanitizer support. Baseline and candidate are independently compiled using
identical C11, O0 or O2, sanitizer and timeout settings. Their complete signed
returns, streams and normal process observations must agree before sampling.
The source remains the documented closed subset with no external input/I/O.

Only `observed_equivalent` permits warm-ups and measurements. Missing Clang,
compilation failure, timeout, UB, different behavior, inconclusive validation and
an unchanged/rejected transformation pipeline are retained as explicit outcomes.
Matching unsanitized executions remain inconclusive; there is no silent
unsanitized fallback. An independent source comparison uses an empty pass
sequence and remains labeled as an independent comparison.

The exact same sanitized binaries used for validation remain alive throughout
the benchmark. Compilation and capability/initial validation executions are not
timed benchmark samples. Artifacts are removed when the owning context closes.
Each subsequent execution receives a fresh private run directory and the same
controlled execution case/environment snapshot.

Defaults are **5 untimed warm-ups and 30 measured executions per variant**.
`warmups` accepts 0..10000; `repetitions` accepts 1..10000. Every round runs both
variants once. The order is deterministic:

| Phase-local round | Order |
| --- | --- |
| 0, 2, 4, ... | original, transformed |
| 1, 3, 5, ... | transformed, original |

Round numbering restarts for measurements after warm-ups. There is no hidden
randomization. Each raw record carries phase, global order index, phase-local
round and variant. Warm-up durations are missing, never manufactured zeros.

Every execution is checked against its own initially validated observation:
status, full returned integer, wrapper process code, signal, stdout and stderr.
A failed run, observation change, invalid clock reading or interruption stops
the remaining schedule. Attempted rows, including a failure and successful
prefix, remain in the report. Both comparative summary groups become
invalid/unavailable; a valid prefix or a group that happened to finish first is
not silently averaged. Successful-sample counts cannot include failed rows.

## Timing definition and interpretation

The clock backend is `time.perf_counter_ns()`. Its boundaries in the existing
runner are immediately before `subprocess.Popen` and after process reaping,
process-group cleanup and bounded output-capture thread completion.

| Included in `duration_ns` | Excluded |
| --- | --- |
| Process creation/startup, including child resource setup | Compiler discovery, compilation and initial validation |
| Sanitizer startup and program computation | Run-directory and input-file preparation |
| C full-return observation-file write | Python capture decoding |
| Output capture and runner supervision/cleanup | Python observation JSON reading/parsing |

The scope is **`end_to_end_process_execution`**, not isolated program computation.
Nanosecond units are clock readings, not an assertion of nanosecond or
microsecond-level measurement accuracy. Clock implementation, monotonic/adjustable flags
and reported resolution are environmental metadata. No overhead correction,
calibration subtraction or repeated-computation native wrapper is applied.

These small fixtures can be dominated by process launch, sanitizer/harness,
capture and scheduling overhead. Cache/filesystem state, background load,
thermal state and ordering also affect results. Benchmarks and heavyweight Clang
integration suites should be run serially. At O2, Clang may already perform the
same source-level transformation, so a small or indistinguishable observed
difference is a valid result. No algorithmic speedup or statistical significance
is established by this methodology.

## Statistical definitions

Statistics use complete groups of nonnegative built-in integer nanoseconds.
Missing values, booleans, floats, negatives or a result too large for finite JSON
numbers invalidate the whole group. A genuine zero remains zero and is flagged.
No failed observation is dropped to improve a summary.

| Field | Definition |
| --- | --- |
| `count` | Number of supplied measured durations; warm-ups are excluded |
| `median_ns` | Ordinary median of the sorted measured durations |
| `mean_ns` | Arithmetic mean |
| `min_ns`, `max_ns` | Observed minimum and maximum |
| `stdev_ns` | Sample standard deviation with denominator `n-1`; missing for `n=1` |
| `q1_ns`, `q3_ns` | Inclusive R7 quartiles: index `(n-1)*p` with linear interpolation, `p=0.25`/`0.75` |
| `iqr_ns` | Q3 minus Q1; a single sample has Q1=Q3 and IQR=0 |
| `coefficient_of_variation` | Sample standard deviation divided by positive mean; dimensionless, missing when undefined |
| `speedup` | `median_original / median_transformed`; a dimensionless **observed process median ratio** |
| `percentage_change` | `100*(median_transformed-median_original)/median_original`; positive means a longer transformed process median |

Each ratio denominator is checked independently. If one is zero, its undefined
quantity is missing rather than invented; a separately defined companion value
can remain present. Numeric overflow also gives an unavailable result.

Group issues include `no_samples`, `invalid_duration`, `numeric_overflow`,
`clock_resolution`, `insufficient_samples_for_stdev`, `zero_mean`, and
`comparison_invalid` when a failed benchmark invalidates attempted groups.
Comparison issues are descriptive:

| Issue | Trigger |
| --- | --- |
| `process_startup_scope` | Always present in the high-level benchmark, which includes process/harness overhead |
| `invalid_summary` | Either group lacks a usable complete summary |
| `zero_original_median`, `zero_transformed_median` | A ratio denominator is zero |
| `numeric_overflow` | A ratio cannot be represented as a finite number |
| `undersampled` | Fewer than five samples in either group |
| `clock_resolution` | A group has genuine zero-duration clock readings |
| `high_variability` | Either defined CV is greater than 0.1 |
| `iqr_overlap` | The closed Q1..Q3 intervals overlap |
| `dispersion_exceeds_difference` | Absolute median gap is no larger than the larger IQR |

Missing/invalid comparisons are `unavailable`; any reliability heuristic makes a
defined comparison `unreliable`. A defined comparison without such flags is
still `descriptive_only` for the high-level process-scope benchmark. These are
neither hypothesis tests nor confidence intervals. A `completed` benchmark can
therefore correctly have `unreliable` timing interpretation and CLI exit 0: the
schedule and behavior were valid, not a performance improvement claim.

## JSON schema and availability

Schema version 1 has these top-level fields:

| Field | Contents |
| --- | --- |
| `schema_version` | Integer 1 |
| `benchmark_id` | Per-run identifier joining all exports; CLI uses a UUID hex string |
| `analysis` | Phase 4 deterministic result: input hashes/names, canonical sources, applicability/origins, settings, compilation and validation observations |
| `environment_metadata` | Compiler version, platform/machine/Python, historical artifact commands/paths, and clock metadata |
| `benchmark` | Status/explanation, repetition/timing settings, raw samples, grouped summaries, comparison, metric availability and limitations |

`benchmark.samples` retain `phase`, `order_index`, `round_index`, `variant`,
`duration_ns`, `duration_unit="ns"`,
`measurement_scope="end_to_end_process_execution"`, full `execution`,
`matches_expected`, `valid`, and `issue`. Execution records preserve actual
status, full return, process code, signal, streams, detail and command. Raw sample
commands refer to now-cleaned temporary artifacts; they are execution provenance,
not deterministic compiler results.

`benchmark.groups.original` and `.transformed` distinguish requested
`expected_samples`, `attempted_samples`, `successful_samples` and the complete
`summary`. `benchmark.comparison` contains status, ratio, percentage change and
issues. Raw measurements and UUIDs vary across runs; ordering/schema and
re-export of one report are repeatable. Canonical JSON rejects NaN and Infinity.

Hardware instructions are explicitly unavailable: `value=null`, `backend=null`,
`unit="instructions"`, `scope="executed_hardware_instructions"`,
`status="unavailable"` and a reason stating that no reliable backend is
implemented. No `perf` installation is required. Static TAC operations remain a
separate structural quantity and are never substituted for hardware counts or
elapsed time. Benchmark samples do not claim a static-count performance benefit.

## Exact CSV schemas and safe persistence

Raw-sample header, in exact order:

```csv
benchmark_id,phase,order_index,round_index,variant,duration_ns,duration_unit,measurement_scope,status,matches_expected,valid,return_value,process_returncode,signal,stdout,stderr,detail,issue
```

Aggregate-summary header, in exact order:

```csv
benchmark_id,benchmark_status,variant,expected_samples,attempted_samples,successful_samples,summary_status,median_ns,mean_ns,min_ns,max_ns,stdev_ns,q1_ns,q3_ns,iqr_ns,coefficient_of_variation,duration_unit,comparison_status,speedup,percentage_change,issues,hardware_instructions,hardware_instructions_status
```

The raw CSV includes warm-ups and failed attempts in actual recorded order.
`status` is the actual execution status; a normal process can still be invalid
for benchmarking when `matches_expected=false` or its duration is invalid.
Summary rows are original first, transformed second. Duration and dispersion
fields ending `_ns` use nanoseconds; CV and ratio are dimensionless and percentage
change uses percent. `issues` joins comparison codes followed by group codes with
semicolons, retaining the first occurrence of duplicates.

Missing fields are empty CSV cells, including untimed warm-ups, absent return
observations, undefined ratios and unavailable hardware instructions. Real zero
durations/counts are written as zero. Booleans are lowercase `true`/`false`.
UTF-8, CSV quoting and CRLF record endings preserve commas, quotes and multiline
streams. JSON missing values are `null`. Every CSV row includes `benchmark_id`.

`save_report(report, json_path, samples_csv=..., summary_csv=...,
protected_paths=...)` returns immutable `ExportPaths`. Pure `raw_rows` and
`summary_rows` expose the corresponding records. Public
`validate_output_paths(paths, protected_paths=...)` makes no filesystem changes
and lets the CLI preflight destinations before compilation.

All paths are checked together: protected input aliases (including hardlinks and
symlink targets), output/output aliases and parent/child path collisions are
rejected. Final output symlinks, directories and special files are refused;
existing regular output files may be replaced. Parent-directory symlinks are
resolved for collision checks. Serialization and validation finish before parent
directories are created. All sibling temporary files are written/flushed before
the first atomic `os.replace`; remaining temps are cleaned after failure.
Atomicity applies to each file, not one transaction across JSON and both CSVs.
These are source-preserving export checks, not a hostile-filesystem sandbox.

## Reproduction commands

From the checkout with `.venv` active:

```sh
python -m compiler --benchmark --transform constants --opt O0 --execution-timeout 10 --csv --output results/phase5/constants-O0.json examples/runtime/constants_return257.c
python -m compiler --benchmark --transform constants --opt O2 --execution-timeout 10 --csv --output results/phase5/constants-O2.json examples/runtime/constants_return257.c
python -m compiler --benchmark --transform unroll --opt O0 --execution-timeout 10 --csv --output results/phase5/unroll-O0.json examples/transformations/unroll_positive.c
python -m compiler --benchmark --transform unroll --opt O2 --execution-timeout 10 --csv --output results/phase5/unroll-O2.json examples/transformations/unroll_positive.c
python -m compiler --benchmark --transform constants --transform unroll --transform constants --opt O0 --execution-timeout 10 --csv --output results/phase5/combined-O0.json examples/transformations/combined.c
python -m compiler --benchmark --transform constants --transform unroll --transform constants --opt O2 --execution-timeout 10 --csv --output results/phase5/combined-O2.json examples/transformations/combined.c
python -m compiler --benchmark --warmups 1 --repetitions 5 --samples-csv results/phase5/custom-raw.csv --summary-csv results/phase5/custom-summary.csv --output results/phase5/negative.json examples/runtime/negative_math.c
python -m compiler --benchmark --against examples/runtime/mismatch_257.c --output results/phase5/mismatch.json examples/runtime/mismatch_one.c
python -m compiler --benchmark --transform unroll --output results/phase5/inapplicable.json examples/basic/minimal.c
python -m compiler --benchmark --execution-timeout 1 --output results/phase5/timeout.json examples/runtime/timeout.c
```

The first six commands reproduce the serial baseline groups, each using the
default five warm-ups and thirty measurements per variant. Their explicit
ten-second execution deadline is recorded as an experiment setting, allowing
process/sanitizer startup without changing the ordinary two-second API/CLI
default. Run them separately from the acceptance tests, with no parallel Clang suite.

Default output is `results/<benchmark_id>/benchmark.json`. `--output` changes the
JSON path. `--csv` adds `<stem>.samples.csv` and `<stem>.summary.csv` beside it;
custom raw/summary paths also work independently, or override one sidecar while
`--csv` supplies the other. JSON is always saved when a complete report is
available, including validation failures. The CLI prints a concise scope,
counts, summaries, ratio/reliability interpretation and saved paths, not all raw
JSON. `--warmups`/`--repetitions` and CSV options require `--benchmark`.

| CLI exit | Benchmark meaning |
| --- | --- |
| 0 | Complete behavior-valid schedule; interpretation may remain unreliable/descriptive |
| 1 | Lexer/parser/semantic source error |
| 2 | Argument, file/encoding or export-path error |
| 3 | Compilation failure |
| 4 | Execution/measurement failure, compile/run timeout or detected UB |
| 5 | Initial or repeated observed behavior differs |
| 6 | Unavailable/inconclusive validation or no accepted transformation |
| 130 | Interrupted; a partial benchmark report is saved when available |

An interruption before a complete validation/report object exists can only
produce the interruption diagnostic. Saving a failure report retains its exit
code. Rejected/inapplicable passes and unsanitized matching pairs do not receive
invented comparative timing results.

## Actual baseline evidence — 2026-10-17

The six main conditions completed serially with no parallel Clang suite. Each
used five untimed warm-ups and thirty timed executions per variant: **60 warm-up
rows and 360 measured rows in total**. Every measured execution was valid. The
full original/transformed returns were **257/257** for constants, **64/64** for
unrolling and **146/146** for the ordered constants → unroll → constants pipeline.
Wrapper process codes were 0, independently of the full returned integer.

Actual exports and exact invocations are retained locally under
[`results/phase5/baseline-2026-10-17/`](../results/phase5/baseline-2026-10-17/),
with a [command/outcome manifest](../results/phase5/baseline-2026-10-17/manifest.json).
These generated results are ignored by Git; reproduce them with the commands
above, or inspect the exact original command lists in the manifest. Each stem
has `.json`, `.samples.csv` and `.summary.csv` files. The first twelve report sets
also retain `.stdout.txt` and `.stderr.txt` command output.

| Condition and JSON | `benchmark_id` | Raw samples / summary |
| --- | --- | --- |
| [constants-O0](../results/phase5/baseline-2026-10-17/constants-O0.json) | `498d286c74fc4d28a4ba6de03d42bfb8` | [raw](../results/phase5/baseline-2026-10-17/constants-O0.samples.csv) / [summary](../results/phase5/baseline-2026-10-17/constants-O0.summary.csv) |
| [constants-O2](../results/phase5/baseline-2026-10-17/constants-O2.json) | `38e50dc5310e4299a2ccf676e251d6f5` | [raw](../results/phase5/baseline-2026-10-17/constants-O2.samples.csv) / [summary](../results/phase5/baseline-2026-10-17/constants-O2.summary.csv) |
| [unroll-O0](../results/phase5/baseline-2026-10-17/unroll-O0.json) | `f064e98a74ab4e939918233e270b48b9` | [raw](../results/phase5/baseline-2026-10-17/unroll-O0.samples.csv) / [summary](../results/phase5/baseline-2026-10-17/unroll-O0.summary.csv) |
| [unroll-O2](../results/phase5/baseline-2026-10-17/unroll-O2.json) | `c6c2cdfcbbae4245a92a278f1ae984f6` | [raw](../results/phase5/baseline-2026-10-17/unroll-O2.samples.csv) / [summary](../results/phase5/baseline-2026-10-17/unroll-O2.summary.csv) |
| [combined-O0](../results/phase5/baseline-2026-10-17/combined-O0.json) | `bad15b3f62b944b6b81ef8a9e9c6493b` | [raw](../results/phase5/baseline-2026-10-17/combined-O0.samples.csv) / [summary](../results/phase5/baseline-2026-10-17/combined-O0.summary.csv) |
| [combined-O2](../results/phase5/baseline-2026-10-17/combined-O2.json) | `09e313af2e2142e1b21a50429c852dda` | [raw](../results/phase5/baseline-2026-10-17/combined-O2.samples.csv) / [summary](../results/phase5/baseline-2026-10-17/combined-O2.summary.csv) |

Median and IQR values below retain their exact recorded nanosecond values;
ratios and percentages are rounded for display. Each condition has thirty
measurements in each group.

| Condition | Original median (ns) | Transformed median (ns) | Original / transformed IQR (ns) | Process median ratio | Duration change |
| --- | ---: | ---: | ---: | ---: | ---: |
| constants-O0 | 10350021 | 10329250 | 68780.5 / 101896.5 | 1.002011 | -0.200686% |
| constants-O2 | 10382458.5 | 10396833.5 | 108854.75 / 134177 | 0.998617 | +0.138455% |
| unroll-O0 | 10376145.5 | 10380374.5 | 247125.25 / 164885.5 | 0.999593 | +0.040757% |
| unroll-O2 | 10437000 | 10433895.5 | 120426.5 / 180604.25 | 1.000298 | -0.029745% |
| combined-O0 | 10412229 | 10381020.5 | 147489.5 / 212457.75 | 1.003006 | -0.299729% |
| combined-O2 | 10384229.5 | 10359646 | 85323 / 104937.5 | 1.002373 | -0.236739% |

The remaining descriptive statistics are shown in milliseconds, rounded to six
decimal places; full precision and quartiles remain in JSON/CSV.

| Condition | Variant | Mean (ms) | Minimum (ms) | Maximum (ms) | Sample SD (ms) | CV |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| constants-O0 | original | 10.348390 | 10.117709 | 10.604125 | 0.082459 | 0.007968 |
| constants-O0 | transformed | 10.767636 | 9.906500 | 20.441541 | 1.903911 | 0.176818 |
| constants-O2 | original | 10.381631 | 9.386083 | 11.235292 | 0.259029 | 0.024951 |
| constants-O2 | transformed | 10.377651 | 9.622500 | 10.682667 | 0.204605 | 0.019716 |
| unroll-O0 | original | 10.516450 | 10.246459 | 11.699250 | 0.380503 | 0.036182 |
| unroll-O0 | transformed | 10.479679 | 9.820209 | 11.491292 | 0.362346 | 0.034576 |
| unroll-O2 | original | 10.434899 | 10.231917 | 10.775166 | 0.111794 | 0.010713 |
| unroll-O2 | transformed | 10.436469 | 10.028792 | 10.659625 | 0.133356 | 0.012778 |
| combined-O0 | original | 10.422414 | 9.583416 | 11.311458 | 0.253040 | 0.024278 |
| combined-O0 | transformed | 10.377151 | 9.457750 | 10.728417 | 0.226271 | 0.021805 |
| combined-O2 | original | 10.383266 | 10.192459 | 10.596083 | 0.091661 | 0.008828 |
| combined-O2 | transformed | 10.387381 | 10.108334 | 11.015208 | 0.147112 | 0.014163 |

All six comparisons are **`unreliable`**. Every one reports
`process_startup_scope`, `iqr_overlap` and `dispersion_exceeds_difference`;
constants-O0 additionally reports `high_variability` because the transformed CV
is approximately 0.177. Its 20.442 ms maximum was retained. **No raw outlier was
excluded and no overhead correction was applied.** These roughly 10.3–10.4 ms
process medians and near-one ratios provide no algorithmic speedup or significance
claim, at either optimization level.

Actual constants-O0 CLI excerpt (exit 0):

```text
original: 30/30 successful measured executions; median 10.350 ms, mean 10.348 ms.
transformed: 30/30 successful measured executions; median 10.329 ms, mean 10.768 ms.
Observed process median ratio (original/transformed): 1.0020; duration change: -0.20%.
Interpretation: unreliable; process_startup_scope, high_variability, iqr_overlap, dispersion_exceeds_difference
No computational speedup or statistical significance is established. Hardware instructions: unavailable.
```

Additional real reports retain applicability and failure outcomes:

| Report | Actual observation/outcome | CLI exit | Measured rows |
| --- | --- | ---: | ---: |
| [negative](../results/phase5/baseline-2026-10-17/negative.json) | Full returns -201/-201; one warm-up and five measurements per variant; `completed`, timing interpretation `unreliable` | 0 | 10 |
| [inapplicable](../results/phase5/baseline-2026-10-17/inapplicable.json) | Full returns 0/0; `no_transformation` | 6 | 0 |
| [rejected](../results/phase5/baseline-2026-10-17/rejected.json) | Full returns 3/3; `no_transformation` | 6 | 0 |
| [mismatch](../results/phase5/baseline-2026-10-17/mismatch.json) | Full returns 1/257; `different_behavior` | 5 | 0 |
| [undefined](../results/phase5/baseline-2026-10-17/undefined.json) | UBSan detected dynamic zero division; `undefined_behavior` | 4 | 0 |
| [inconclusive](../results/phase5/baseline-2026-10-17/inconclusive.json) | UBSan disabled, full returns 257/257; `inconclusive` | 6 | 0 |
| [timeout](../results/phase5/baseline-2026-10-17/timeout.json) | Capability check succeeded; original and transformed loop computations exceeded the separate three-second execution deadline; `timeout` | 4 | 0 |

The timeout command used `--execution-timeout 3`, independently of the
ten-second deadline for the successful conditions. Both timed-out processes were
terminated, full observations are missing and comparative ratios remain missing.

Across these thirteen saved reports, JSON/CSV headers, join identifiers, record
order, integer durations, missing warm-up readings, full returns, statuses and
counts were checked. Mean, median, min/max, sample SD, R7 quartiles/IQR, ratios
and percentage changes were recomputed independently from the raw measured
durations. Temporary executable/workspace cleanup was verified. Failure and
inapplicability CSVs preserve unavailable aggregates as empty cells, with JSON
`null` values. Hardware counts remain unavailable in every report.

The current observed validation environment is **Apple M2, eight logical cores,
macOS 26.6.2 arm64, Python 3.14.5**, and **Apple Clang 21.0.0
(clang-2100.3.34.2)** targeting **arm64-apple-darwin25.6.0**. Each baseline report
must retain its own observed environment and actual timeout/optimization flags.
Background system load of approximately 14 was observed during validation, with
XProtect/MobileAsset activity present. This does not establish a cause for timing
variation or timeouts, and no host security setting was changed. Reports record
`mach_absolute_time()` as the monotonic, non-adjustable clock implementation and
approximately 41.67 ns reported clock resolution; this is not execution-time
accuracy. Actual compile flags were `-std=c11 -O0` or `-O2`,
`-fsanitize=undefined -fno-sanitize-recover=all`. Compile and execution deadlines
were ten seconds. The unsanitized negative control explicitly omitted UBSan.

## Acceptance evidence — passed

| Check | Current evidence status |
| --- | --- |
| Existing 1111 Phase 1–4 cases | All passed in the complete serial gate |
| Timing seam and runner compatibility | 24 new cases passed |
| Pure statistics | 64 new cases passed |
| Persistence and path protection | 35 new cases passed |
| Repeated benchmark orchestration | 95 new cases passed |
| Benchmark CLI integration, O0/O2 | 55 new cases passed |
| Genuine baseline/raw-sample recomputation | Six O0/O2 conditions and seven additional reports checked as described above |
| Local links, CSV-header accuracy, example paths and whitespace | Seven updated documents checked; local links/paths resolve, exact CSV headers match implementation and `git diff --check` is clean |
| `.venv/bin/python -m pytest -q --tb=short --showlocals` | **1384 passed, 0 failed, 0 skipped**, 269.75 seconds of test-suite wall time |
| `.venv/bin/python -m pip check` | No broken requirements found |

The complete suite passed **1384 cases**, comprising all 1111 prior cases plus
273 new cases. Actual Clang integrations executed at O0/O2; none was skipped.
The suite duration is validation evidence, not a runtime measurement of a C
program. Thirteen complete JSON/raw CSV/summary CSV sets were verified against
their schemas, source/observation provenance and independent statistical
recomputation, with all temporary workspaces cleaned.

Earlier overlapping Clang work produced validation timeouts and is not accepted
as a passing gate or usable baseline. A subsequent pre-fix audit suite had
1371 passes and one fake-compiler output-limit test failure: that invocation
returned `os_error` rather than `output_limit`. The case passed in isolation and
thirty repeated reproductions; its cause remains unidentified. It was not a
timeout, and no causal claim about host load is made. Correctness assertions and
ordinary timeout defaults remain intact. A later gate attempt was stopped after
504 passes and a fake-compiler discovery timeout. Its fixture now uses the
ordinary ten-second discovery budget before selecting the original one-second
compilation deadline; the fake compilation still sleeps twenty seconds. The
focused test passed in 2.82 seconds, retaining all original assertions. This
test setup adjustment does not change production compiler/execution deadlines.
The final complete serial gate above passed after those narrow audit/test-setup
repairs; M5 is accepted in [PROGRESS.md](PROGRESS.md).

## Platform, safety and phase limits

The local execution platform is macOS arm64. Linux and other Python/compiler
versions remain unverified; no platform coverage is inferred from portable APIs.
Execution is restricted operationally to trusted local coursework fixtures.
Process deadlines, bounded output and available POSIX limits contain accidental
runaway work; they provide no filesystem/network isolation or default complete
memory cap. Inherited host environment is shared consistently within a pair but
is not fully serialized.

UBSan and observed agreement do not prove universal safety, termination or formal
equivalence. Startup/harness and OS load can dominate the measured difference.
No hardware performance-counter support, response matrices, DNA vectors,
fingerprint distance/classification, dashboard or new C syntax is implemented.
Stop at the Phase 5 acceptance gate; Phases 6–7 have not begun. No commit, push,
branch or Git configuration change is part of this work.

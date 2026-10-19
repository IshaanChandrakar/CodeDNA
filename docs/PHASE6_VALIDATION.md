# Phase 6 — descriptive response matrices and fingerprint comparisons

Stability follow-up, 2026-10-19: two complete serial runs now pass **1720 tests
each**, including all 1709 original cases plus eleven supervision regressions.
Phase 6 source/fixture bytes and deterministic outputs were preserved. The gate
below records the original run; corrected runtime behavior, test budgets and
repeat validation are recorded in [RUNTIME_STABILITY.md](RUNTIME_STABILITY.md).

Accepted 2026-10-18 (Asia/Kolkata): **1709 passed, 0 failed, 0 skipped**, including
all **1384** historical cases and **325** new cases. Genuine report ingestion,
deterministic extraction/comparison, reliability exclusions and JSON/CSV exports
passed validation. Phase 5 reports and schemas are unchanged.

## Definition and evidence boundary

A CodeDNA fingerprint is a versioned, structured selection of matrix observations
for **one compiler configuration**. It has three feature groups:

- `structural`: source/pipeline properties, reported committed transformation
  statistics, and static TAC/CFG measurements derived from saved canonical C.
- `compiler`: recorded compilation, execution, equivalence and benchmark statuses.
- `performance`: recorded process medians/ratios, derived duration responses and
  explicitly unavailable hardware instructions.

This is an interpretable description of available evidence. It does not uniquely
identify a compiler, classify vendors, establish semantic equivalence, or prove
an algorithmic performance improvement. A structural difference between different
programs is a program difference, not a compiler response.

The six original constants/unrolling/combined O0/O2 reports and seven failure or
control reports are preserved byte-for-byte under
[`examples/observations/phase5/`](../examples/observations/phase5/README.md).
Their README records original paths and SHA-256 checksums. Phase 6 performs no
new benchmark campaign. Embedded temporary paths are historical provenance.
Full original Phase 5 documents remain in each observation's `provenance.report`.
The import is evidence reuse, not authentication of arbitrary supplied JSON.

## Modules and public interfaces

| Module | Responsibility |
| --- | --- |
| `fingerprint/models.py` | Strict JSON snapshots, finite numbers, version/kind checks, axes/references/features and stable content identities |
| `fingerprint/matrix.py` | `build_matrix(reports)`, deterministic sparse axes, Phase 5 validation, timing audit and pure canonical-source TAC/CFG extraction |
| `fingerprint/extraction.py` | `extract_fingerprint(matrix, configuration_id=..., source_ids=..., pipeline_ids=..., observation_ids=...)` selects one configuration without aggregation |
| `fingerprint/similarity.py` | Explicit alignment policies and missing-aware weighted per-feature comparisons |
| `fingerprint/storage.py` | Strict JSON loading, stable long-form CSV and input-preserving atomic output |
| `fingerprint/cli.py` | Reporting commands behind the existing `python -m compiler` entry point |

The existing compiler, transformation algorithms, runtime and Phase 5 schemas
are retained. Only additive CLI routing touches earlier implementation files.
No dependency, new C feature, optimization pass or dashboard is added.

Created files are the six implementation modules listed above;
`tests/test_fingerprint_matrix.py`, `test_fingerprint_extraction.py`,
`test_fingerprint_similarity.py`, `test_fingerprint_models.py`,
`test_fingerprint_storage.py`, `test_phase6_cli.py`; this validation report;
`examples/comparison/{original,renamed,refactored,unrelated}.c` and its README;
and the thirteen original JSON files plus README under
`examples/observations/phase5/`. Modified files are `compiler/__main__.py`,
`fingerprint/__init__.py`, `README.md`, and the four current architecture,
compiler-design, implementation-plan and progress documents. Historical
Phase 4/5 validation reports remain unchanged.

## Matrix dimensions and identities

The sparse matrix contains sorted `sources`, `pipelines`, `configurations`,
`feature_definitions` and observations. Observation rows reference all three axes
and carry a named feature vector. Missing source/pipeline/config combinations
have **no observation**, rather than an invented zero-valued row.

Sources use the exact input SHA-256 recorded by Phase 4. Canonical-source hashes
are separate: raw comments/formatting mean these are usually different hashes.
Pipeline identity includes the exact ordered sequence, each pass version and
parameters, unroll limit, comparison kind and independent-source identity.
Configuration identity includes requested compiler and actual discovery
path/version/target, optimization and exact ordered flags, C target/protocol,
sanitizer, timeouts/output/memory limits, case/environment controls, recorded
platform/machine/Python/clock and the entire measurement protocol.

IDs are prefix plus full SHA-256 of sorted-key compact strict JSON; source IDs
use the recorded raw-source hash. Report/observation hashes cover parsed JSON
content, while the fixture README hashes the original bytes. Input order and
dictionary-key order do not change generated artifacts. Exact duplicate evidence
is deduplicated. Replicate reports remain distinct and cannot be automatically
averaged or arbitrarily picked by comparison. A fingerprint cannot mix O0/O2 or
different environments. A matrix can hold all of them on separate axes.

Recorded environments are incomplete: matching metadata does not establish
matching physical machines, host load or all inherited environment variables.
The identity policy prevents known incompatible conditions being silently mixed.

## Feature definitions and arithmetic

All 25 feature names, kinds, units, descriptions and comparison rules are stored
with every matrix/fingerprint. Ordered pass statuses are joined with ` > `.
Committed folds, propagated reads, replaced loops, expanded iterations and changed
nodes are summed across reports. Zero committed edits on a rejected pass are
facts; they do not mean a successful zero response. Without a selected pass,
edit-count features are `not_applicable` with `null` values.

Static `operations` count every real TAC instruction except `Label`; binary
operations are counted separately. CFG counts real basic blocks, excluding
synthetic entry/exit. These come from `lower_ir(parse(canonical_source))`, followed
by `build_cfg`, without machine compilation. Reparsing negative emitted literals
introduces supported unary nodes; these counts describe **saved canonical C**,
not the original in-memory transformed AST. They are never hardware counts.

For original value b and transformed value v:

```text
delta = v - b
response = (v - b) / b, only for finite b > 0 and finite v >= 0
```

Negative response means reduction. Missing/nonpositive baselines give a missing
response with a reason. A skipped/rejected pipeline has no transformed-response
value even when its observed static count is unchanged. Its raw count difference
may legitimately be zero. An applied pass may also legitimately have zero change
in a selected structural measurement.

Timing imports first cross-check successful compilation and complete matching
validation observations, sanitizer capability and actual compiler availability.
An `observed_equivalent` label cannot override contradictory returns or failed
compilation/capability evidence. Imports audit the AB/BA sample schedule, full
returned values/streams/status, valid flags, units, requested counts, and untimed warm-ups. Pure Phase 5
statistics and reliability are recomputed from retained samples. Inconsistent
evidence keeps its raw values but marks derived features invalid. Only completed,
sanitized observed-equivalent results can be valid performance observations.
Timing reliability remains distinct from observation validity.

## Comparison method and interpretation

Default `strict` alignment requires the same source, ordered pipeline and complete
configuration identity. Missing dimensions remain explicit exclusions. Alternative
side-by-side policies deliberately relax one dimension:

- `configuration`: align source/pipeline, permitting actual compiler identity,
  optimization/flags differences while requiring matching environment, target,
  other execution settings and measurement protocol.
- `program`: one observation per side, same pipeline/configuration, source may
  differ. Scores describe program profiles, not compiler behavior.
- `pipeline`: one observation per side, same source/configuration, sequence may
  differ; shared pass versions/parameters remain compatible.

Schema or feature-definition/unit mismatches and incompatible known conditions
produce an incompatible result with reasons. Ambiguous replicate alignment is
excluded. Numeric values must be finite and valid. Missing, invalid, unavailable,
unreliable and merely descriptive timing components cannot enter a score. Their
values, validity/reliability and reasons stay visible in the report.

For a valid categorical feature, distance is 0 when values match and 1 otherwise.
For a valid numerical feature with values a and b:

```text
d(a,b) = |a-b| / (|a|+|b|)
d(0,0) = 0
D = sum(weight_i * d_i) / sum(weight_i)
S = 1 - D
```

The numerical rule is symmetric, bounded in [0,1], unitless and defined for zero
or negative responses. Scaling operands before subtraction prevents overflow.
Positive finite feature weights default to 1 and are configurable. Weights are
rescaled before summation. Equal weights are an explicit descriptive choice, not
a trained importance model; correlated count features can affect the result.
Per-feature distance/contribution, used and requested counts, coverage and every
exclusion are reported. Fewer than two usable dimensions by default means
`insufficient_evidence`, with `null` distance and similarity. Coverage is usable
dimensions divided by requested union dimensions, so sparse overlap is visible.
There is no learned threshold or probability claim.

The earlier plan proposed raw Euclidean/cosine vectors. This implementation
refines that sketch to one feature-aware mixed-data measure: statuses and counts
have different meanings/units, cosine has zero-vector issues, and noisy timings
cannot responsibly form a performance vector. No additional arbitrary metrics
are implemented. No performance-only score exists for the genuine Phase 5 data.

## Serialization and safe output

Matrix, fingerprint and comparison documents have independent schema version 1
and kinds `codedna.response_matrix`, `codedna.fingerprint`, `codedna.comparison`.
Feature schema is `codedna.features.v1`. Each feature includes `value`, `validity`,
`reliability`, reasons and a JSON pointer/derivation back to its originating
report. Original report JSON, source/config/pipeline identity and environmental
metadata survive round trips. Strict JSON rejects duplicate keys, NaN/Infinity
and overflowing numbers. A returned dictionary is detached from its record.

Comparison JSON embeds both complete input fingerprints, including their original
report provenance and experiment/feature definitions, so its interpretation does
not depend on locating a separate file by hash.

CSV is a stable long-form export for later visualization. Rows preserve artifact,
observation and axis identifiers, named feature/group/kind/unit, values,
validity/reliability, exclusions and provenance. Comparison rows preserve used
and excluded dimensions, contributions and overall availability/coverage. Missing
values are blank; actual zeros remain zero. JSON is the round-trip interchange;
CSV is a documented flat projection, not an alternate lossless report parser.

Every output is preflighted against all input paths, output aliases, symlinks,
directories and special files using the existing public path validator. Payloads
are serialized before filesystem mutation; all sibling temporary files are
prepared before atomic per-file replacement. Multi-file exports are not one
transaction. Phase 5 raw/summary CSV headers and JSON remain unchanged.

Exact feature CSV header (matrix and fingerprint):

```csv
artifact_kind,artifact_id,observation_id,benchmark_id,source_id,pipeline_id,configuration_id,feature,group,kind,unit,value,validity,reliability,reasons,provenance
```

Exact comparison CSV header:

```csv
artifact_kind,artifact_id,status,row_type,dimension_key,left_fingerprint_id,right_fingerprint_id,left_observation_ids,right_observation_ids,feature,group,kind,unit,left_value,right_value,left_validity,right_validity,left_reliability,right_reliability,left_reasons,right_reasons,weight,usable,reasons,difference,contribution,side,observation_id,distance,similarity,usable_dimensions,requested_dimensions,coverage
```

CSV list/dictionary cells use strict JSON, avoiding ambiguous semicolon parsing
for reasons or provenance. Rows are deterministically sorted. Comparison row
types are `dimension`, `excluded_observation`, `incompatibility`, or `summary`.
Fingerprint rows use the fingerprint's ID; its parent matrix ID stays in JSON.

## Genuine demonstrations — observed 2026-10-18

All commands below reuse complete, genuine Phase 5 reports. They invoke no
compiler or new measured process. Use the checkout's `.venv` Python, or activate
it and use `python` as shown. The acceptance run generated fourteen JSON/CSV pairs
under [`results/phase6/acceptance/`](../results/phase6/acceptance/) and retained
every actual CLI invocation, return code, stdout and stderr in its
[`manifest.json`](../results/phase6/acceptance/manifest.json). These generated
artifacts are ignored by Git; the thirteen curated input reports are versioned.

Generate a smaller actual response matrix and independent fingerprints:

```sh
python -m compiler --matrix --benchmark-report examples/observations/phase5/constants-O0.json --benchmark-report examples/observations/phase5/constants-O2.json --output results/phase6/pair.json --csv
python -m compiler --fingerprint --benchmark-report examples/observations/phase5/constants-O0.json --output results/phase6/acceptance/constants-O0.fingerprint.json --csv
python -m compiler --fingerprint --benchmark-report examples/observations/phase5/constants-O2.json --output results/phase6/acceptance/constants-O2.fingerprint.json --csv
python -m compiler --fingerprint --benchmark-report examples/observations/phase5/unroll-O0.json --output results/phase6/acceptance/unroll-O0.fingerprint.json --csv --inspect-features
```

Repeat `--benchmark-report PATH` for all thirteen reports to reproduce the full
matrix; the exact argument list is in the manifest. It has **9 source identities,
4 pipeline identities, 5 configurations, 13 observations and 25 feature
definitions**. Its 325 feature rows preserve **45 missing values**. All 65
performance-group cells are marked unreliable or unavailable. The five separate
configurations include primary O0/O2, the negative-arithmetic 1/5 protocol,
unsanitized execution and the three-second timeout protocol. They are not mixed
into one fingerprint. Exact duplicate import and reverse-order import reproduce
the same complete matrix and ID:

```text
matrix_c36d8834e22ceba15161a0893eb0c196a2abeaa70a0bc1b566010ed907b3e0ef
```

Actual extracted structural values (identical at O0/O2 for each primary source):

| Source / sequence | Folds | Propagated reads | Unrolled loops / iterations | Canonical-C TAC original → transformed | TAC response |
| --- | ---: | ---: | ---: | ---: | ---: |
| constants_return257.c / constants | 2 | 1 | 0 / 0 | 4 → 2 | -0.5 |
| unroll_positive.c / unroll | 0 | 0 | 1 / 4 | 12 → 21 | +0.75 |
| combined.c / constants → unroll → constants | 12 | 16 | 1 / 4 | 16 → 13 | -0.1875 |
| negative_math.c / constants | 6 | 2 | 0 / 0 | 9 → 6 | -0.3333333333333333 |

Unrolling increases static operations because it expands the body; this says
nothing about dynamic instructions or performance. Rejected declarations retain
`pipeline.status="rejected"`, zero committed loop/iteration counts, TAC 11→11,
delta 0, **missing response** (`no_applied_pass`) and no runtime ratio. UB and
timeout reports retain their actual execution status and absent performance.

All six required process median ratios survive unchanged in observations:

| Sequence | O0 ratio | O2 ratio | Reliability / scoring |
| --- | ---: | ---: | --- |
| constants | 1.002010891400634 | 0.9986173674898228 | unreliable / excluded |
| unroll | 0.9995925965869535 | 1.000297539878562 | unreliable / excluded |
| constants → unroll → constants | 1.0030063036673513 | 1.0023730057957578 | unreliable / excluded |

Each retains `process_startup_scope`, `iqr_overlap` and
`dispersion_exceeds_difference`; constants-O0 also retains `high_variability`.
The negative-arithmetic control also remains unreliable. None is a proven
speedup. Imported values are preserved with original precision; no outlier
removal, zero filling or overhead correction occurs.

Compare the saved constants fingerprints:

```sh
python -m compiler --compare-fingerprints results/phase6/acceptance/constants-O0.fingerprint.json --against results/phase6/acceptance/constants-O0.fingerprint.json --output results/phase6/acceptance/self.json --csv
python -m compiler --compare-fingerprints results/phase6/acceptance/constants-O0.fingerprint.json --against results/phase6/acceptance/constants-O2.fingerprint.json --alignment configuration --output results/phase6/acceptance/configuration.json --csv
python -m compiler --compare-fingerprints results/phase6/acceptance/constants-O0.fingerprint.json --against results/phase6/acceptance/constants-O2.fingerprint.json --alignment configuration --feature-group performance --output results/phase6/acceptance/performance-only.json --csv
python -m compiler --compare-fingerprints results/phase6/acceptance/constants-O0.fingerprint.json --against results/phase6/acceptance/constants-O2.fingerprint.json --output results/phase6/acceptance/incompatible.json --csv
```

Actual first summary lines, in that order:

```text
Fingerprint comparison: comparable; 20/25 usable dimensions; similarity 1.0.
Fingerprint comparison: comparable; 20/25 usable dimensions; similarity 1.0.
Fingerprint comparison: insufficient_evidence; 0/5 usable dimensions; similarity unavailable.
Fingerprint comparison: incompatible; 0/0 usable dimensions; similarity unavailable.
```

The first two commands exit 0: distance 0, coverage 0.8, with 14 structural and
6 categorical compiler-status dimensions. All five performance components are
excluded. The O0/O2 result means those recorded profiles match; it establishes
neither equal machine code nor compiler-performance similarity. The last two
commands exit 6 with `null` scores; the strict comparison explains
`configuration_mismatch`. Reports are still saved. `--inspect-features` prints
values, units, validity/reliability and reasons; it uses stderr when stdout is
JSON, or accompanies the saved-output summary on stdout. JSON without `--output`
can be piped normally. Argument/file/schema errors exit 2, interrupts 130.

A genuine explicit program-profile negative control compares constants-O0 to
the existing dynamic-divzero `undefined` report, using `--alignment program`.
It reports **20/25 usable dimensions, distance 0.48028011204481796, similarity
0.5197198879551821**. The UB status is a valid categorical observation, while all
runtime metrics are missing/excluded. This nonzero profile similarity does not
make the UB program safe or equivalent. It illustrates why a score cannot replace
the existing equivalence gate. Both complete reports and their failure reasons
remain in comparison JSON.

For example, the actual constants-O0 ratio feature contains these selected JSON
fields (its complete record also has the exact report hash and JSON pointer):

```json
{"name":"performance.median_ratio","value":1.002010891400634,"validity":"valid","reliability":"unreliable","reasons":["process_startup_scope","high_variability","iqr_overlap","dispersion_exceeds_difference"]}
```

The corresponding CSV `value` is `1.002010891400634`, `unit` is `ratio`, and its
reliability remains `unreliable`. The real `pipeline.loops_unrolled` value is
`0` with unit `count`; the hardware-instruction value is a blank cell with unit
`hardware_instructions`, validity `missing`, reliability `unavailable` and an
explicit backend reason. This distinguishes a real zero from missing evidence.

`examples/comparison/` also contains original, renamed, refactored and unrelated
closed-subset sources. Pure parse/validation/constants/TAC inspection confirmed
final returns 257, 257, 257 and 7 respectively. This independently hand-checkable
expectation is not a timing campaign or held-out identification evaluation.

## Acceptance checks — passed

| Check | Observed result |
| --- | --- |
| `.venv/bin/python -m pytest -q --tb=short --showlocals` | **1709 passed**, **0 failed**, **0 skipped**, 296.50 seconds (4:56) |
| All historical Phase 1–5 tests | **1384 retained**, historical test files untouched |
| New matrix tests | **74** |
| New extraction tests | **36** |
| New strict-model tests | **37** |
| New comparison tests | **108** |
| New storage tests | **28** |
| New CLI tests | **42** |
| Genuine existing Clang data | All 13 original reports copied byte-for-byte and imported, including six required O0/O2 ratio observations |
| Real execution regression coverage | Existing genuine Clang O0/O2 and Graphviz integrations passed; no skip |
| Actual generated artifacts | 14 JSON/CSV pairs validated for exact JSON round trips, row counts, units, missing/zero/reliability markers and deterministic reverse import |
| Pure source examples | Original/renamed/refactored/unrelated parse, validate and constant-transform; final TAC returns 257/257/257/7 |
| `.venv/bin/python -m pip check` | No broken requirements found |
| `git diff --check`, local Markdown links, CSV headers | Clean whitespace, all links resolve, documented headers exactly match implementation |

The complete serial suite retains all earlier correctness assertions and requires
no exact C duration or guaranteed speedup. A preliminary run also passed all 811
Phase 1–3 cases. The 296.50-second suite duration is test-validation wall time,
not a program-performance metric. Phase 6 report commands did not invoke Clang
or collect new samples; actual machine execution occurred in regression tests.
All six primary imported ratios retain their unreliable status and original
reasons, with no performance-only score.

Current observed validation platform: **Python 3.14.5, macOS arm64, Apple Clang
21.0.0 (clang-2100.3.34.2)**, target **arm64-apple-darwin25.6.0**. Historical
Phase 5 observations record macOS 26.6.2, Apple M2, the same Clang version and
flags `-std=c11 -O0` or `-O2`, `-fsanitize=undefined`,
`-fno-sanitize-recover=all`; primary compile/run deadlines are ten seconds and
protocol is five untimed warm-ups/thirty measurements per variant. Their full
recorded platform/Python/clock/settings remain in every imported report. No
dependency, Git configuration, branch, commit or push change was made.

Only existing Apple Clang 21.0.0, macOS arm64, O0/O2 observations are available.
O0/O2 are configurations of one product. No GCC, cross-vendor identification or
Linux execution evidence is fabricated. Hardware instructions remain unavailable.
Phase 7, Streamlit pages, interactive websites and compiler classifiers have not
begun. No Git commit, push, branch or configuration change is performed.

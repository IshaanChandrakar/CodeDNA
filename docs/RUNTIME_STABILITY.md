# Runtime stability investigation — 2026-10-19

Status: accepted after two complete serial runs (1720 passed each), sensitive
repetitions, genuine Clang/export checks and final subprocess cleanup checks.
This is a follow-up to the historical Phase 5/6 gates, not Phase 7 work.

## Preserved starting point

The checkout is on `main` at Phase 5 commit `e72d37f`, with all uncommitted
Phase 6 modules, tests, fixtures and documentation present. The interrupted
investigation had made no production/test edits. A SHA-256 manifest of all 127
starting tracked/untracked project files is retained under ignored
`results/test-stability/initial-worktree-sha256.json`. No reset, branch, commit,
push, Git configuration or dependency change is part of this investigation.

Read the runner, runtime contracts, tests and Phase 4/5/6 validation reports.
`git diff 1de20f7 e72d37f -- runtime/compiler_runner.py` shows that timing and
interruption cleanup were added in Phase 5, while deadline-check order, buffered
capture and group-cleanup behavior were inherited from Phase 4. Current
Phase 6 had not changed the runner before this work.

## Reproduction evidence

The saved pytest cache has 16 runtime node IDs and one obsolete parser ID. The
obsolete ID does not exist in the current suite; it is not a parser failure.
All 16 actual runtime cases passed when invoked separately before corrections.
The cache is not a per-run failure report and cannot establish the cause of all
historical manual failures.

A diagnostic full run of all 1709 existing tests finished **1708 passed,
1 failed in 291.81 seconds**. The failure was a timed raw C `return 17` program
classified as timeout. Its process was actually still alive (`Ss`) when killed
after two seconds, and returned `-9`. This is not evidence that the completed-
process watchdog race caused that particular failure. Logs are in
`results/test-stability/baseline-full.txt` and `baseline-processes.jsonl`.

The traced run recorded 885 subprocess calls. Capture-thread count after each
recorded call was one (the main thread); no residual capture readers appeared.
No overlapping pytest/Clang jobs, zombies or abandoned CodeDNA executables were
found in initial/final snapshots. Initial process/descriptor counts were well
below their limits. Significant swap usage was observed, but neither exhaustion
nor a causal link to a timeout was demonstrated.

## Confirmed implementation defects

1. **Completed child falsely classified as timeout.** The outer watchdog tested
   its deadline before checking whether the child had exited. A deterministic
   clock/process regression returned `returncode=0, timeout=True` before the fix.
   The runner now polls/reaps at an expired deadline before deciding to kill.
   A live-child control still times out and is terminated.
2. **Short output violation hidden until EOF.** `BufferedReader.read(8192)` can
   wait for a full buffer or EOF. A child writing 1025 bytes, then sleeping with
   its pipe open, exceeded the 1024-byte limit but was reported as timeout. The
   saved result had both `timeout=True` and `output_limit=True`. `read1(8192)`
   now processes available data immediately, retaining at most the configured
   bytes. A pipe-held-open regression independently verifies detection before
   EOF. A confirmed byte violation takes priority over a coincident deadline
   after final draining.
3. **Capture storage error mislabeled as output limit.** A failure opening a
   capture file set the same event as byte overflow. A controlled failing-file
   regression returned `output_limit` instead of `os_error`. Capture failures
   now have a separate error path and trigger termination without setting the
   byte-limit flag.
4. **Darwin zombie cleanup reported as permission failure.** In 10/10 actual
   `/usr/bin/true` reproductions, `killpg(SIGKILL)` on an exited, unreaped leader
   raised `EPERM`; reaping returned zero and a subsequent group signal raised
   `ESRCH`. The diagnostic full run recorded exactly this `Z`/`EPERM` sequence
   during compiler-output limiting. `_kill_group` now rechecks/reaps on `EPERM`
   and retries group cleanup within a 100 ms cleanup-only allowance. Permission errors for live/inaccessible groups
   remain errors. Redundant second signals after successful group termination
   are avoided. Tests cover the real exited child and both genuine error cases.
5. **A cleanup failure masked the primary failure.** Deterministic fault
   injection replaced both `KeyboardInterrupt` and an original management
   error with cleanup `PermissionError`, skipping capture joins. Two further
   regressions failed before correction. Exceptional cleanup now independently
   attempts group termination, a bounded one-second reap and bounded joins of
   started captures. The original interrupt propagates with diagnostic notes;
   structured errors retain the original and cleanup diagnostics. No process
   is relaunched and failed cleanup is not described as successful termination.

The first three controlled regressions failed against the unchanged runner
(`3 failed, 1 passed` with the genuine-timeout control passing). The new
supervision module adds eleven cases; final results are recorded below.

## Separate environment/startup finding and test budgets

The implementation fixes do not remove genuine host startup delays. An initial
post-fix runner/timing test run reported **92 passed, 3 failed in 47.13 seconds**
in the diagnostic console:
constant results 1, -1 and INT_MAX exceeded the ordinary two-second budget.
These failures are retained, not relabeled as successful runs.

An intermediate sensitive round returned **28 passed, 1 failed** with output
overflow classified as `os_error` from Darwin `EPERM`. That run preceded the
bounded reap/group-disappearance correction. A subsequent warm-executable check
recorded an observed/recovered `EPERM`. Ten diagnostic three-case rounds also exposed two normal-parent
descendant cases failing their incidental one-second launch budget; that branch
now uses the functional budget while the nonterminating branch retains one
second. These development failures are recorded in `sensitive-repeat.json`,
`warm-output-eperm.json` and `eperm-traced-repeats.json`.

An explicitly separate diagnostic used a ten-second execution budget, with no
sampling before two seconds elapsed. Fresh harness number 37 (PID 4433) was
still alive after **2.022 seconds**, with recorded CPU time `0:00.00`. It later
returned the correct -1. Sampling after the observed delay found the process in dyld startup
rather than user `main`; the eventual 3.20-second wall duration includes sampling
overhead and is not an unperturbed launch time. Logs:
`results/test-stability/cold-harness-diagnostics.json` and
`over-budget-4433.sample.txt`.

Other diagnostic runs showed new executable inodes starting much more slowly
than repeated executions or hardlinks to an already executed inode. These are
diagnostic process wall times, not computational performance measurements.
Sampling changes execution and debugger-notification behavior. The specific
OS service responsible for the startup tail has **not** been identified; load,
I/O, loader and security-service explanations must not be presented as proven.
No host security or system configuration was changed.

After exceptional-cleanup corrections, two more serial runs returned **1719
passed, 1 failed in 275.32 seconds** and **1718 passed, 2 failed in 215.74
seconds**. The three failures were finite equivalence observations using the
two-second default (expected values 507, 3 and 146); each passed individually
with that same default afterward. These logs are `full-final-{1,2}.txt/.xml`
and `equivalence-isolated-before-budget-correction.json`. Despite their file
names, these were failed development gates, not accepted final runs.

Further serial full runs after the first corrections returned **1716 passed,
2 failed in 307.58 seconds** and **1717 passed, 1 failed in 281.27 seconds**
(1709 original tests plus nine regressions). All three failures were finite
Phase 5 benchmark validations using a three-second execution budget. The CLI
failure's saved JSON records original timeout/SIGKILL and transformed success
with value 146. All three passed individually with the unchanged three-second
budgets (1.92, 2.11 and 3.05 seconds for the whole tests). Logs and the saved
failure JSON remain under `results/test-stability/`; these are not passing gates.

Real Clang functional contexts now explicitly allow ten seconds: runner and
harness observations, finite equivalence comparisons, ordinary/timed status and
clock-boundary checks, benchmark/report helpers and finite Phase 4/5 CLI calls.
The distinction is the test's contract: these assert values, diagnostics,
protocol, ordering or persistence, not a short launch SLA. The timeout and probe
tests still exercise their original short deadlines. Generic CLI helpers and
mock/default-forwarding tests are unchanged; no hidden global override is used.
Assertions are unchanged. All
production defaults remain unchanged, including `execution_timeout=2`.
Intentional 0.1/1/3-second and other explicitly short deadline tests remain
unchanged, as does the CLI benchmark's explicit 0.2-second timeout case.
There is no process re-execution within a runner call, automatic pass-on-retry
mechanism, warm-start workaround, skipped failure or globally patched timeout.
A genuinely slow first launch can still exceed a caller's
configured production deadline and must be reported as timeout.

## Scope of changes

- `runtime/compiler_runner.py`: watchdog ordering, available-data capture,
  distinct capture errors, Darwin group-cleanup race, redundant-signal guard
  and bounded exceptional cleanup preserving primary diagnostics.
- `tests/test_process_supervision.py`: eleven targeted regression/control cases.
- `tests/test_compiler_runner.py`: explicit functional budgets and bounded `ps`.
- `tests/test_timed_runner.py`: explicit budget for non-timeout classifications.
- `tests/test_benchmark.py`, `tests/test_phase5_cli.py`: explicit functional
  benchmark budgets, retaining intentional timeout cases.
- `tests/test_equivalence.py`, `tests/test_harness.py`, `tests/test_phase4_cli.py`:
  explicit functional execution budgets, preserving intentional watchdogs.
- Current documentation: this report and a link/status in README/progress and
  the Phase 6 validation report.

The Phase 4/5 records, full signed return protocol, resource limits, process-group
ownership and timed/untimed shared execution path are retained. Timing still
starts before `Popen` and ends after reaping/group cleanup/capture joins;
compilation and Python observation parsing remain outside it. Capability runs
once per equivalence operation, never on each benchmark sample. No global
capability cache or weakened safety gate was introduced.

An AST comparison against `e72d37f` verifies all **591 existing `assert`
statements** in the seven modified test files are identical (comments/positions
excluded). Counts, outcome expectations and parametrizations are retained;
eleven new regression/control cases extend the 1709-test baseline to 1720.
Evidence: `results/test-stability/assertion-preservation.json`.

## Validation gate — passed

All 16 original runtime node IDs passed again individually after correction.
Every newly failing benchmark/equivalence case also passed individually at its
unchanged original deadline before the functional-budget correction.

| Check | Actual result |
| --- | --- |
| Focused final runner/regression module run | 35 passed in 7.65 s |
| Earlier sensitive repetitions | 5 x 29 passed, then 3 x 36 passed |
| Final sensitive repetitions | 3 x 39 passed (52.07, 52.58, 52.07 s) |
| Complete serial acceptance run 1 | 1720 passed, 0 failed, 0 skipped in 330.24 s |
| Complete serial acceptance run 2 | 1720 passed, 0 failed, 0 skipped in 334.19 s |

The final commands are the normal uninstrumented suite, run serially with no
parallel compiler jobs or pass-on-retry mechanism:

```console
.venv/bin/python -m pytest -q --tb=short --showlocals --junitxml=results/test-stability/gate-1.xml
.venv/bin/python -m pytest -q --tb=short --showlocals --junitxml=results/test-stability/gate-2.xml
```

Full text/JUnit records are `gate-{1,2}.txt/.xml`, with `gate-summary.json` and
`sensitive-gate.json`. Earlier failing runs remain separately retained. Both
complete runs and all final subprocess/export checks passed. The complete-suite
totals include all 1709 original cases plus eleven new regressions, with no
failures or skips. There were no intermittent failures in these final repeats.

Independent Phase 6 validation ingested all thirteen authentic JSON reports in
forward/reverse order and reproduced the unchanged matrix identity
`matrix_c36d8834e22ceba15161a0893eb0c196a2abeaa70a0bc1b566010ed907b3e0ef`.
Matrix/fingerprint/comparison JSON round-trips and CSV schemas passed (325/25/25
rows). Self-comparison used 20 dimensions with similarity 1.0; performance-only
comparison correctly remained `insufficient_evidence` with a null score.
The 33 Phase 6 source/test/fixture files and four additional interface/design
files matched their recovery checksums. Only stability notes were added to
current status/validation documentation. Evidence is
`results/test-stability/phase6-final-validation.json`.

## Genuine Clang and cleanup verification

The final checks ran on macOS 26.6.2 arm64, Python 3.14.5 and `/usr/bin/clang`
reporting Apple Clang 21.0.0 (`clang-2100.3.34.2`), target
`arm64-apple-darwin25.6.0`. Both optimization configurations used C11 and UBSan
(`-fsanitize=undefined -fno-sanitize-recover=all`). Each CLI smoke run validated
both full return values as **257**, retained two untimed warm-ups and four valid
timed samples (two per variant), and exported JSON/raw CSV/summary CSV.

| Configuration | Original process median | Transformed process median | Interpretation |
| --- | --- | --- | --- |
| `-O0` | 12.566 ms | 12.598 ms | Unreliable/undersampled |
| `-O2` | 12.782 ms | 11.854 ms | Unreliable/undersampled |

These are actual end-to-end process durations, including startup, sanitizer,
harness and supervision. Compilation is excluded. They do not establish a
computational speedup or statistical significance. Hardware counters remain
unavailable. The two-sample groups are an export/execution smoke check, not a
new performance campaign. Exact samples, summaries and metadata are
`smoke-O{0,2}.json`, with `.samples.csv`, `.summary.csv` and terminal `.txt`
files; `benchmark-final-validation.json` records independent export checks.

```console
.venv/bin/python -m compiler --benchmark --warmups 1 --repetitions 2 --opt O0 --execution-timeout 10 --csv --output results/test-stability/smoke-O0.json examples/runtime/constants_return257.c
```

A separately compiled 1025-byte writer was executed 200 times, alternating 100
plain and 100 timed calls. **200/200 returned `output_limit`**, retained exactly
1024 bytes and left no capture threads or workspace. Ten fresh exited/unreaped
`/usr/bin/true` leaders each produced raw signal `EPERM` and then cleaned up
successfully through the production helper (**10/10**). Detailed records are
`output-limit-final-stress.json` and `zombie-final-validation.json`; the serial
reproduction script is `post_gate_validation.py` under the same ignored results
directory. These are supervision diagnostics, not successful timing samples.

`pip check` found no broken requirements. `git diff --check`, an additional
trailing-whitespace scan including untracked project files, and local doc-link
checks passed. The final process snapshot found no active runner/Clang/pytest
processes. The runner's temporary workspaces were removed and no process or
descriptor exhaustion was found. Records are `static-final-checks.json`,
`cleanup-final-validation.json` and `processes-final.txt`.

Both implementation defects and environment-dependent first-launch delays were
demonstrated. The specific host service and the causal role of machine load
remain undetermined; not every historical failed invocation can be mapped to a
single cause. Correctly configured production deadlines can still expire on a
slow launch. The passing gate establishes the recorded repeatability on this
host, not an unlimited latency guarantee.

Phase 6 matrices, fingerprints, genuine input JSON, schemas and previous
transformation/compiler functionality remain in place. Phase 7 has not begun.

# Implementation plan

Updated 2026-10-16. Setup and Phases 1–4 are complete. Phases 5–7 below are pending;
phase numbers are acceptance gates, not calendar dates.
Implement one phase at a time and preserve earlier working behavior.

## Dependencies and milestones

```text
Setup (M0) → Phase 1 (M1) → Phase 2 (M2) → Phase 3 (M3)
           → Phase 4 (M4) → Phase 5 (M5) → Phase 6 (M6) → Phase 7 (M7)
```

The line wraps for readability; the dependency chain is strictly sequential.
Within Phase 2, shared AST semantic validation and IR lowering precede CFG
partitioning. Phase 3 validates pure source/AST/TAC structure and independently
expected values; Clang/process-equivalence infrastructure is implemented in
Phase 4 without beginning Phase 5 measurements.

| Milestone | Observable outcome | Gate reviewers |
| --- | --- | --- |
| M0 | Installable package structure, design contracts, setup smoke tests | All |
| M1 | Restricted C source produces real PLY tokens and a shared AST | Ishaan; Pranav checks tests |
| M2 | Valid AST produces real TAC, basic blocks, CFG and diagrams | Ishaan and Zayn |
| M3 | Two actual transformation passes with documented safety and tested outputs | Zayn; Pranav checks validation |
| M4 | Automated Clang compilation/execution with equivalence and failure handling | Pranav and Zayn |
| M5 | Repeated measurements with honest availability and provenance | Pranav |
| M6 | Missing-aware matrices and comparisons over real measurements | Pranav; all review interpretation |
| M7 | Local demonstration and reproducible baseline evaluation | All |

## Setup — M0

Preserve the existing Git repository and its README identity. Create the five
minimal packages, example/result directories, `pyproject.toml`, dependencies,
ignore rules, README, four design/progress documents and import smoke tests.
Keep future stage modules and `app.py` absent. Validate editable installation,
dependency consistency and tests. Do not modify branch/remote or push changes.

## Phase 1 — Lexical and syntax analysis (complete)

**Dependency:** M0. **Owner:** Ishaan; Pranav supports test configuration.

1. Define source spans, token records, diagnostic exceptions and AST dataclasses
   from [COMPILER_DESIGN.md](COMPILER_DESIGN.md), with deterministic serialization.
2. Implement `compiler/lexer.py` with PLY: keywords, identifiers, decimal literals,
   multi-character operators, punctuation, whitespace/comments and positions.
   Report illegal characters and unterminated comments without silently skipping.
3. Implement `compiler/parser.py` with the restricted grammar, explicit operator
   precedence, loop components, statement blocks and nearest-`if` dangling else.
   Use fresh per-parse state and avoid generated PLY tables in the working tree.
4. Populate `examples/basic/` and `examples/loops/` with small valid C fixtures.
   Add `tests/test_lexer.py`, `tests/test_parser.py` and AST serialization tests.
5. Document how to obtain tokens and structured AST using the implemented Python
   APIs; add command examples only once the actual API exists.

**Acceptance:** exact token types/values/spans for representative valid source;
correct AST shapes for declarations, precedence, assignments, nested conditions,
loops and returns; comments preserve following line/column locations; invalid
syntax/EOF/unsupported constructs produce clear diagnostics; consecutive parses
do not leak state; no unexplained PLY conflicts; all module and setup tests pass.

**Deliverable:** working tokenizer, parser and AST generator. No CFG, IR,
semantic dataflow engine, optimizer, Clang orchestration, or dashboard in this phase.

**Acceptance evidence:** PLY 3.11 works with Python 3.14.5 on macOS; the full suite
passes 243 tests (8 original setup tests plus 235 frontend tests). Actual CLI
tokens/AST JSON and invalid-file diagnostics are documented in the README. A
debug LALR build reports no unresolved conflicts and writes no generated tables.
Both valid `main` forms and every documented statement/operator are exercised.

## Phase 2 — Semantic analysis, CFG and intermediate representation (complete)

**Dependency:** M1 and the accepted AST schema. **Owners:** Ishaan (CFG/graphs),
Zayn (semantic checks/IR); Pranav supports integration tests.

1. Add symbol scopes and validation for unique declarations, declared references,
   definite initialization and reachable returns. Keep analysis separate from AST.
2. Implement `compiler/ir.py`: typed operands/instructions, genuine recursive
   three-address lowering, explicit branch targets, temporaries and text output.
3. Implement `compiler/cfg.py`: leader discovery, basic-block partitioning,
   typed control-flow edges, entry/exit and reachability over the shared IR.
4. Implement `visualization/graph_renderer.py`: deterministic AST/CFG DOT and
   optional Graphviz SVG/PNG export. Report a missing `dot` binary clearly.
5. Add unit tests for expression order, branches, loop back edges, early returns,
   scoping errors, initialized reads and CFG/IR consistency; graph rendering
   integration tests skip explicitly when the external renderer is absent.

**Acceptance:** all instructions arise from actual AST lowering; branches resolve
to existing labels; no instructions follow a terminator within a block; loop
condition/body/update edges have the correct order; return has no fallthrough;
readable IR and valid DOT are available; at least one AST and CFG render succeeds
on a machine with Graphviz; existing frontend tests still pass.

**Deliverable:** AST → IR → CFG pipeline and AST/CFG diagrams. These structures
are generated by project algorithms, not hardcoded examples or borrowed LLVM IR.

**Acceptance evidence (2026-10-15):** **530 passed, 0 failed, 0 skipped** on
macOS/Python 3.14.5/PLY 3.11, including all 243 Phase 1 cases. The 287 new tests
cover semantic scopes and initialization, conservative joins and loop facts,
defined C integer arithmetic diagnostics, exact TAC computation/ordering, actual
branch/loop/return behavior, deterministic CFG leaders/edges, DOT escaping,
renderer failures and CLI files/diagnostics. Graphviz 16.1.0 rendered genuine AST
and CFG SVG/PNG/PDF outputs in integration tests. Missing-renderer tests preserve
DOT without claiming a rendered image. Example diagrams are under ignored
`results/phase2/`. No Python dependencies were added.

Binding/dataflow lives in `compiler/semantic.py`, a justified separation from
representation/lowering; `compiler.ir.validate` preserves the planned entry point.
At the M2 gate, known constants supported semantic diagnostics only. Source
operations and branch conditions remained explicit in TAC; Phase 3 had not yet
started at that historical milestone.

## Phase 3 — Compiler transformations (complete)

**Dependency:** M2 and agreed source/IR provenance. **Owner:** Zayn; Pranav
supports correctness testing.

1. Extend shared representation support with an AST-to-C emitter. Round-trip
   emitted subset C through the frontend and validate it.
2. Implement scoped constant propagation, conservative branch joins and loop
   invalidation, plus safe C integer constant folding. Preserve unknown values.
3. Implement small full loop unrolling under documented constant-header rules,
   including safe positive/negative steps and < <= > >= comparisons as explicitly
   requested. Preserve initializer effects, updates, final induction and scope.
4. Produce independent variants and explicit ordered combinations with
   applied/not-applicable/rejected reports, statistics and provenance. Retain a
   fresh unchanged baseline and revalidate/re-lower every candidate.
5. Validate structural behavior, emitted-source round trips and independently
   derived full integer expectations with test-only arithmetic/TAC oracles. Do
   not build Clang/process/runtime-equivalence infrastructure in Phase 3; this
   follows the current request's strict boundary. Add parametrized safety tests.

**Acceptance:** actual changed AST/IR/source for eligible examples; fresh unchanged
baseline; explicit skip reasons for unsafe or unsupported loops; independently
expected full integer results in test-only oracles; coverage of branch joins, assignments in loops,
negative division/remainder, undefined-arithmetic refusal, zero trips, iteration
limit, induction writes and loop returns; no benchmark data claimed yet.

**Deliverable:** emitted original/transformed subset C, fresh transformed ASTs,
genuine TAC/CFGs, deterministic reports and tested safety within the declared
preconditions. Machine compilation, execution and runtime equivalence are supplied
by the separate Phase 4 gate below.

**Acceptance evidence (2026-10-16):** **811 passed, 0 failed, 0 skipped**, including
all 530 Phase 1–2 cases. The 281 new cases cover constant/folding safety (86),
unrolling/count/overflow/scope (70), source emission (51), combined pipeline,
provenance and reports (35), and actual CLI behavior (39). Seven new C examples
demonstrate constants, ascending/descending loops, composition and rejected
induction writes/declarations/limits. Actual constant TAC changes from seven
instructions to `base = 14`, `adjusted = 10`, `return 3`; explicit
`constants → unroll → constants` expands four combined-example iterations and
ends at `return 146`. Reports contain real edit counts and rejection reasons,
not runtime or hardware results.

Common helpers supply safe signed arithmetic, fresh IDs and transactional
revalidation. Rejected candidates restore a fresh input and zero committed stats.
The emitter resides in `compiler/codegen.py`, with the planned `compiler.ir.emit_c`
re-export; no language/API expansion is needed. Source/TAC/report/graph artifacts
are regenerable under ignored `results/phase3/`. No dependencies changed.

## Phase 4 — Compilation and execution (complete)

**Dependency:** M3. **Owner:** Pranav; Zayn supplies emitted variants and validation
contracts.

1. Implement `runtime/compiler_runner.py` with configured Clang discovery,
   argument-list subprocesses, private temporary directories and stable flags.
2. Capture compiler diagnostics and separate compilation failure, compilation
   timeout, execution timeout, signal termination and normal process exit.
3. Run baseline/variants with identical inputs, argument lists and environment.
   V1 cases use controlled literal fixtures and empty stdin/argv.
4. Integrate full-return observation and stdout/stderr/status comparisons; reject
   output mismatches before a program can enter measurement.
5. Add real Clang integration tests, invalid compilation, timeout and cleanup
   tests; clearly skip external-tool cases when unavailable.

**Acceptance:** successful local compile/run on supported macOS and Linux setups;
consistent results across original and emitted variants; mismatches and failures
are structured and distinguishable; timeout terminates the controlled process;
temporary artifacts are managed; no shell command injection via file names or
arguments; full-return differences such as 0 versus 256 are detected.

**Deliverable:** automated compilation/execution and tested equivalence gate.
Dynamic comparison validates cases, not universal semantic equivalence.

**Implemented (2026-10-16):** context-owned Clang discovery/builds/runs, immutable
runtime records, AST-based full-return harness, target assertions, bounded output,
process-group deadlines and POSIX resource limits. A known-valid capability check
tests target/sanitizer availability. Real source comparisons preserve the Phase 3
pipeline's applicability and composed provenance; rejected/unchanged passes have
an explicit `no_transformation` outcome. JSON separates deterministic results
from environmental version/platform/command/path metadata. CLI compile/run/equiv,
second-source controls, O0/O2, deadlines, sanitization and saved reports are added.
UBSan-disabled matches are inconclusive; no failure can pass equivalence.

Real module validation has exercised Apple Clang 21.0.0 on macOS arm64 at O0/O2,
including exact signed boundaries, negative division/remainder, branch/loop
behavior, positive/negative/zero-trip unrolling, final induction values, combined
passes, 1-versus-257 mismatch controls, UB, crashes, timeouts, unavailable tools,
compiler errors and cleanup. All 811 original tests passed separately. The final
complete suite passed **1111 tests, 0 failed, 0 skipped**, including all **811**
prior tests and **300** new cases (63 runner, 89 harness, 92 equivalence, 56 CLI).
Evidence is recorded in [PROGRESS.md](PROGRESS.md). Linux is not yet
validated; execution remains for trusted local fixtures rather than a security
sandbox. See [actual programs/reports/commands](PHASE4_VALIDATION.md).

## Phase 5 — Runtime measurement

**Dependency:** M4. **Owner:** Pranav.

1. Implement `runtime/benchmark.py` with warmups, configurable repetitions,
   interleaved variant order, monotonic wall timing, raw samples and aggregation.
2. Probe Linux `perf` counter support and permissions. Record event name/modifiers,
   process scope, scaling/multiplexing details and backend diagnostics.
3. Use explicit missing values and reasons when counters are unsupported,
   inaccessible or invalid. Report genuine static TAC counts separately.
4. Save schema-versioned JSON and long-form CSV with commands, flags, source
   hashes, case IDs, platform/dependency versions, run order and metric provenance.
5. Test aggregation, units, serialization, backend unavailability and failed-run
   exclusion. Collect real samples on a documented local workload; do not assert
   fragile wall-time thresholds as unit-test correctness.

**Acceptance:** repeatable protocol with recoverable raw observations; medians
and dispersion recompute from raw data; unavailable counts survive round trips;
startup overhead is disclosed; validation failures do not become measurements;
at least one real timing experiment; perf integration checked where available
and marked untested/unavailable elsewhere, rather than assumed portable.

**Deliverable:** reproducible measurement system, with clearly labeled
platform-dependent metrics and no fabricated performance claims.

## Phase 6 — Transformation-response fingerprinting

**Dependency:** M5. **Owner:** Pranav; all contributors review example semantics.

1. Implement `fingerprint/matrix.py` with named transformation/parameter rows,
   case/metric columns and `(variant - baseline) / baseline` normalization.
2. Handle zero/missing/non-finite baselines and skipped passes with distinct
   statuses; do not fill missing cells with zero.
3. Implement Euclidean distance and cosine similarity over compatible common
   cells, defined overlap thresholds, coverage, and zero-norm handling.
4. Populate `examples/comparison/` with original, renamed, structurally refactored
   and unrelated programs; document expected semantic relationships independently
   of measured scores. Compare only aligned experiments and cases.
5. Test normalization with transparent synthetic numeric fixtures used only for
   unit arithmetic tests. Generate reported research fingerprints from actual
   measured programs and retain the raw data that produced them.

**Acceptance:** hand-checkable normalization; schema/condition mismatches rejected;
zero baseline and no-overlap cases return explicit unavailable results; distance
symmetry and self-comparison where defined; real family comparisons with reported
coverage; no equivalence/probability claim inferred merely from similar scores.

**Deliverable:** working fingerprint generation and comparison. Adaptive pass
selection is still an optional research extension, not required to claim this
initial deterministic pipeline works.

## Phase 7 — Dashboard and evaluation

**Dependency:** M6 and all earlier stage contracts. **Owners:** Pranav integrates;
Ishaan supplies frontend/graphs; Zayn supplies transformations and correctness.

1. Create `app.py` for a local Streamlit demo over existing modules. Provide C
   source input, stage diagnostics, tokens, AST/CFG/IR, original/transformed C,
   pass applicability, validation status, measurements and matrices.
2. Compare two programs using compatible experiment configurations and show
   coverage, noise and missing-metric reasons alongside scores.
3. Implement documented baselines: normalized AST structural features, CFG
   shape/control-flow features, TAC opcode/features and a labeled single-run
   runtime fingerprint. Baselines consume actual generated/measured artifacts.
4. Evaluate against the same labeled original/renamed/refactored/unrelated corpus
   and controlled cases. Define feature extraction, normalization, comparison
   metric and hyperparameters for each baseline. Use held-out program families
   for threshold decisions; avoid putting variants of one family in both splits.
5. Report pairwise discrimination/retrieval metrics appropriate to corpus size,
   failures, missing coverage, repeated-run sensitivity and limitations. Single-run
   noise must be visible; no promise of outperforming baselines before evidence.
6. Add integration tests for the complete local flow, run the full test suite,
   write demo instructions and store reviewed actual evaluation artifacts.

**Acceptance:** real end-to-end local demo on supported fixtures; invalid source
and absent tools show useful messages; two-program comparison exposes its real
measurements; all four baseline definitions and results are reproducible; claims
match evidence; completed-stage tests pass; uploaded-code deployment is not
enabled without an explicit execution-isolation decision.

**Deliverable:** demonstration-ready CodeDNA and an honest lab evaluation.

## Exactly what begins next (Phase 5; not started)

The present task stops at the M4 acceptance gate. A subsequent Phase 5 request
may add repeated measurement and verified counter availability. No benchmark,
program timing metrics, instruction counts, performance datasets, response matrix,
fingerprint or dashboard implementation is included in Phase 4.

# Progress

Updated: 2026-10-16 (Asia/Kolkata). Status is recorded from completed work, not
from the existence of a design document or an empty package.

## Current task

Repository setup (M0) and Phases 1–4 (M1–M4) are complete. The existing checkout
remains on `main` with the original GitHub remote. Phase 3 began from the existing
clean Phase 2 checkout, preserved all 530 prior test cases, and did not change Git
configuration, create a branch, commit or push. Phase 4 passed its acceptance
gate with **1111 passing tests**, including all **811 prior tests**. Phases 5–7 remain pending.

| Setup item | Status |
| --- | --- |
| Inspect existing repository and preserve project identity | Complete |
| Create minimal packages and example/result directories | Complete |
| Configure Python dependencies, editable install and pytest | Complete |
| Add ignore rules and README setup instructions | Complete |
| Write architecture, compiler design and seven-phase plan | Complete |
| Validate dependency installation and smoke tests | Complete |

The setup/Phase 1–2 validation logs below are historical. Phase 3 evidence is
recorded separately below, followed by Phase 4 evidence. No phase is ongoing.

## Contributor tracking

| Contributor | Completed | Ongoing | Pending |
| --- | --- | --- | --- |
| Ishaan — Frontend | Phase 1 frontend; Phase 2 TAC-derived basic blocks/CFG and AST/CFG diagrams | No implementation tasks | Phase 7 frontend/graph demo integration |
| Zayn — Transformations | Phase 2 analysis/TAC; Phase 3 transformations/reports; Phase 4 pipeline/provenance integration | No implementation tasks | Phase 7 transformation demo |
| Pranav — Runtime/evaluation | Phase 4 Clang runner, full-return harness, equivalence/CLI and tests; all 811 prior tests retained | No implementation tasks | Phases 5–6 measurements/fingerprints; Phase 7 dashboard/evaluation |

Rows track progress by the team's agreed responsibility areas. They do not claim
that named individuals have independently authored or reviewed these changes.

## Phase gates

| Phase | Status | Evidence required to mark complete |
| --- | --- | --- |
| 1. Lexical/syntax analysis | Complete | Actual PLY tokens/AST, source diagnostics, CLI, 243 passing tests; evidence below |
| 2. Semantic analysis/CFG/IR | Complete | Real symbols/dataflow, TAC/CFG, diagrams and 530 passing tests; evidence below |
| 3. Transformations | Complete | Fresh AST passes, reports/source round trips, expected-value tests; 811 passing total |
| 4. Compilation/execution | Complete | Real Clang O0/O2 pipeline, exact full returns, mismatch/UB/failure/timeout/cleanup tests; 1111 passing total |
| 5. Measurement | Pending | Raw repeated timings, truthful counter availability, JSON/CSV provenance |
| 6. Fingerprinting | Pending | Real response matrices/comparisons, zero/missing-value tests |
| 7. Dashboard/evaluation | Pending | End-to-end demo, all four baselines, reproducible evaluation evidence |

Acceptance criteria are in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).
Update a phase to ongoing only when actual implementation begins, and to complete
only after its gate passes. Record commands, outcomes, limitations and any changed
interfaces with each status update. Do not record proposed example results as data.

## Setup validation log

Initial environment inspection: Python 3.14.5 and `/usr/bin/clang` available;
Graphviz `dot` and Linux `perf` absent. No external renderer or hardware counter
installation is needed to validate M0. No C program has been compiled or run.

Observed setup validation on macOS with Python 3.14.5:

| Check | Observed result |
| --- | --- |
| `python3 -m venv .venv` | Local environment created successfully |
| `.venv/bin/python -m pip install --no-cache-dir -r requirements.txt` | Editable project and all declared extras installed successfully |
| `.venv/bin/python -m pip check` | No broken requirements found |
| `.venv/bin/python -m pytest` | 8 passed |
| `.venv/bin/python -m pytest --collect-only -q` | 8 tests collected |
| Imports from `/private/tmp` using the virtual-environment Python | All five packages resolve to this checkout |
| TOML parsing, minimal package inspection, local Markdown links | Valid metadata; package files contain only docstrings; links resolve |
| `git diff --check` | No whitespace errors |

The first dependency installation attempt failed because sandbox DNS resolution
was blocked. A network-enabled retry succeeded; this was not a dependency-version
failure. The pip cache is outside the writable sandbox, so installation used
`--no-cache-dir`. The local `.venv`, package metadata and caches are ignored.

Resolved direct tooling versions: CodeDNA 0.0.1, PLY 3.11, graphviz 0.21,
pytest 9.1.1, Streamlit 1.65.0. These are observed versions, not an experiment
lockfile. Linux and other Python versions have not been tested in M0. `dot` and
`perf` remain absent; graph rendering and runtime measurements remain untested
because those phases have not been implemented.

## Phase 1 validation log

Validated on macOS with the existing Python **3.14.5**, PLY **3.11**, and pytest
**9.1.1** in `.venv`. No dependency versions were changed and no fallback Python
was required. PLY lexer/parser behavior is verified by actual execution, not only
by import checks.

| Command/check | Actual result |
| --- | --- |
| `.venv/bin/python -m pytest` | **243 passed, 0 failed, 0 skipped**; includes all 8 original setup tests |
| `.venv/bin/python -m pip check` | No broken requirements found |
| `python -m compiler --tokens examples/basic/minimal.c` using `.venv` | 9 genuine tokens, exit 0 |
| `python -m compiler --ast examples/basic/minimal.c` using `.venv` | Typed Program → Function → Block → Return → IntegerLiteral serialized as JSON, exit 0 |
| Invalid example CLI tests | All 6 invalid examples produce source-located errors, exit 1, no traceback/partial stdout |
| CLI file/encoding/argument tests | Exit 2 with useful stderr messages |
| Debug PLY LALR build | Zero unresolved shift/reduce or reduce/reduce conflicts; no generated table/debug files |
| Editable CLI from outside the checkout | Successfully parses a real file and returns valid JSON |

The 243 tests exercise all documented operators and statement shapes; expression
precedence/associativity, parenthesized and unary expressions, dangling else with
and without braces, declaration/assignment loop initializers, nested loops,
immutable traversal, unique/deterministic node IDs, spans and real JSON hierarchy.
They also cover comment/newline locations, huge malformed/range-invalid literals,
unsupported keywords/operators, syntax/EOF failures, lexer reuse and parse state
after errors. Nine valid and six intentionally invalid C fixtures are checked.

### Phase 1 acceptance checklist

- [x] Supported C is tokenized by PLY with typed values and original lexemes.
- [x] PLY parser constructs typed shared ASTs from actual source.
- [x] Precedence, associativity, parentheses and unary expressions are correct.
- [x] Conditions, nearest-if `else`, loops, blocks and returns parse correctly.
- [x] Lexical and syntax diagnostics carry exact source locations, including EOF.
- [x] ASTs serialize to JSON and expose child/preorder traversal.
- [x] `python -m compiler --tokens/--ast FILE` works on genuine examples.
- [x] Automated lexer/parser/AST and CLI tests pass.
- [x] All original setup tests still pass.
- [x] README, compiler design, architecture and roadmap describe the actual state.

### Decisions and limitations

The documented AST and grammar were retained. `compiler/diagnostics.py` is a small
shared source-map/error module so both lexer and parser use the same positions
without coupling AST classes to PLY. `compiler/__main__.py` implements the CLI.
Frozen/slotted dataclasses, tuple block items and string operator enums make the
shared tree stable and easy to inspect. Parentheses widen the existing expression
span without introducing an undocumented node kind. Expression grammar is layered;
only dangling-else resolution requires explicit precedence.

Phase 1 is syntax-only: duplicate/undeclared variables, initialization, integer
arithmetic safety, scope, required return paths and termination are not checked.
No symbol tables, CFG, TAC/LLVM IR, optimization, C execution or measurements have
been implemented. Unsupported syntax is rejected rather than passed to Clang.
There is no C preprocessing/line splicing, external input or I/O; literals are
restricted to documented decimal magnitudes. Error recovery stops at the first
encountered source error. Deep AST JSON serialization is subject to Python's
recursion limit; the CLI handles that failure without a traceback. Linux and other
Python versions have not been executed in this task.

## Phase 2 validation log — 2026-10-15

Implemented `compiler/semantic.py`, `compiler/ir.py`, `compiler/cfg.py`, and
`visualization/graph_renderer.py`; minimally extended shared diagnostics and CLI.
The lexer, parser, AST classes and all Phase 1 tests/interfaces were preserved.
The existing Python 3.14.5, PLY 3.11 and pytest 9.1.1 worked without dependency
changes. External Graphviz **16.1.0** was installed via Homebrew to satisfy actual
render validation; Homebrew also installed/upgraded its system dependencies.
Python requirements and project configuration were unchanged.

| Validation | Actual result |
| --- | --- |
| `.venv/bin/python -m pytest` | **530 passed, 0 failed, 0 skipped** |
| Existing Phase 1 test files | All original **243** cases remain passing |
| `tests/test_semantic.py` | 111 passed: binding/scopes, initialization, branch/loop facts, C arithmetic, return/dead-code diagnostics |
| `tests/test_ir.py` | 52 passed: typed operations, actual expected results via a test-only TAC evaluator, branch/loop/return behavior, provenance and determinism |
| `tests/test_cfg.py` | 44 passed: actual TAC leaders/edges, loops/back edges, returns, dead blocks and invalid manual IR |
| `tests/test_graph_renderer.py` | 28 passed, including 7 actual external rendering cases |
| `tests/test_phase2_cli.py` | 52 passed, including 2 actual CLI SVG renders, missing-renderer fallback and file-alias protection |
| Rendered examples | `results/phase2/arithmetic_ast.svg`, `sum_cfg.svg`, `sum_cfg.png`, and DOT sidecars generated from real example programs |

Graph rendering was first checked with no external `dot`: 7 rendering tests and
2 CLI SVG tests explicitly skipped while all fallback tests passed. After
Graphviz installation, those 9 cases ran and passed in the complete suite.
The rendered loop CFG was visually inspected. No runtime or performance
measurements were made, and the TAC evaluator exists only in tests.

### Phase 2 acceptance checklist

- [x] Lexical block/loop scope, undeclared references and documented no-shadowing rule.
- [x] Definite initialization through assignments and continuing conditional branches.
- [x] Source-located known-zero/overflow errors, return checks and unreachable warnings.
- [x] Typed, deterministic TAC with genuine expression and control-flow lowering.
- [x] Correct branch joins, repeated loop conditions, updates/back edges and early returns.
- [x] TAC-derived basic blocks, typed edges, entry/exit and structural reachability.
- [x] Real AST/CFG DOT and Graphviz SVG/PNG/PDF rendering; explicit fallback/error behavior.
- [x] CLI semantic/TAC/CFG/graph inspection; Phase 1 behavior preserved.
- [x] Full tests pass and README/design/architecture/roadmap/progress reflect actual state.
- [x] No Phase 3 transformations, C execution, measurements, commits, branches or Git configuration changes introduced.

### Decisions and practical limits

Semantic annotations remain separate from immutable ASTs. The small
`compiler/semantic.py` module keeps binder/dataflow concerns out of IR records;
`compiler.ir.validate` retains the planned public interface. Conditional facts
join only continuing paths. Every `if` arm and every loop's zero-iteration path
are conservatively possible, even with literal conditions. Loop-written values
lose known constants; no fixed-point range analysis or termination proof is
claimed. Some statically unreachable constant arms can therefore still produce
semantic errors, and some runtime-dependent faults remain undetected.

Constants are used for diagnostics only; AST/TAC arithmetic and conditional edges
are not folded or pruned. Structurally dead statements after returns are warned
and omitted in lowering; dead declarations/names are still checked. Both division
and remainder use signed 32-bit C rules, including undefined zero divisors,
overflow and `INT_MIN / -1` / `INT_MIN % -1`. Future execution must verify target
integer assumptions and validate defined inputs. CFG reachability is structural,
not an execution-trace claim. External-renderer availability is optional for DOT
export. Linux and other Python versions were not executed in this task.

## Phase 3 validation log — 2026-10-16

Implemented fresh-AST constant propagation/folding, safe full loop unrolling,
shared arithmetic/cloning/report helpers, explicit ordered orchestration, and
pure C source emission. Existing parse/analyze/TAC/CFG/visualization APIs and all
530 previous tests were retained. No dependency, supported-source-language or
Git configuration change was needed. Validation used Python 3.14.5, PLY 3.11
and pytest 9.1.1 on macOS.

| Validation | Actual result |
| --- | --- |
| `.venv/bin/python -m pytest` | **811 passed, 0 failed, 0 skipped** |
| Original Phase 1–2 tests | All **530** cases remain passing |
| `tests/test_constant_folding.py` | 86 passed: arithmetic/comparisons, signed division/remainder, bounds, unsafe preservation, scope/joins/loops, stable repeats |
| `tests/test_loop_unrolling.py` | 70 passed: signed counts, zero trips, final updates, boundaries, scope/IDs and every rejection class |
| `tests/test_codegen.py` | 51 passed: original cases, canonical C round trips, negative nodes/INT_MIN, dangling else and immutability |
| `tests/test_transformations.py` | 35 passed: exact sequences, math-derived expected values, fresh baselines, composed origins, rollback and serializable committed reports |
| `tests/test_phase3_cli.py` | 39 passed: real success/rejection examples, TAC/AST/CFG/C/report modes, limits and established exit codes |

Actual constant example TAC before transformation has seven instructions. After
`constants` it is `base = 14`, `adjusted = 10`, `return 3`. Its report is
`applied` with 4 folds, 2 propagated reads and 6 changed AST nodes. The
`combined.c` sequence `constants → unroll → constants` reports three applied
passes, one loop/four iterations expanded, and final TAC `return 146`.
`rejected_induction.c` reports `rejected` / `INDUCTION_WRITE`, preserving the
program and recording zero committed unrolls. Declaration and 40-trip limit
examples report `DECLARATION_IN_BODY` and `ITERATION_LIMIT` respectively.

Review added explicit raw-expression regressions for unknown numerators with
known-zero divisors (`x/(1-1)`, `x%(2-2)`): complete unsafe structure is preserved.
Revalidation tests expose previously unknown faults after unrolling and verify
whole-pass rollback with zeroed stats. Repeated passes and multi-pass provenance
are deterministic; final syntax nodes never share identity with the original.

Regenerable ignored artifacts under `results/phase3/` include actual
`constants_before.tac`, `constants_after.tac`, `constants_report.json`,
`combined_report.json`, `rejected_report.json`, `combined_transformed.c` and
`combined_cfg.svg`/`.dot`. No emitted C was compiled or run. Test-only pure
arithmetic/TAC oracles check independently expected full integer values; there
is no process/runtime-equivalence infrastructure or performance data.

### Phase 3 acceptance checklist

- [x] Actual safe constant propagation and folding; conservative scoped transfers.
- [x] Signed C division/remainder and overflow/undefined-operation refusal.
- [x] Proven constant-loop expansion with positive/negative steps and exact final values.
- [x] Explicit rejected/not-applicable reasons, limits and committed statistics.
- [x] Fresh ASTs, unique copy IDs, immutable original/provenance and stable repeats.
- [x] Exact ordered combinations with serializable reports and safe rollback.
- [x] Semantic revalidation and genuine transformed TAC/CFG; pure C emission.
- [x] Seven real C examples and successful/rejected CLI output demonstrations.
- [x] All 530 previous tests and 281 new tests pass; documentation matches output.
- [x] No Phase 4 compilation/execution/equivalence, benchmarking, fingerprints or dashboard.

### Phase 3 decisions and limitations

`common.py` centralizes safe arithmetic, cloning/provenance and transactional
report finalization; `pipeline.py` keeps ordering explicit. `codegen.py` separates
pure formatting from typed IR, while `compiler.ir.emit_c` retains the planned
public API. The source grammar is unchanged; folded negative internal literal
nodes emit through existing unary syntax, including the safe INT_MIN expression.

Constant environments join only continuing paths and clear loop-written facts;
there is no branch pruning, unsafe algebraic identity or speculative rewrite.
Unrolling extends the original positive-only sketch, as explicitly requested,
to safe signed steps and < <= > >= comparisons. It still requires constant
headers, straight-line assignment/block/empty bodies, no induction writes,
declarations, conditionals, returns or nested loops, and in-range final updates.
Maximum iterations default to 32 with a supported 0..1024 configuration range.
Rejected inner loops are not separately expanded. If candidate revalidation
fails, the whole pass (including other attempted expansions) is rolled back.

These checks are not universal semantic equivalence, termination or runtime
arithmetic proofs. Linux and other Python versions were not tested. Original
runtime-dependent faults can remain unknown; operation order is preserved for
defined inputs. Reports contain compiler edit counts, not machine instruction
or performance improvements. CLI rejection inspection exits 0 with explicit
status; source errors still exit 1 and argument/file/render errors exit 2.

## Phase 4 validation log — 2026-10-16

Implemented `runtime/models.py`, `runtime/compiler_runner.py`, `runtime/harness.py`
and `runtime/equivalence.py`; extended only the CLI and runtime package description
in existing implementation files. Frontend/analysis/TAC/CFG/emitter and Phase 3
pass implementations and every prior test remain unchanged. Seven new runtime
fixtures and four test modules exercise actual processes, not just a simulated
comparison. No dependencies, branches, Git settings, commits or pushes changed.

Observed environment: macOS arm64, Python 3.14.5, pytest 9.1.1, Apple Clang
**21.0.0 (clang-2100.3.34.2)**, target **arm64-apple-darwin25.6.0**. Actual flags
`-std=c11 -O0 -fsanitize=undefined -fno-sanitize-recover=all` and separate `-O2`
conditions. All integration tests ran locally with actual Clang available.

| Validation | Actual result |
| --- | --- |
| Original test files, excluding all four Phase 4 modules | **811 passed** |
| Harness module | **89 passed**, including 16 real O0/O2 compile/run checks |
| Equivalence module | **92 passed** in the final gate; real O0/O2 pairs, negative controls, UB and timeouts |
| CLI module | **56 passed**, real commands, reports, diagnostics and alias protection |
| Runner module | **63 passed** in the final gate, including FIFO-observation protection |
| `.venv/bin/python -m pytest -q` | **1111 passed, 0 failed, 0 skipped**, 196.27 seconds of test-suite wall time |
| `.venv/bin/python -m pip check` | No broken requirements found |
| `git diff --check` and local Markdown links | Clean; links resolve |

The first full gate ran 1105 cases: 1104 passed and one timeout-fixture assertion
failed because a trivial sanitized program itself exceeded that test's one-second
deadline. The runner correctly reported timeout. Both equivalence timeout tests
now use three seconds to include process/sanitizer startup; exact assertions were
retained, with no retry. Both focused tests then passed. Six additional real UB
cases cover subtraction overflow, multiplication overflow and INT_MIN remainder
at O0/O2. The final full gate passed all **1111 cases**. This includes **300** new
cases and the unchanged **811** prior cases; the suite duration above is test-run
evidence, not a measured runtime/performance result for compiled programs.

Real CLI evidence: constants **257/257**, positive unrolling **64/64**, negative
unrolling at O2 **89/89**, combined **146/146**, zero-trip final induction **12/12**,
negative division/remainder **-201/-201** all report `observed_equivalent` (exit 0).
Full return observations have wrapper process status 0, independently of signed
integer value; INT_MIN/MAX also run. Deliberate **1/257** reports
`different_behavior` (exit 5). Infinite-loop fixture reports `timeout` (exit 4),
loop-carried zero divisor `undefined_behavior` (exit 4), and rejected unrolling
`no_transformation` with matching **3/3** (exit 6). Missing compiler is
`unavailable` (exit 6). Invalid raw generated C yields actual Clang diagnostics,
compiler status 1, and compilation `failure`.

Private workspaces, bounded output, process-tree termination, resource controls,
crash/missing/nonexecutable artifacts and cleanup have actual tests. A wrapper
records a strict versioned full integer result file and asserts target width.
Reports retain exact input hashes, emitted C, harness hashes, settings,
applicability and origin maps; environmental paths/version/platform are separate.
Representative complete JSON reports were inspected and regenerated under ignored
`results/phase4/`. Matching deterministic result sections are checked across runs.

Review found that unconstrained extra flags could disable UBSan. They are now
restricted to diagnostics, excluding preprocessor/assembler/linker forwarding;
regressions cover sanitizer/semantic/optimization overrides. Matching runs with
UBSan disabled remain inconclusive. There is no silent sanitizer fallback and
rejected/unchanged pipelines cannot pass as validated transformations.

Execution remains for trusted local fixtures, not hostile uploads. There is no
filesystem/network security isolation or default total address-space cap.
Inherited host environment is consistent within a pair but not fully serialized.
UBSan/finite executions do not prove arbitrary safety, termination or mathematical
equivalence. Linux and other Python/compiler versions remain unverified.
Full file inventory, original/transformed C, commands and selected real output
are in [PHASE4_VALIDATION.md](PHASE4_VALIDATION.md).

### Phase 4 acceptance checklist

- [x] Discover actual Clang, record version/settings and preserve compiler diagnostics.
- [x] Independently compile original/transformed validated C using C11, O0 and O2.
- [x] Capture full signed 32-bit returns separately from wrapper status, including boundaries.
- [x] Exercise real constant/loop/combined comparisons, branches and final induction values.
- [x] Detect deliberate 1/257 and other mismatches, dynamic arithmetic UB and timeouts.
- [x] Retain rejected/inapplicable pass reports without claiming optimization validation.
- [x] Bound output, terminate process groups and clean private build/run artifacts.
- [x] Inspect deterministic structured reports, CLI diagnostics and saved failure statuses.
- [x] Run all 1111 tests without skips, preserving all 811 prior tests.
- [x] Update requested documentation and stop before Phase 5; no commit, push, branch or Git configuration changes.

## Next development task — Phase 5 (not started)

The task stops at the Phase 4 gate. No repeated measurements, runtime metrics,
instruction counts, performance CSV, response matrix, fingerprints or dashboard
have been introduced.

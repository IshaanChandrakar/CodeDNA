# Progress

Updated: 2026-10-16 (Asia/Kolkata). Status is recorded from completed work, not
from the existence of a design document or an empty package.

## Current task

Repository setup (M0) and Phases 1–3 (M1–M3) are complete. The existing checkout
remains on `main` with the original GitHub remote. Phase 3 began from the existing
clean Phase 2 checkout, preserved all 530 prior test cases, and did not change Git
configuration, create a branch, commit or push. Phases 4–7 remain pending.

| Setup item | Status |
| --- | --- |
| Inspect existing repository and preserve project identity | Complete |
| Create minimal packages and example/result directories | Complete |
| Configure Python dependencies, editable install and pytest | Complete |
| Add ignore rules and README setup instructions | Complete |
| Write architecture, compiler design and seven-phase plan | Complete |
| Validate dependency installation and smoke tests | Complete |

The setup/Phase 1–2 validation logs below are historical. Phase 3 evidence is
recorded separately below. No phase is ongoing.

## Contributor tracking

| Contributor | Completed | Ongoing | Pending |
| --- | --- | --- | --- |
| Ishaan — Frontend | Phase 1 frontend; Phase 2 TAC-derived basic blocks/CFG and AST/CFG diagrams | No implementation tasks | Phase 7 frontend/graph demo integration |
| Zayn — Transformations | Phase 2 analysis/TAC; Phase 3 safe constant pass, full unrolling, C emitter, applicability reports and provenance | No implementation tasks | Phase 4 equivalence integration; Phase 7 transformation demo |
| Pranav — Runtime/evaluation | 530 prior tests retained; 281 Phase 3 tests, ordered pipeline/CLI and expected-value validation | No implementation tasks | Phases 4–6 runtime/equivalence/measurements/fingerprints; Phase 7 dashboard/evaluation |

Rows track progress by the team's agreed responsibility areas. They do not claim
that named individuals have independently authored or reviewed these changes.

## Phase gates

| Phase | Status | Evidence required to mark complete |
| --- | --- | --- |
| 1. Lexical/syntax analysis | Complete | Actual PLY tokens/AST, source diagnostics, CLI, 243 passing tests; evidence below |
| 2. Semantic analysis/CFG/IR | Complete | Real symbols/dataflow, TAC/CFG, diagrams and 530 passing tests; evidence below |
| 3. Transformations | Complete | Fresh AST passes, reports/source round trips, expected-value tests; 811 passing total |
| 4. Compilation/execution | Pending | Clang pipeline, identical cases, mismatch/error/timeout tests |
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

## Next development task — Phase 4 (not started)

After a separate Phase 4 request, implement Clang compilation and controlled
execution of emitted baseline/variant sources, identical cases/environment,
full return/output equivalence, cleanup, compiler/runtime diagnostics and
timeouts. Preserve the Phase 1–3 interfaces and transformation sequence metadata.
Runtime, fingerprint and dashboard packages still contain only minimal package
files; measurements and all later phases remain pending.

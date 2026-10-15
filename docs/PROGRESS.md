# Progress

Updated: 2026-10-15 (Asia/Kolkata). Status is recorded from completed work, not
from the existence of a design document or an empty package.

## Current task

Repository setup (M0) and Phases 1–2 (M1–M2) are complete. The existing checkout
remains on `main` with the original GitHub remote. This Phase 2 task preserved the
pre-existing uncommitted Phase 1 files and did not change Git configuration,
create a branch, commit or push. Phases 3–7 remain pending.

| Setup item | Status |
| --- | --- |
| Inspect existing repository and preserve project identity | Complete |
| Create minimal packages and example/result directories | Complete |
| Configure Python dependencies, editable install and pytest | Complete |
| Add ignore rules and README setup instructions | Complete |
| Write architecture, compiler design and seven-phase plan | Complete |
| Validate dependency installation and smoke tests | Complete |

The setup/Phase 1 validation logs below are historical. Phase 2 evidence is
recorded separately below. No phase is ongoing.

## Contributor tracking

| Contributor | Completed | Ongoing | Pending |
| --- | --- | --- | --- |
| Ishaan — Frontend | Phase 1 frontend; Phase 2 TAC-derived basic blocks/CFG and AST/CFG diagrams | No implementation tasks | Phase 7 frontend/graph demo integration |
| Zayn — Transformations | Phase 2 scopes/dataflow/diagnostics, typed TAC and genuine lowering | No implementation tasks | Phase 3 emitter/constant propagation/folding/unrolling/correctness; Phase 7 transformation integration |
| Pranav — Runtime/evaluation | All 243 Phase 1 tests retained; 287 Phase 2 tests and CLI integration validated | No implementation tasks | Phase 3 correctness harness support; Phases 4–6 runtime/measurements/fingerprints; Phase 7 dashboard/evaluation integration |

Rows track progress by the team's agreed responsibility areas. They do not claim
that named individuals have independently authored or reviewed these changes.

## Phase gates

| Phase | Status | Evidence required to mark complete |
| --- | --- | --- |
| 1. Lexical/syntax analysis | Complete | Actual PLY tokens/AST, source diagnostics, CLI, 243 passing tests; evidence below |
| 2. Semantic analysis/CFG/IR | Complete | Real symbols/dataflow, TAC/CFG, diagrams and 530 passing tests; evidence below |
| 3. Transformations | Pending | Actual pass changes, skip reasons, full-return correctness tests |
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

## Next development task — Phase 3 (not started)

After a separate Phase 3 request, implement AST-to-C emission, genuine scoped
constant propagation/folding, safe loop unrolling with applicability reports,
and full-return correctness tests on defined inputs. Preserve the Phase 1–2 APIs
and revalidate/re-lower transformed ASTs. Transformation, runtime, fingerprint
and dashboard modules remain unimplemented.

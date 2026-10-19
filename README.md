# CodeDNA

**Adaptive Compiler-Guided Transformation-Response Fingerprinting for Semantic Program Identification**

CodeDNA is a Compiler Design Lab project exploring whether the way a program
responds to meaning-preserving compiler transformations can help identify
semantically similar programs. The intended pipeline accepts a restricted C
program, constructs an AST, CFG, and three-address IR, applies constant
propagation/folding and loop unrolling, and compares changes in measured runtime
behavior against the original program.

Repository: [Trifecta-tech/CompilerFallSem](https://github.com/Trifecta-tech/CompilerFallSem).

## Current status

Runtime stability follow-up (2026-10-19): confirmed process-supervision defects
are corrected. Two complete serial runs passed **1720 tests each**, retaining all
1709 prior cases and adding eleven regressions; intentional timeout tests and
the two-second production default remain intact. The earlier totals below are
historical gates. See [the investigation](docs/RUNTIME_STABILITY.md).

**Phases 1–6 are complete:** the PLY frontend, typed AST, semantic analysis, TAC,
CFGs/diagrams, constant propagation/folding, conservative full loop unrolling,
ordered pass reports, C emission, controlled Clang builds/execution and observed
equivalence reports. The accepted Phase 4 gate passed **1111 tests**, including
all **811 Phase 1–3 tests**. Phase 5 now implements equivalence-gated repeated
process measurements, descriptive statistics and JSON/CSV export. The Phase 5
gate passed **1384 tests, 0 failed, 0 skipped**, retaining all **1111** prior cases
and adding **273** cases. Six genuine O0/O2 baseline conditions preserve 360 timed
samples and 60 untimed warm-ups; none establishes an algorithmic speedup. Evidence is in
[PROGRESS.md](docs/PROGRESS.md) and [PHASE5_VALIDATION.md](docs/PHASE5_VALIDATION.md).
Phase 6 response matrices, descriptive fingerprints and missing-aware comparison
passed the complete serial gate: **1709 passed, 0 failed, 0 skipped** (all 1384
prior cases plus 325 new cases). Genuine report ingestion, deterministic JSON/CSV,
compatibility and unreliable-timing exclusions are validated. Full evidence is
in [PHASE6_VALIDATION.md](docs/PHASE6_VALIDATION.md).
**Phase 7 has not begun; the dashboard remains absent.**

The research hypothesis is to be evaluated: a similar fingerprint is evidence
for investigation, not proof of semantic equivalence. Timing noise, constant
programs, and transformations that do not apply can reduce discrimination.

## Setup

Use Python **3.11 or newer** on macOS or Linux. From the existing checkout:

```sh
cd /Users/pranav/Documents/CodeDNA
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
python -m pytest
```

Use the checkout's actual path on another machine. Installation requires access
to a Python package index. `requirements.txt` installs the editable project with
the `test` and `dashboard` extras; versions live in `pyproject.toml`. For a lighter
frontend/test environment, use `python -m pip install -e '.[test]'` instead.
Version ranges are initial compatibility constraints, not a lockfile. Record
resolved versions with each future experiment; cross-platform Python versions
and external tools still need an implementation-stage compatibility matrix.

### Dependencies and external tools

| Component | Purpose | Needed when |
| --- | --- | --- |
| PLY | Genuine lexer and LALR parser | Phase 1 |
| Python `graphviz` | Declared visualization binding; DOT export itself uses pure Python | Phase 2 |
| Graphviz `dot` executable | Optional rendering of DOT to SVG/PNG/PDF | Phase 2 |
| Clang/LLVM | Compile and execute emitted C | Phases 4–5 |
| pytest | Setup and module tests | Now and every phase |
| Streamlit | Demonstration dashboard | Phase 7 |
| Linux `perf` | Possible future hardware-counter backend | Not required or implemented in Phase 5 |

The Python Graphviz package does not install `dot`. DOT generation and the core
test suite work without it; real rendering tests skip explicitly when it is
absent. Clang is needed for Phase 4 compilation/execution; frontend and
transformation inspection still work without it. Phase 5 does not require `perf`
or implement hardware counters; those metrics remain explicitly unavailable.
Graphviz 16.1.0 was installed locally via Homebrew,
including its system dependencies, to validate real rendered diagrams.

macOS tool installation, when needed:

```sh
xcode-select --install
brew install graphviz
```

On Debian/Ubuntu, when needed:

```sh
sudo apt-get update
sudo apt-get install clang graphviz
```

Linux `perf` packaging and permissions vary with the distribution and kernel.
No counter installation is needed for this benchmark pipeline. Hardware
instructions have JSON `null`/CSV blank values and an explicit unavailable
status/reason. Static TAC counts are a separate structural quantity and are
never substituted for executed hardware instructions or elapsed time.

Check tools without running a benchmark:

```sh
clang --version
dot -V
```

### Tests

```sh
python -m pytest
python -m pytest --collect-only -q
```

The suite includes all 530 Phase 1–2 tests and 281 Phase 3 tests for safe arithmetic,
constant environments, unroll proofs/limits, source emission, pass sequencing,
revalidation rollback, freshness/provenance, reports and CLI behavior. Small test-only TAC evaluators
check expected return values and branch/loop behavior; they are not a production
runtime or measurement backend. Nine rendering cases require external Graphviz
and skip explicitly without it. Missing-renderer and renderer-failure tests run
independently of the local installation. Phase 4 adds actual Clang compilation,
execution, protocol, equivalence and CLI tests; tool-dependent tests skip with an
explicit reason when Clang is absent. Phase 5 adds clock-boundary, repeated-run,
statistics, export and benchmark-CLI tests. Real Clang tests and baseline
benchmarks should run serially to avoid adding avoidable background load. Pure
statistics fixtures check mathematical results without asserting a particular
program duration or speedup. Hardware counters are not used.
Phase 6 tests reuse thirteen genuine saved Phase 5 reports for matrix/extraction,
mixed-feature comparisons, serialization and CLI checks without rerunning Clang.

```sh
python -m pytest tests/test_semantic.py tests/test_ir.py tests/test_cfg.py
python -m pytest tests/test_graph_renderer.py tests/test_phase2_cli.py
python -m pytest tests/test_constant_folding.py tests/test_loop_unrolling.py tests/test_codegen.py
python -m pytest tests/test_transformations.py tests/test_phase3_cli.py
python -m pytest tests/test_harness.py tests/test_compiler_runner.py tests/test_equivalence.py tests/test_phase4_cli.py
python -m pytest tests/test_benchmark_statistics.py tests/test_benchmark_storage.py
python -m pytest tests/test_timed_runner.py tests/test_benchmark.py tests/test_phase5_cli.py
python -m pytest tests/test_fingerprint_models.py tests/test_fingerprint_matrix.py tests/test_fingerprint_extraction.py tests/test_fingerprint_similarity.py
python -m pytest tests/test_fingerprint_storage.py tests/test_phase6_cli.py
```

## Phase 1 usage

Activate `.venv`, then run from the checkout:

```sh
python -m compiler --tokens examples/basic/arithmetic.c
python -m compiler --ast examples/basic/arithmetic.c
python -m compiler --ast examples/basic/nested_if_else.c
python -m compiler --ast examples/loops/sum.c
python -m compiler --ast examples/invalid/missing_semicolon.c
```

`--tokens` performs lexical analysis only. `--ast` parses and writes formatted
AST JSON. Exit codes are **0** for success, **1** for source errors, and **2** for
file/encoding or CLI-argument errors. Diagnostics go to stderr; no partial output
or traceback is printed for expected errors. Read UTF-8 files; original newline
spelling is preserved for source offsets. Locations use one-based character
columns (a tab counts as one character), zero-based character offsets and an
exclusive end position.

Actual token output from `python -m compiler --tokens examples/basic/minimal.c`:

```text
1:1 INT 'int'
1:5 ID 'main'
1:9 LPAREN '('
1:10 RPAREN ')'
1:12 LBRACE '{'
1:14 RETURN 'return'
1:21 INTEGER 0
1:22 SEMICOLON ';'
1:24 RBRACE '}'
```

Library APIs return real typed records and syntax nodes:

```python
from pathlib import Path
from compiler.ast_nodes import ast_to_dict, ast_to_json, walk
from compiler.lexer import tokenize
from compiler.parser import parse

source = Path("examples/basic/minimal.c").read_text(encoding="utf-8")
tokens = tokenize(source)
program = parse(source)
print(ast_to_json(program))
print([type(node).__name__ for node in walk(program)])
```

The traversal prints `['Program', 'Function', 'Block', 'Return', 'IntegerLiteral']`.
The actual return-expression subtree from that program, obtained with
`ast_to_json(program.function.body.items[0].value)`, is:

```json
{
  "kind": "IntegerLiteral",
  "node_id": "n0",
  "span": {
    "start_line": 1,
    "start_column": 21,
    "end_line": 1,
    "end_column": 22,
    "start_offset": 20,
    "end_offset": 21
  },
  "value": 0
}
```

Actual invalid-file diagnostic (exit code 1):

```text
examples/invalid/missing_semicolon.c:3:5: parser error [UNEXPECTED_TOKEN]: Unexpected RETURN token 'return'
```

Tokens have `type`, typed `value`, original `lexeme` and `span`. All AST nodes are
frozen dataclasses with spans and deterministic per-parse IDs; blocks use tuples.
Use `iter_child_nodes()` for direct children or `walk()` for preorder traversal.
`LexicalError` and `ParseError` carry a structured `.diagnostic`; callers can
catch their shared base `FrontendError` from `compiler.diagnostics`.

## Phase 2 usage

```sh
python -m compiler --check examples/basic/arithmetic.c
python -m compiler --tac examples/basic/arithmetic.c
python -m compiler --cfg examples/loops/sum.c
python -m compiler --ast-dot examples/basic/arithmetic.c
python -m compiler --cfg-dot --output results/sum_cfg.dot examples/loops/sum.c
python -m compiler --ast-dot --format svg --output results/arithmetic_ast.svg examples/basic/arithmetic.c
python -m compiler --cfg-dot --format png --output results/sum_cfg.png examples/loops/sum.c
```

`--check`, `--tac`, `--cfg` and `--cfg-dot` validate semantics first; `--tokens`,
`--ast` and `--ast-dot` preserve syntax-only inspection. `--output` saves text or
graph output, creating parent directories. `--format` is graph-only, defaults to
`dot`, and accepts `dot`, `svg`, `png` or `pdf`; rendered formats require an output
file. Output/sidecar aliases of the input file are rejected. Warnings go to stderr
without changing a successful exit code. Source errors exit 1; file/argument or
rendering errors exit 2. Failed rendering leaves a `.dot` sidecar and reports its
path, so graphs remain inspectable without the external executable.

Actual `--tac examples/basic/arithmetic.c` output:

```text
%t0 = 3 * 4
%t1 = 2 + %t0
x = %t1
%t2 = x - 2
%t3 = %t2 / 3
y = %t3
%t4 = y % 3
%t5 = x + %t4
x = %t5
return x
```

Actual edge section from `--cfg examples/loops/sum.c` (the command also prints
the instructions in each block):

```text
edges:
  entry -> B0 [entry]
  B0 -> B1 [fallthrough]
  B1 -> B2 [true]
  B1 -> B4 [false]
  B2 -> B3 [fallthrough]
  B3 -> B1 [jump]
  B4 -> exit [return]
```

The jump from B3 to B1 is the actual loop-back edge. Returns lead only to the
synthetic exit. Source variables retain their spelling; temporary names have a
`%` prefix so an input variable named `t0` cannot collide with `%t0`.

```python
from compiler.semantic import analyze
from compiler.ir import lower_ir, format_ir, validate
from compiler.cfg import build_cfg, format_cfg
from visualization.graph_renderer import ast_to_dot, cfg_to_dot, render

analysis = analyze(program)   # separate symbols/bindings/warnings; AST unchanged
ir = lower_ir(program)       # validates before lowering
cfg = build_cfg(ir)          # consumes typed TAC, never reparses its text
print(format_ir(ir))
print(format_cfg(cfg))
render(cfg_to_dot(cfg), "results/cfg.svg", "svg")
```

`SemanticError` extends the existing `FrontendError`. Example source
`int main(){int x;return x;}` produces:

```text
<input>:1:25: semantic error [UNINITIALIZED_VARIABLE]: Variable 'x' is not definitely initialized before this read
```

Semantic checks enforce block/loop scope, no duplicate names or shadowing anywhere
in `main`, declared/initialized reads, explicit return paths, and statically known
zero divisors or signed 32-bit overflow. Structural unreachable statements warn
and are omitted during lowering. Initialization joins only paths that continue;
both conditional arms are conservatively possible and loops may execute zero
times, even with literal conditions. Diagnostic constants do not rewrite/fold
the AST or TAC. Loop-written values lose known-constant facts. Passing validation
does not prove runtime arithmetic safety or termination.

Division truncates toward zero; remainder is `a - trunc(a/b) * b`. Signed overflow,
zero divisors, and `INT_MIN / -1` or `INT_MIN % -1` are undefined in the study's
32-bit signed-int model. The Phase 4 harness verifies this target and reports
runtime UBSan violations. Phase 2 itself does not execute C or measure performance.

## Phase 3 usage

```sh
python -m compiler --tac examples/transformations/constants.c
python -m compiler --transform constants --tac examples/transformations/constants.c
python -m compiler --transform constants --report examples/transformations/constants.c
python -m compiler --transform unroll --report examples/transformations/unroll_negative.c
python -m compiler --transform unroll --report examples/transformations/rejected_induction.c
python -m compiler --transform unroll --max-unroll 4 --tac examples/transformations/unroll_positive.c
python -m compiler --transform constants --transform unroll --transform constants --c examples/transformations/combined.c
python -m compiler --transform constants --transform unroll --transform constants --cfg-dot --format svg --output results/combined_cfg.svg examples/transformations/combined.c
```

Repeat `--transform constants` or `--transform unroll` to specify the exact order;
combinations are explicitly labeled sequences. With no inspection mode, a
transformation request defaults to `--report`. Existing `--ast`, `--tac`, `--cfg`,
`--check` and graph modes inspect the transformed tree when passes are requested.
`--tokens` remains original-source-only and cannot be combined with a pass.
`--c` emits validated subset C, without compiling or executing it; it also works
without passes for a canonical baseline. `--report` requires at least one pass.

Exit codes remain 0 for successful inspection (including rejected/not-applicable
passes), 1 for source errors, and 2 for argument/file/render errors. Unsafe passes
return a fresh preserved input tree and a reason; non-report modes also print
rejection reasons to stderr. `--output` saves source, TAC, JSON or graphs with the
existing input-file/sidecar overwrite protection. No performance values are
generated by any transformation command.

Actual TAC for `examples/transformations/constants.c` before the pass:

```text
%t0 = 3 * 4
%t1 = 2 + %t0
base = %t1
%t2 = base - 4
adjusted = %t2
%t3 = adjusted / 3
return %t3
```

After `--transform constants --tac`:

```text
base = 14
adjusted = 10
return 3
```

Actual report fields for the example above and the rejected induction-write
example (selected fields; full JSON also includes parameters, statistics and spans):

| Example / pass | Status | Actual report evidence |
| --- | --- | --- |
| `constants.c` / `constants` | `applied` | 4 expressions folded, 2 references propagated, 6 changed AST nodes |
| `combined.c` / `constants → unroll → constants` | all 3 `applied` | 1 loop expanded into 4 iterations; final TAC instruction `return 146` |
| `rejected_induction.c` / `unroll` | `rejected` | `INDUCTION_WRITE`: body assigns to induction variable; 0 loops unrolled |
| `rejected_declaration.c` / `unroll` | `rejected` | `DECLARATION_IN_BODY`: duplication violates the unique-name scope policy |
| `rejected_limit.c` / `unroll` | `rejected` | `ITERATION_LIMIT`: 40 trips exceeds the default 32 |
| `basic/minimal.c` / `unroll` | `not_applicable` | No eligible change; all counters remain zero |

`unroll_positive.c` and `unroll_negative.c` retain their final induction values:
their hand-derived results are 64 and 89 respectively after a final constants
pass. In `combined.c`, i=2,3,4,5 contributes 14, final i=6, and 14*10+6=146.
These are semantic expectations checked in tests, not timing or hardware results.

### Transformation safety and interfaces

The constant environment maps resolved symbol IDs to known signed 32-bit integers.
Assignments update/invalidate facts; branch joins retain only values agreeing on
all continuing paths. Loop-written entry facts are cleared before condition/body
rewrites and on exit; the zero-trip path prevents body facts from escaping.
Only fully known, defined operations fold. There is no branch pruning, expression
reassociation, or algebraic identity rewrite that could erase an unsafe operand.
Undefined raw-expression folds preserve the complete original expression.
`fold_expression()` is a standalone expression helper without whole-program
validation or a variable environment; full passes always validate their input.

Unrolling accepts constant-expression starts/bounds and `i <`, `<=`, `>`, `>=`
bound with `i = i + constant` or `i = i - constant`. Positive and negative steps
must move toward the bound. Counts are derived mathematically, not by simulating
a potentially nonterminating loop. Bodies contain only assignments, nested blocks
and empty statements: induction writes, declarations, conditionals, returns and
nested loops are rejected. All induction values, including the final executed
update, must fit signed 32-bit int. Initializer effects, iteration order, final
induction values and loop-local scope are preserved. Zero trips retain the
initializer. The default limit is 32 iterations; `--max-unroll` accepts 0..1024.
No inner loop is independently expanded inside an ineligible outer loop.

Every pass rebuilds all AST nodes. One-to-one rewrites retain source IDs/spans;
duplicated bodies/updates get unique deterministic IDs and an origin map.
Candidates undergo semantic revalidation. If that reveals a new static fault,
the whole pass rolls back to a fresh input tree and zero committed-change
statistics (`REVALIDATION_FAILED`). A report can be `applied` with decisions for
other skipped loops; when no change commits, unsafe decisions mean `rejected`,
while absence of an eligible opportunity means `not_applicable`.

```python
from compiler.ir import emit_c, lower_ir
from transformations import apply_transformations, propagate_and_fold, unroll_loops

constant_variant = propagate_and_fold(program)
unrolled_variant = unroll_loops(program, max_iterations=32)
combined = apply_transformations(program, ("constants", "unroll", "constants"))
print(combined.to_json())
print(emit_c(combined.program))
transformed_ir = lower_ir(combined.program)
```

Results contain fresh programs, serializable reports and read-only provenance.
Pipeline origins compose back to the initial source tree. Constant passes reach
a stable repeated result; repeated unrolling finds no loops in already expanded
syntax. Folded negative values are legal internal integer nodes; emitted C uses
the existing unary syntax, and spells INT_MIN as `(-2147483647 - 1)` so the lexer
need not accept a larger literal. Emitted source is parsed/validated in tests.

This is a conservative subset, not a universal equivalence or runtime safety
proof. Runtime-dependent faults, termination, arbitrary C, adaptive pass selection
and machine behavior remain outside Phase 3. Test-only arithmetic/TAC oracles
check independently expected values; no C process or runtime-equivalence pipeline
is created. Actual local reports, emitted C and a transformed CFG can be
regenerated under ignored `results/phase3/` using `--output`.

## Phase 4 usage

```sh
python -m compiler --compile examples/runtime/constants_return257.c
python -m compiler --run examples/runtime/constants_return257.c
python -m compiler --equiv --transform constants examples/runtime/constants_return257.c
python -m compiler --equiv --transform unroll examples/transformations/unroll_positive.c
python -m compiler --equiv --transform unroll --opt O2 examples/transformations/unroll_negative.c
python -m compiler --equiv --transform constants --transform unroll --transform constants --output results/phase4/combined.json examples/transformations/combined.c
python -m compiler --equiv --against examples/runtime/mismatch_257.c examples/runtime/mismatch_one.c
python -m compiler --equiv --execution-timeout 1 examples/runtime/timeout.c
python -m compiler --equiv examples/runtime/dynamic_divzero.c
```

These commands return structured JSON. `--compile` validates and compiles in a
temporary workspace; the binary is removed on completion. `--run` also executes
and records the complete signed integer separately from process status.
`--equiv` defaults to constants; repeat `--transform` for the exact pass order.
`--against` compares two validated sources and cannot accompany passes.
`--output` saves reports, including failed comparisons, and protects both inputs.

Defaults are Clang, C11, O0, UBSan, a 10-second compilation deadline and a 2-second
execution deadline. Configure with `--clang PATH`, `--opt O0|O2`,
`--compile-timeout SECONDS` and `--execution-timeout SECONDS`. Deadlines must be
finite and positive. `--no-sanitize` allows single-program observations, but
matching pairs are inconclusive. Unsupported sanitizer environments are explicit;
there is no silent fallback. Optional API extra flags may configure diagnostics
only, preserving the target/optimization/sanitizer contract.

Actual Apple Clang 21.0.0 results (O0 unless stated):

| Example | Full original / transformed return | Outcome / CLI exit |
| --- | --- | --- |
| Constants | 257 / 257 | `observed_equivalent` / 0 |
| Positive-step unrolling | 64 / 64 | `observed_equivalent` / 0 |
| Negative-step unrolling, O2 | 89 / 89 | `observed_equivalent` / 0 |
| Constants → unroll → constants | 146 / 146 | `observed_equivalent` / 0 |
| Zero-trip final induction | 12 / 12 | `observed_equivalent` / 0 |
| Negative division/remainder | -201 / -201 | `observed_equivalent` / 0 |
| Deliberate mismatch | 1 / 257 | `different_behavior` / 5 |
| Infinite loop | No completed result | `timeout` / 4 |
| Dynamic zero divisor | No accepted result | `undefined_behavior` / 4 |
| Rejected declaration-in-body unrolling | 3 / 3 | `no_transformation` / 6 |

Actual selected JSON from `--run examples/runtime/constants_return257.c`:

```json
{"status": "success", "process_returncode": 0, "return_value": 257, "stdout": "", "stderr": ""}
```

The harness wraps the validated AST's canonical C with a collision-free static
entry and a separate versioned JSON observation file. C assertions verify the
exact signed 32-bit target. Full returns are never inferred from process exit
codes. Reports separate deterministic results (input hashes, sources, reports,
origins, settings, compilation outcomes and observations) from environmental
compiler version, platform and temporary paths. No accepted change produces
`no_transformation`; matching unchanged executions do not validate a rejected pass.

Runtime exit codes: **0** compiled/executed/observed equivalent; **1** source error;
**2** argument/file error; **3** compilation failure; **4** execution failure,
compile/run timeout or detected UB; **5** mismatch; **6** unavailable/inconclusive
validation or no accepted transformation. Saving a report retains that exit code.

```python
from runtime.equivalence import check_equivalence, compare_sources
from runtime.models import CompileConfig

report = check_equivalence(source, ("constants", "unroll", "constants"),
                           config=CompileConfig(optimization="O2"))
print(report.outcome)
print(report.to_json())
control = compare_sources("int main(){return 1;}", "int main(){return 257;}")
assert control.outcome == "different_behavior"
```

Execution is for trusted local coursework fixtures. Process-group termination,
bounded output and POSIX resource limits contain accidental runaway programs;
there is no filesystem/network isolation or security sandbox. Supported programs
still have no external input/I/O. UBSan and successful matching runs establish
observed behavior under recorded conditions, not a proof of universal equivalence,
safety or termination. Local coverage is macOS arm64; Linux remains unverified.

See [the complete Phase 4 evidence, actual original/transformed C, report contract,
file inventory and limitations](docs/PHASE4_VALIDATION.md). That report records
the historical Phase 4 gate; current measurement work is described below.

## Phase 5 usage

```sh
python -m compiler --benchmark --transform constants --opt O0 --execution-timeout 10 --csv --output results/phase5/constants-O0.json examples/runtime/constants_return257.c
python -m compiler --benchmark --transform unroll --opt O2 --execution-timeout 10 --csv --output results/phase5/unroll-O2.json examples/transformations/unroll_positive.c
python -m compiler --benchmark --transform constants --transform unroll --transform constants --execution-timeout 10 --warmups 1 --repetitions 5 --csv --output results/phase5/combined.json examples/transformations/combined.c
python -m compiler --benchmark --against examples/runtime/mismatch_257.c --warmups 0 --repetitions 2 --output results/phase5/mismatch.json examples/runtime/mismatch_one.c
```

These commands reproduce the documented protocol. [The example catalog](examples/benchmarks/README.md) includes
negative returns, rejected/inapplicable passes, timeouts, UB and unavailable
validation. Actual serial O0/O2 samples and the passing complete test gate are
recorded in [the Phase 5 report](docs/PHASE5_VALIDATION.md).
Its six baseline groups used five warm-ups and thirty measurements per
variant with an explicit ten-second execution deadline; the ordinary API/CLI
default remains two seconds. Each export records its actual configuration.

Actual constants-O0 output excerpt, from a completed 257/257 comparison:

```text
original: 30/30 successful measured executions; median 10.350 ms, mean 10.348 ms.
transformed: 30/30 successful measured executions; median 10.329 ms, mean 10.768 ms.
Observed process median ratio (original/transformed): 1.0020; duration change: -0.20%.
Interpretation: unreliable; process_startup_scope, high_variability, iqr_overlap, dispersion_exceeds_difference
```

All six main conditions completed, retaining 360 measured samples and 60 untimed
warm-ups. Every comparison was `unreliable`; no algorithmic speedup or statistical
significance is established. The report includes full raw/summary exports,
compiler flags and genuine negative controls.

`--benchmark` defaults to constants, **5 untimed warm-ups and 30 measured
executions per variant**. `--warmups` accepts 0..10000 and `--repetitions` accepts
1..10000. Repeat `--transform` for an exact sequence, or use `--against` for an
independent validated source comparison without passes. C11, O0/O2, compiler
selection, sanitization and deadlines use the existing Phase 4 configuration;
baseline and variant always receive equivalent settings.

Compilation, the target/sanitizer capability check and initial full-observation
comparison happen before measurement. The exact same validated sanitized
binaries remain alive for warm-ups and repeated measurements. Each phase uses
deterministic AB/BA pairs: round 0 original/transformed, round 1
transformed/original, then repeat. Every run checks the full returned integer,
streams, signal and wrapper status against its validated observation. Failure,
divergence or interruption stops the schedule, retains attempted raw rows, and
invalidates comparative summaries. Successful prefixes are not averaged after
a failed comparison. Rejected or unchanged transformations cannot acquire a
performance result by comparing a program with itself.

The monotonic `time.perf_counter_ns()` duration is **end-to-end process execution
time**. It starts immediately before `Popen` and ends after process reaping,
process-group cleanup and bounded capture-thread completion. It includes process
creation/startup, resource setup in the child, sanitizer, computation, the C
observation-file write, capture and runner supervision. It excludes compilation,
run-directory/input preparation, Python capture decoding and observation JSON
parsing. Nanosecond units describe clock readings, not nanosecond accuracy. No
startup correction or calibration is applied; tiny fixtures can be dominated by
startup and harness overhead. At O2, Clang may already perform similar
transformations.

Complete valid groups report count, median, mean, min/max, sample standard
deviation, inclusive interpolated quartiles/IQR and coefficient of variation.
`speedup = median_original / median_transformed` is a dimensionless observed
**process median ratio**; percentage change is
`100 * (median_transformed - median_original) / median_original`.
Unavailable/zero denominators are explicit, and genuine zero durations stay zero.
Small sample counts, high variation and overlapping distributions are flagged.
The output establishes neither an algorithmic speedup nor statistical significance.

The CLI prints a concise interpretation and saved paths. JSON is always saved:
without `--output`, its path is `results/<benchmark_id>/benchmark.json`. `--csv`
adds `.samples.csv` and `.summary.csv` beside it; `--samples-csv PATH` and
`--summary-csv PATH` also work independently. All exports join on `benchmark_id`.
JSON separates the existing `analysis` result from variable measurements under
`benchmark` and compiler/platform/clock details under `environment_metadata`.
Raw rows preserve warm-ups (`duration_ns: null`), failures and actual order.
Missing CSV values are blank, booleans are `true`/`false`, and units are explicit.
Exact column order, statistical definitions and issue codes are in
[PHASE5_VALIDATION.md](docs/PHASE5_VALIDATION.md).

All output paths are checked before compilation: neither input nor an output
alias can be overwritten accidentally, including hardlinks and resolved
symlink-parent aliases. Final output symlinks, directories and special files are
rejected. Existing regular report files may be replaced. All sibling temporary
files are prepared before per-file atomic replacement; a multi-file export is
not one transaction.

Benchmark exit codes are **0** for a completed behavior-valid schedule (including
descriptive/unreliable timings), **1** source error, **2** argument/file error,
**3** compilation failure, **4** execution/measurement failure, timeout or UB,
**5** different behavior, **6** unavailable/inconclusive/no accepted transformation,
and **130** interruption. A saved failure report retains the failure exit code.
Matching unsanitized pairs are inconclusive and are not measured. Phase 6 report
commands are described below; Phase 7 remains pending.

## Phase 6 usage — accepted

These commands reuse the [thirteen genuine Phase 5 reports](examples/observations/phase5/README.md).
They do not compile C or rerun measurements. A matrix can contain several
configurations, while each extracted fingerprint contains exactly one.
The first matrix command selects three records; the full thirteen-record
demonstration command and exports are in the Phase 6 validation report.

```sh
python -m compiler --matrix --benchmark-report examples/observations/phase5/constants-O0.json --benchmark-report examples/observations/phase5/constants-O2.json --benchmark-report examples/observations/phase5/unroll-O0.json --output results/phase6/matrix.json --csv
python -m compiler --fingerprint --benchmark-report examples/observations/phase5/constants-O0.json --output results/phase6/constants-O0.json --csv
python -m compiler --fingerprint --benchmark-report examples/observations/phase5/constants-O2.json --output results/phase6/constants-O2.json --csv
python -m compiler --fingerprint --benchmark-report examples/observations/phase5/unroll-O0.json --output results/phase6/unroll-O0.json --csv
python -m compiler --compare-fingerprints results/phase6/constants-O0.json --against results/phase6/constants-O2.json --alignment configuration --output results/phase6/configuration-comparison.json --csv
python -m compiler --compare-fingerprints results/phase6/constants-O0.json --against results/phase6/constants-O0.json --feature-group performance --inspect-features
```

Without `--output`, stdout is structured JSON; `--inspect-features` also writes
readable values, units, validity, reliability and exclusion reasons to stderr.
With `--output`, the CLI prints a summary and saved paths; `--csv` writes one
long-form `<stem>.csv` beside JSON. Summaries list configuration identifiers with
optimization/compiler labels. For a saved multi-configuration matrix, use
`--fingerprint MATRIX.json --configuration ID`, copying the desired ID from the
matrix summary. Optional repeated `--source-id`, `--pipeline-id` and
`--observation-id` filters select observations explicitly.

Actual derived values from the genuine reports:

| Feature | Constants O0 | Unroll O0 |
| --- | ---: | ---: |
| `pipeline.expressions_folded` | 2 | 0 |
| `pipeline.references_propagated` | 1 | 0 |
| `pipeline.loops_unrolled` | 0 | 1 |
| `pipeline.iterations_expanded` | 0 | 4 |
| `tac.original.operations` → `tac.transformed.operations` | 4 → 2 | 12 → 21 |
| `tac.response.operations` | -0.5 | 0.75 |
| Recorded `performance.median_ratio` | 1.002010891400634 | 0.9995925965869535 |
| Timing reliability | `unreliable`, excluded from scores | `unreliable`, excluded from scores |

TAC counts are structural properties. Unrolling increases this fixture's static
TAC count; neither that change nor a near-one process ratio proves a runtime
improvement. All six original O0/O2 ratios remain recorded with their reliability
reasons. Hardware instructions remain missing, and none of those timings is
scored by default.

The all-report demonstration contains 13 observations, 9 source identities,
4 ordered pipeline identities, 5 complete configurations and 25 feature
definitions. Missing combinations have no invented row. Actual comparison output:

```text
Fingerprint comparison: comparable; 20/25 usable dimensions; similarity 1.0.
Similarity is descriptive evidence, not semantic equivalence or compiler identification.
```

That output applies both to constants-O0 self-comparison and to its explicit
O0/O2 configuration comparison over valid structural and categorical features.
The performance-only self-comparison instead reports
`insufficient_evidence; 0/5 usable dimensions; similarity unavailable` and exits
6. Strict O0/O2 comparison is `incompatible`, also exit 6. These are honest
missing-evidence outcomes; a structural similarity of 1 does not identify a
compiler or prove semantics.

Comparison modes make the intended alignment explicit:

| `--alignment` | Required agreement |
| --- | --- |
| `strict` (default) | Source SHA-256, complete ordered pass/version/parameter identity and complete compiler/environment/measurement configuration |
| `configuration` | Same source/pipeline; compiler path/version and selected optimization/flags may differ while target, environment, cases and remaining settings match |
| `program` | One observation on each side, same configuration and pipeline; source may differ |
| `pipeline` | One observation on each side, same source/configuration; shared pass versions/parameters and comparison context must agree |

Numeric dimensions use bounded symmetric relative difference
`abs(a-b)/(abs(a)+abs(b))`, defined as zero for two zeros. Categorical dimensions
use 0 for equality and 1 for difference. The distance is their positive-weighted
mean; similarity is `1-distance`. The default minimum is two usable dimensions;
`--feature-group`, `--weight FEATURE=NUMBER` and `--min-dimensions` make selection
and weighting explicit. Reports retain per-feature contributions, coverage,
unmatched/ambiguous observations and every exclusion. No score is produced for
insufficient or incompatible evidence. Mixed units are never placed blindly into
raw Euclidean distance or cosine similarity.

Schema-1 `codedna.response_matrix`, `codedna.fingerprint` and
`codedna.comparison` JSON retain versioned definitions, stable identifiers and
complete input provenance. CSV has separate feature-row and comparison-row
schemas with units, validity, reliability, reasons and missing cells; real zeros
remain zero. Input/output alias protections and per-file atomic exports reuse the
Phase 5 path policy. Phase 6 exits **0** for successful construction/comparable
evidence, **2** for argument/file/schema errors, **6** for incompatible/insufficient
comparison, and **130** for interruption. Saved exclusion reports retain exit 6.
Full schemas and methodology are in [PHASE6_VALIDATION.md](docs/PHASE6_VALIDATION.md).
Evidence covers Apple Clang on macOS arm64; O0/O2 are optimization settings of
that toolchain. No GCC, cross-vendor identification or Linux validation is claimed.

## Current directory structure

```text
CodeDNA/
├── compiler/
│   ├── __init__.py
│   ├── __main__.py
│   ├── ast_nodes.py
│   ├── diagnostics.py
│   ├── lexer.py
│   ├── parser.py
│   ├── semantic.py
│   ├── ir.py
│   ├── codegen.py
│   └── cfg.py
├── transformations/
│   ├── __init__.py
│   ├── common.py
│   ├── constant_folding.py
│   ├── loop_unrolling.py
│   └── pipeline.py
├── runtime/
│   ├── __init__.py
│   ├── models.py
│   ├── compiler_runner.py
│   ├── harness.py
│   ├── equivalence.py
│   ├── benchmark_models.py
│   ├── benchmark.py
│   ├── benchmark_statistics.py
│   └── benchmark_storage.py
├── fingerprint/
│   ├── __init__.py
│   ├── models.py
│   ├── matrix.py
│   ├── extraction.py
│   ├── similarity.py
│   ├── storage.py
│   └── cli.py
├── visualization/
│   ├── __init__.py
│   └── graph_renderer.py
├── examples/
│   ├── basic/       # 6 valid C examples and .gitkeep
│   ├── loops/       # 3 valid C examples and .gitkeep
│   ├── invalid/     # 6 intentionally invalid C examples
│   ├── transformations/  # 7 Phase 3 success/rejection examples
│   ├── runtime/     # 7 full-return/equivalence/failure examples
│   ├── benchmarks/README.md  # repeatable commands over existing C fixtures
│   ├── observations/phase5/  # 13 authentic benchmark JSON files and provenance README
│   └── comparison/     # documented program relationships for structural examples
├── tests/
│   ├── test_setup.py
│   ├── test_lexer.py
│   ├── test_parser.py
│   ├── test_ast.py
│   ├── test_frontend_integration.py
│   ├── test_semantic.py
│   ├── test_ir.py
│   ├── test_cfg.py
│   ├── test_graph_renderer.py
│   ├── test_phase2_cli.py
│   ├── test_codegen.py
│   ├── test_constant_folding.py
│   ├── test_loop_unrolling.py
│   ├── test_transformations.py
│   ├── test_phase3_cli.py
│   ├── test_compiler_runner.py
│   ├── test_harness.py
│   ├── test_equivalence.py
│   ├── test_phase4_cli.py
│   ├── test_timed_runner.py
│   ├── test_benchmark.py
│   ├── test_benchmark_statistics.py
│   ├── test_benchmark_storage.py
│   ├── test_phase5_cli.py
│   ├── test_fingerprint_models.py
│   ├── test_fingerprint_matrix.py
│   ├── test_fingerprint_extraction.py
│   ├── test_fingerprint_similarity.py
│   ├── test_fingerprint_storage.py
│   └── test_phase6_cli.py
├── docs/
│   ├── ARCHITECTURE.md
│   ├── IMPLEMENTATION_PLAN.md
│   ├── PHASE4_VALIDATION.md
│   ├── PHASE5_VALIDATION.md
│   ├── PHASE6_VALIDATION.md
│   ├── COMPILER_DESIGN.md
│   └── PROGRESS.md
├── results/.gitkeep
├── pyproject.toml
├── requirements.txt
├── .gitignore
└── README.md
```

Phase 6 matrix/extraction/comparison/storage/CLI code passed acceptance with all
1709 tests. `app.py` remains absent; Phase 7 has not begun.
`compiler/codegen.py` keeps pure source
emission separate from IR records, and `compiler.ir.emit_c` retains the planned
public interface. Shared transformation helpers/reports and explicit sequencing
live under `transformations/`.
`compiler/semantic.py` separates binding/dataflow from representation/lowering;
the planned `validate()` remains available through `compiler.ir`.
`compiler/diagnostics.py` shares frontend
errors/source mapping without coupling AST definitions to PLY; `__main__.py`
provides the requested CLI. `visualization/__init__.py` makes
visualization an explicit importable package. `.gitkeep` files retain empty
directories in Git; generated results are ignored.

## Supported C syntax (implemented)

One `int main()` or `int main(void)` function, integer literals and variables,
local declarations, assignments, unary `+`/`-`, arithmetic `+ - * / %`, relational
and equality expressions, blocks and empty statements, `if`/`else`, basic `for`
loops, and `return`. Comments and LF/CRLF/CR line endings are supported. Literals
must be decimal `0..2147483647` without leading zeros or suffixes. Initial
programs have no external input or I/O; cases use controlled source fixtures.

Pointers, arrays, function calls, additional functions, preprocessing directives,
strings, floating point, structs, `while`/`do`, `break`/`continue`, increment and
compound-assignment operators are unsupported. Use `i = i + 1` in a `for` update.
See [the precise grammar, semantic restrictions, and AST/IR contract](docs/COMPILER_DESIGN.md).

Phase 1 APIs continue to check **syntax** only; Phase 2 APIs apply the semantic
checks above. Deeply nested frontend processing and AST
JSON serialization is limited by Python recursion; the CLI reports that limit
without a traceback. There is no C preprocessing or line-splicing implementation.

## Roadmap

| Phase | Deliverable | Primary owner |
| --- | --- | --- |
| 1. Lexical and syntax analysis | PLY tokens, AST, source diagnostics | Ishaan |
| 2. CFG and IR | Basic blocks, edges, three-address code, diagrams | Ishaan / Zayn |
| 3. Transformations | Constant propagation/folding and safe loop unrolling | Zayn |
| 4. Compilation and execution | Clang runner, identical runs, errors/timeouts, equivalence gate | Pranav |
| 5. Runtime measurement | Complete: repeated process times, honest missing hardware counts, JSON/CSV; 1384 passing tests | Pranav |
| 6. Fingerprinting | Complete: sparse matrices, explicit fingerprints, interpretable comparisons; 1709 passing tests | Pranav |
| 7. Dashboard and evaluation | Streamlit demo and AST/CFG/IR/single-run baselines | All |

Complete and validate one phase before starting the next. Acceptance criteria
and dependencies are in [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## Team and interfaces

- **Ishaan:** lexer, parser, shared AST, CFG.
- **Zayn:** three-address IR, constant propagation/folding, loop unrolling,
  transformation correctness.
- **Pranav:** compilation, execution, measurements, test automation, fingerprint
  evaluation, and integration.

The frontend returns shared AST nodes; semantic analysis and TAC lowering consume
the AST, and CFG construction consumes TAC. Implemented transformations
return fresh ASTs and reports. Runtime consumes emitted C and returns structured
execution/measurement records. Fingerprinting consumes measurements with explicit
units, provenance, and missing values. Phase 1–6 APIs are implemented and accepted.
Dashboard APIs remain planned.
Details: [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Development rules

Work in this existing repository on `main`. Do not initialize another repository,
create branches, change the remote, or automatically push changes. Preserve
working functionality and document interface changes before integration.
Implement actual compiler algorithms; keep unavailable stages clearly marked.
Test each completed module and record progress in [PROGRESS.md](docs/PROGRESS.md).
Use only trusted local C fixtures until an isolated execution environment exists;
subprocess timeouts alone do not sandbox uploaded code.

Benchmark variants with the same compiler flags, inputs, and environment. Verify
observable results before accepting measurements. Keep raw data and metadata;
never invent timing values, instruction counts, or similarity scores.

## Current gate: Phase 6 accepted — stop

The complete suite passed 1709 tests, including all 1384 prior cases. Genuine
report-derived matrices/fingerprints/comparisons and fourteen JSON/CSV pairs were
inspected. This task stops here. The dashboard, machine-learning classifiers, extra compiler
vendors and hardware-counter backends have not been implemented.

## References

- [PLY project and documentation](https://github.com/dabeaz/ply)
- [Python packaging configuration](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [pytest configuration](https://docs.pytest.org/en/stable/reference/customize.html)
- [Graphviz Python documentation](https://graphviz.readthedocs.io/)
- [Clang documentation](https://clang.llvm.org/docs/)
- [Streamlit documentation](https://docs.streamlit.io/)

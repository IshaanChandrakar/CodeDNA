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

**Phases 1–3 are complete:** the PLY frontend, typed AST, semantic analysis, TAC,
CFGs/diagrams, constant propagation/folding, conservative full loop unrolling,
ordered pass reports and pure C source emission. The full suite passes **811
tests** on macOS with Python 3.14.5 and PLY 3.11, including all **530 Phase 1–2
tests**. **Phases 4–7 are pending.** There is no machine compilation/execution,
runtime-equivalence service, benchmark, fingerprint or dashboard implementation.

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
| Clang/LLVM | Compile C and inspect LLVM IR | Phases 4–5 |
| pytest | Setup and module tests | Now and every phase |
| Streamlit | Demonstration dashboard | Phase 7 |
| Linux `perf` | Executed hardware instruction counts | Phase 5, if permitted |

The Python Graphviz package does not install `dot`. DOT generation and the core
test suite work without it; real rendering tests skip explicitly when it is
absent. Clang and `perf` are external tools for later phases, not required by the
current compiler pipeline. Graphviz 16.1.0 was installed locally via Homebrew,
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

Linux `perf` packaging varies with distribution and kernel. Install the matching
distribution package and check hardware counter access during Phase 5. macOS
has no Linux `perf`; its hardware-instruction field will be missing unless a
separately validated backend is added. Static IR instruction counts are a
separate metric and must never be labeled executed hardware instructions.

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
checks expected return values and branch/loop behavior; it is not a production
runtime or measurement backend. Nine rendering cases require external Graphviz
and skip explicitly without it. Missing-renderer and renderer-failure tests run
independently of the local installation. No hardware counters or benchmarks run.

```sh
python -m pytest tests/test_semantic.py tests/test_ir.py tests/test_cfg.py
python -m pytest tests/test_graph_renderer.py tests/test_phase2_cli.py
python -m pytest tests/test_constant_folding.py tests/test_loop_unrolling.py tests/test_codegen.py
python -m pytest tests/test_transformations.py tests/test_phase3_cli.py
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
32-bit signed-int model. The future execution backend must verify the target and
use defined inputs. Phase 2 does not execute user C or measure performance.

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
├── runtime/__init__.py
├── fingerprint/__init__.py
├── visualization/
│   ├── __init__.py
│   └── graph_renderer.py
├── examples/
│   ├── basic/       # 6 valid C examples and .gitkeep
│   ├── loops/       # 3 valid C examples and .gitkeep
│   ├── invalid/     # 6 intentionally invalid C examples
│   ├── transformations/  # 7 Phase 3 success/rejection examples
│   └── comparison/.gitkeep
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
│   └── test_phase3_cli.py
├── docs/
│   ├── ARCHITECTURE.md
│   ├── IMPLEMENTATION_PLAN.md
│   ├── COMPILER_DESIGN.md
│   └── PROGRESS.md
├── results/.gitkeep
├── pyproject.toml
├── requirements.txt
├── .gitignore
└── README.md
```

Later runtime modules, `fingerprint/matrix.py`, `fingerprint/similarity.py`, and
`app.py` remain absent after Phase 3. `compiler/codegen.py` keeps pure source
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
| 5. Runtime measurement | Repeated times and available hardware counts, JSON/CSV | Pranav |
| 6. Fingerprinting | Normalized response matrix and missing-aware comparisons | Pranav |
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
units, provenance, and missing values. These are design contracts, not existing
APIs except for the completed Phase 1–3 pipeline. Details: [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Development rules

Work in this existing repository on `main`. Do not initialize another repository,
create branches, change the remote, or automatically push changes. Preserve
working functionality and document interface changes before integration.
Implement actual compiler algorithms; keep unavailable stages clearly marked.
Test each completed module and record progress in [PROGRESS.md](docs/PROGRESS.md).
Use only trusted local C fixtures until an isolated execution environment exists;
future subprocess timeouts alone will not sandbox uploaded code.

Benchmark variants with the same compiler flags, inputs, and environment. Verify
observable results before accepting measurements. Keep raw data and metadata;
never invent timing values, instruction counts, or similarity scores.

## Next work: Phase 4 (not started)

After a separate Phase 4 request, implement Clang compilation and controlled
execution of baseline/transformed sources, identical cases/environment, full
return/output equivalence, failure diagnostics and timeouts. The current task
stops at Phase 3. No compiler runner, C execution, runtime-equivalence checks,
benchmark, repeated measurements, fingerprint or dashboard has begun.

## References

- [PLY project and documentation](https://github.com/dabeaz/ply)
- [Python packaging configuration](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [pytest configuration](https://docs.pytest.org/en/stable/reference/customize.html)
- [Graphviz Python documentation](https://graphviz.readthedocs.io/)
- [Clang documentation](https://clang.llvm.org/docs/)
- [Streamlit documentation](https://docs.streamlit.io/)

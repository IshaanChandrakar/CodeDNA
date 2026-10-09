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

**Repository setup only. None of the seven compiler/application phases is
implemented.** The packages contain descriptive docstrings, and the tests check
installation and imports. No tokenizer, parser, transformation, benchmarking,
fingerprint score, or dashboard is available yet. Dependencies for future work
are declared without implementing that work.

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
| Python `graphviz` | Build DOT graphs | Phase 2 |
| Graphviz `dot` executable | Render DOT to SVG/PNG | Phase 2 |
| Clang/LLVM | Compile C and inspect LLVM IR | Phases 3–5 |
| pytest | Setup and module tests | Now and every phase |
| Streamlit | Demonstration dashboard | Phase 7 |
| Linux `perf` | Executed hardware instruction counts | Phase 5, if permitted |

The Python Graphviz package does not install `dot`. Clang and `perf` are also
external tools. They are not required for the current smoke tests.

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

The initial suite has eight import smoke tests. Future tests marked `integration`
require external tools; tests marked `perf` require Linux counter access. Missing
optional tools must yield explicit skips or unavailable measurements, never
fabricated data. There are no such tests yet.

## Current directory structure

```text
CodeDNA/
├── compiler/__init__.py
├── transformations/__init__.py
├── runtime/__init__.py
├── fingerprint/__init__.py
├── visualization/__init__.py
├── examples/
│   ├── basic/.gitkeep
│   ├── loops/.gitkeep
│   └── comparison/.gitkeep
├── tests/test_setup.py
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

Stage-specific files such as `compiler/lexer.py`, `compiler/parser.py`,
`compiler/ast_nodes.py`, `compiler/cfg.py`, `compiler/ir.py`, the transformation
and runtime modules, `fingerprint/matrix.py`, `fingerprint/similarity.py`,
`visualization/graph_renderer.py`, and `app.py` will be created in their phases.
They are intentionally absent during setup. `visualization/__init__.py` makes
visualization an explicit importable package. `.gitkeep` files retain empty
directories in Git; generated results are ignored.

## Supported C subset (planned)

One `int main()` or `int main(void)` function, integer literals and variables,
local declarations, assignments, arithmetic and relational expressions,
`if`/`else`, counted `for` loops, and `return`. Initial programs have no external
input or I/O; input cases will initially be controlled source fixtures.

Pointers, arrays, function calls, additional functions, preprocessing directives,
strings, floating point, structs, `while`/`do`, `break`/`continue`, increment and
compound-assignment operators are unsupported. Use `i = i + 1` in a `for` update.
See [the precise grammar, semantic restrictions, and AST/IR contract](docs/COMPILER_DESIGN.md).

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

The frontend returns shared AST nodes; CFG and IR consume that AST. Transformations
return fresh ASTs and reports. Runtime consumes emitted C and returns structured
execution/measurement records. Fingerprinting consumes measurements with explicit
units, provenance, and missing values. These are design contracts, not existing
APIs. Details: [ARCHITECTURE.md](docs/ARCHITECTURE.md).

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

## Next work: Phase 1 only

Define `SourceSpan` and AST dataclasses in `compiler/ast_nodes.py`, implement PLY
tokens in `compiler/lexer.py`, and implement the documented grammar and precedence
in `compiler/parser.py`. Add real basic/conditional/loop fixtures and unit tests
for tokens, AST structure, and source-located errors. Do not start CFG, IR,
transformations, runtime, fingerprints, or the dashboard until Phase 1 is accepted.

## References

- [PLY project and documentation](https://github.com/dabeaz/ply)
- [Python packaging configuration](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [pytest configuration](https://docs.pytest.org/en/stable/reference/customize.html)
- [Graphviz Python documentation](https://graphviz.readthedocs.io/)
- [Clang documentation](https://clang.llvm.org/docs/)
- [Streamlit documentation](https://docs.streamlit.io/)

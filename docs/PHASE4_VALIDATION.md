# Phase 4 — compilation, execution and observed equivalence

Accepted 2026-10-16: `.venv/bin/python -m pytest -q` completed with **1111 passed,
0 failed, 0 skipped**, retaining all **811** prior tests. The **300** new cases
comprise 63 runner, 89 harness, 92 equivalence and 56 CLI tests. Actual Clang
integration ran. `pip check`, whitespace checks and local documentation links
passed. This document records actual local evidence; Phase 5 has not begun.
The validation history is in [PROGRESS.md](PROGRESS.md).

## Files and architecture

New implementation files: `runtime/models.py` (immutable configuration/results),
`runtime/compiler_runner.py` (Clang discovery, bounded subprocesses, context-owned
builds/runs), `runtime/harness.py` (validated AST wrapper and strict observation
protocol), and `runtime/equivalence.py` (single-source operations, independent
source comparisons, pipeline/provenance integration and JSON reports).
`runtime/__init__.py` describes the implemented package; `compiler/__main__.py`
adds runtime commands. No lexer, parser, AST, semantic, TAC/CFG, code emitter or
transformation implementation changed.

New tests: `tests/test_compiler_runner.py`, `tests/test_harness.py`,
`tests/test_equivalence.py`, and `tests/test_phase4_cli.py`. Seven new fixtures in
`examples/runtime/` cover full results, constants, negative arithmetic, zero-trip
loops, deliberate differences, timeout and dynamic division by zero. README,
architecture, compiler design, implementation plan and progress are updated.
No Python dependencies were added.

`CompilerRunner(CompileConfig(...))` must be used as a context manager. Its
`compile_source(source, label=..., observation_file=...)` creates an independent
build. `execute(artifact, case=None)` runs in a fresh private directory. Thin
module-level delegates require `workspace=runner` so the lifetime of a binary is
never hidden. Raw C compilation is a trusted low-level testing interface; the
high-level service and CLI always parse/analyze the existing C subset first.

`check_equivalence(source, sequence, config=..., max_iterations=32)` validates,
applies the existing ordered pipeline, revalidates, emits both ASTs, compiles them
independently and compares real observations. `compare_sources(left, right)` is
the negative-control interface; it validates both sources without inventing a
transformation. `evaluate_source(..., execute=False|True)` powers compile/run.
All preserve the original AST/source. Reports retain applicability and composed
AST origins. An unchanged/rejected pipeline produces `no_transformation`, never
evidence of a successfully validated optimization. Failures take precedence.

## Harness and execution contract

The harness accepts a typed validated `Program`, emits canonical C, verifies the
emitter's known opening header, and substitutes that header with a collision-free
static computation entry. It never regex-rewrites arbitrary C. The generated
wrapper calls the computation exactly once and writes
`{"protocol_version":1,"return_value":257}` to a fixed, exclusively created file
in the private run directory. It exits 0 independently of the computation's
return. Observation failures have infrastructure statuses 120–122. The strict
JSON reader rejects missing/extra/duplicate fields, boolean/noninteger numbers,
unsupported versions and out-of-range integers. A failed observation is never
replaced by the OS exit code. Stdout/stderr remain separate observations.

Standard headers follow the computation, so header macros such as `EOF` and
`INT_MIN` cannot rewrite supported user identifiers. Static C assertions check
`CHAR_BIT == 8`, `sizeof(int) == 4`, and exact signed 32-bit minimum/maximum. Full
returns 0, 257, -257, -2147483648 and 2147483647 were genuinely compiled/observed
at O0/O2. Entry-name and standard-library-name collision fixtures also ran.

Clang is located and its successful `--version` recorded once per runner. Tested:

```text
Apple clang version 21.0.0 (clang-2100.3.34.2)
Target: arm64-apple-darwin25.6.0
Thread model: posix
InstalledDir: /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin
```

Flags: `-std=c11 -O0 -fsanitize=undefined -fno-sanitize-recover=all`, with separately
tested `-O2`. Default compile/run deadlines are 10/2 seconds. Commands are argument
lists and never use a shell. Baseline/variant share one environment snapshot;
`LC_ALL=C`, `LANG=C`, `TZ=UTC` and
`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=0:exitcode=86` are enforced. Extra
API flags are diagnostic options only: sanitizer/target/optimization/macro/output
overrides and preprocessor/assembler/linker forwarding cannot bypass this contract.

A known-valid capability program checks configured target/sanitizer compilation
and startup before pair execution. Missing tools, unsupported sanitizer/target,
bad options, compiler diagnostics and timeouts remain explicit. There is no
silent unsanitized fallback. With sanitization disabled, matching executions are
`inconclusive`; their observations remain available. Different observations
still produce `different_behavior`. Default UBSan tests detect dynamic addition,
subtraction/multiplication overflow, zero division/remainder and `INT_MIN / -1`.
Known static faults continue to use source-located frontend diagnostics.

Stdout/stderr stream into bounded private captures (default 65536 bytes each).
Timeout or excess output kills the process group, including descendants. Available
POSIX limits cover CPU, core files and file size; an optional API address-space
limit is available. Temporary sources, binaries, inputs, captures and observations
are removed on normal/failing context exit. Tests exercise cleanup, process trees,
crashes, missing/nonexecutable artifacts, output overflow and malformed protocols.

## Reproduction and real results

From the checkout with `.venv` activated:

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
python -m compiler --equiv --transform unroll examples/transformations/rejected_declaration.c
```

Actual selected report results:

| Case | Original / transformed full return | Outcome / CLI exit |
| --- | --- | --- |
| Compile constants fixture | Not executed | `compiled` / 0 |
| Run constants fixture | 257 | `executed` / 0 |
| Constant optimization | 257 / 257 | `observed_equivalent` / 0 |
| Positive-step unrolling | 64 / 64 | `observed_equivalent` / 0 |
| Negative-step unrolling at O2 | 89 / 89 | `observed_equivalent` / 0 |
| Constants → unroll → constants | 146 / 146 | `observed_equivalent` / 0 |
| Zero-trip initializer/final induction value | 12 / 12 | `observed_equivalent` / 0 |
| Negative division/remainder | -201 / -201 | `observed_equivalent` / 0 |
| Deliberate negative control | 1 / 257 | `different_behavior` / 5 |
| Infinite-loop fixture | No completed result | `timeout` / 4 |
| Loop-carried zero divisor | No accepted result | `undefined_behavior` / 4 |
| Declaration-in-body unrolling rejection | 3 / 3 | `no_transformation` / 6 |
| Explicit missing compiler | No execution | `unavailable` / 6 |

Original canonical C in the real constants report:

```c
int main(void) {
    int base = ((16) * (16));
    return ((base) + (1));
}
```

Actual transformed C:

```c
int main(void) {
    int base = (256);
    return (257);
}
```

Both execution records contain (selected JSON fields):

```json
{"status": "success", "process_returncode": 0, "return_value": 257, "stdout": "", "stderr": ""}
```

The 1-versus-257 control has two normal process statuses of 0 and distinct full
return observations. It confirms that the checker detects actual differences
that raw Unix exit-code comparison can hide. Additional real controls compare
0/256, -1/255, large positive/negative and boundary results.

Invalid raw generated C was tested through the runner, separately from subset
source validation. Clang returned 1 and compilation status `failure`, retaining:

```text
<workspace>/build-0001/program.c:1:18: error: non-void function 'main' should return a value [-Wreturn-mismatch]
    1 | int main(void) { return ; @ }
      |                  ^
<workspace>/build-0001/program.c:1:27: error: expected expression
    1 | int main(void) { return ; @ }
      |                           ^
2 errors generated.
```

Full inspected reports were regenerated in ignored `results/phase4/`; paths in
their environmental section describe now-cleaned temporary artifacts.

## Report and CLI contracts

Reports have `schema_version=1`, deterministic `result`, and separate
`environment_metadata`. Result includes input names/exact SHA-256 hashes,
canonical sources, harness hashes, ordered applicability reports/origins,
configuration, capability diagnostics, independent compilation outcomes and
execution observations. Temporary paths in diagnostics normalize to
`<workspace>`. Environmental metadata holds raw commands/artifact paths, compiler
version and platform/Python details. It contains no timing samples or metrics.
Deterministic sections compare equal across repeated successful real checks.

`--compile` reports compilation and removes its temporary binary; it does not
export a persistent executable. `--run` returns JSON with the full integer.
`--equiv` defaults to constants; explicit passes retain exact order. `--against`
compares two validated inputs and cannot be combined with passes. `--output`
saves JSON, including failure/mismatch reports, with the same nonzero exit code.
Both input files are protected against direct, hardlink and symlink overwrite.

Options: `--clang PATH`, `--opt O0|O2`, `--compile-timeout SECONDS`,
`--execution-timeout SECONDS`, `--sanitize` (default), `--no-sanitize`. Deadlines
must be finite/positive; runtime options cannot accompany unrelated modes.

| CLI exit | Meaning |
| --- | --- |
| 0 | Compiled, executed, or observed equivalent |
| 1 | Lexer/parser/semantic source error |
| 2 | Argument, file/encoding or graph error |
| 3 | Compilation failure |
| 4 | Execution failure, compile/run timeout or detected undefined behavior |
| 5 | Different observed behavior |
| 6 | Validation unavailable/inconclusive, or no accepted transformation |

## Limits and phase boundary

Only macOS arm64 with Python 3.14.5 and Apple Clang 21.0.0 was executed locally.
The runner uses POSIX mechanisms intended for macOS/Linux; Linux remains
unverified. Missing tools skip relevant integration tests explicitly, but passing
without real compilation cannot satisfy this phase's acceptance gate.

Execution is for trusted local coursework fixtures. There is no filesystem or
network isolation, complete memory cap by default, or security sandbox. The
inherited host environment is consistent within a comparison but not fully
serialized. Resource/timeout controls contain accidental runaway work. UBSan
does not prove arbitrary safety; frontend validation does not prove termination.
At O2, C's optimizer assumptions still apply. Stdout/stderr capture is tested at
the runner layer, and the checker compares both streams; accepted user sources retain the
documented closed, side-effect-free subset without external input/I/O.

Successful comparison means observed equivalence for the recorded programs and
execution conditions, never universal mathematical equivalence. No program
runtime metrics, repeated benchmarking, instruction counts, CSV performance
datasets, response matrices, fingerprints or dashboard work has begun. No Git
commit, push, branch or configuration change was made.

# Compiler design

Status: Phases 1–4 grammar, AST, analysis, TAC/CFG, diagrams, transformations,
C emission, Clang execution and observed equivalence implemented. Phase 5 remains
pending. Updated 2026-10-16.
This document is the shared frontend/representation contract.

## Language boundary

The input is one translation unit containing exactly one integer-returning
`main` function with no parameters. Accept `int main()` and `int main(void)`.
Support decimal integer literals, integer local variables, declarations with
optional initializers, assignments, unary `+`/`-`, binary `+ - * / %`, relational
`< <= > >=`, equality `== !=`, blocks, `if` with optional `else`, basic `for`,
empty statements, and `return expression;`. Whitespace and C line/block comments
are ignored while retaining source locations. No implicit preprocessing occurs.

Unsupported: globals, additional/user functions, calls (`printf`, `scanf`, etc.),
arguments to `main`, pointers, references, arrays, strings/characters, floats,
hex/octal literals, unsigned/long types, casts, structs/unions/enums, macros and
includes, logical/bitwise operators, ternary expressions, comma expressions,
assignment expressions, compound assignment, `++`/`--`, `while`/`do`,
`switch`, `break`, `continue`, `goto`, and storage/type qualifiers.

Reject unsupported syntax with a diagnostic; do not route it directly to Clang
and describe it as frontend support. Lexer/parser construction uses genuine
PLY rules; neither regex extraction of statements nor a Clang-produced AST
replaces the lab implementation.

## Implemented grammar

This EBNF describes the actual PLY grammar in `compiler/parser.py`.
`identifier` and `integer` are lexical token classes; `main` is an identifier
whose spelling is checked in the function production. Keywords have reserved
token types. Integer literals use `0` or a nonzero digit followed by decimal
digits; reject leading-zero multi-digit literals so C octal semantics cannot
diverge from the frontend.

```text
program      := "int" "main" "(" ["void"] ")" block EOF
block        := "{" { declaration | statement } "}"
declaration  := "int" identifier ["=" expression] ";"
statement    := block | assignment ";" | if_stmt | for_stmt
              | "return" expression ";" | ";"
assignment   := identifier "=" expression
if_stmt      := "if" "(" expression ")" statement ["else" statement]
for_stmt     := "for" "(" for_init ";" expression ";" assignment ")" statement
for_init     := assignment | "int" identifier "=" expression
expression   := equality
equality     := relation { ("==" | "!=") relation }
relation     := sum { ("<" | "<=" | ">" | ">=") sum }
sum          := product { ("+" | "-") product }
product      := unary { ("*" | "/" | "%") unary }
unary        := ("+" | "-") unary | primary
primary      := integer | identifier | "(" expression ")"
```

There is one variable per declaration, and every `for` header has a nonempty
initializer, condition and assignment update. Basic loops such as
`for (int i = 0; i < 4; i = i + 1)` are supported. The parser accepts this general
header shape; the unroller later handles only its proven-safe subset.

Multiplication/division/remainder bind tighter than addition/subtraction, which
bind tighter than relational operators, then equality. Unary operators bind
most tightly. Binary operators associate left. Assignment is only a statement,
so it has no expression precedence. Layered, left-recursive expression productions
implement these rules. The no-else `if` production uses `%prec IF_WITHOUT_ELSE`,
whose precedence is lower than `ELSE`; an `else` shifts onto the nearest unmatched
`if`. A debug LALR build on PLY 3.11 reports **zero unresolved shift/reduce or
reduce/reduce conflicts**. The test suite checks both dangling-else behavior and
the build log. Parser tables and `parser.out` are never written.

### Lexical contract and diagnostics

`compiler.lexer.tokenize(source)` returns `TokenRecord(type, value, lexeme, span)`.
Token names are `INT`, `VOID`, `RETURN`, `IF`, `ELSE`, `FOR`, `ID`, `INTEGER`,
`PLUS`, `MINUS`, `STAR`, `SLASH`, `PERCENT`, `ASSIGN`, `EQ`, `NE`, `LT`, `LE`,
`GT`, `GE`, `LPAREN`, `RPAREN`, `LBRACE`, `RBRACE`, and `SEMICOLON`.
Keyword matching is case-sensitive; `main` remains an `ID` checked by the program
production. Identifiers use ASCII `[A-Za-z_][A-Za-z0-9_]*`. Other C11 reserved
words are rejected, including when spelled in an identifier position.

PLY operator rules use longest matches and explicitly reject `++`, `--`, compound
assignment and other unsupported multi-character operators before they can be
split into supported tokens. Numeric-like text with leading zeros, a suffix,
hex/octal syntax or a decimal point is rejected. Magnitudes above 2147483647 are
rejected before Python `int()` conversion, including inputs beyond Python's digit
limit. Unary signs are separate tokens.

Ignore space, tab, form feed, vertical tab, `//` comments and nonnested `/* */`
comments. Source positions retain LF, CRLF or lone CR without normalization;
columns count characters, not display widths. No preprocessor directives or
backslash line-splicing are implemented. Each `build_lexer()` is fresh, and its
`input(source)` resets state. Every `parse(source)` builds fresh grammar/parser
state and produces no partial AST on failure.

Shared diagnostics live in `compiler/diagnostics.py` to avoid duplicating source
position logic or importing PLY into AST definitions. `SourceMap` maps character
offsets to spans. `Diagnostic` has `stage`, stable `code`, `message`, and `span`.
`LexicalError`, `ParseError`, and Phase 2 `SemanticError` derive from `FrontendError` and expose
`.diagnostic`. The frontend fails at the first encountered error; it does not
recover and invent missing statements.

| Stage | Diagnostic codes |
| --- | --- |
| Lexer | `ILLEGAL_CHARACTER`, `INVALID_INTEGER_LITERAL`, `INTEGER_OUT_OF_RANGE`, `UNTERMINATED_COMMENT`, `UNSUPPORTED_KEYWORD`, `UNSUPPORTED_OPERATOR` |
| Parser | `UNEXPECTED_TOKEN`, `UNEXPECTED_EOF`, `INVALID_ENTRY_POINT` |
| Semantic | `DUPLICATE_DECLARATION`, `UNDECLARED_VARIABLE`, `UNINITIALIZED_VARIABLE`, `DIVISION_BY_ZERO`, `MODULO_BY_ZERO`, `INTEGER_OVERFLOW`, `MISSING_RETURN` |
| Semantic warning | `UNREACHABLE_STATEMENT` |

Unexpected EOF has a zero-width span at the actual end of source, including
empty/comment-only files. Unexpected tokens retain their exact original lexeme
and position. CLI file/encoding errors are separate from source diagnostics.

## Implemented semantic analysis

Use C signed `int` semantics for a target with 32-bit `int`; the Phase 4 harness
checks and records that assumption with static assertions. Results outside that range are undefined
for this study and must not be folded into Python's unbounded integer values.
Literal magnitudes initially fit `0..2147483647`; spelling `-2147483648` is outside
the initial literal subset and can be extended deliberately later.

Division truncates toward zero, unlike Python floor division for negative values.
Remainder is `a - trunc(a / b) * b`. Zero divisors, `INT_MIN / -1` and
`INT_MIN % -1` are undefined; do not evaluate/fold them. Comparisons produce integer `0` or `1`,
and conditions treat zero as false, all other integers as true. Expressions are
side-effect-free because calls and assignments within expressions are unsupported.

Blocks have lexical scope; a declaration in a `for` initializer lives through
that loop only. To simplify the first implementation, declared variable names
must be unique across `main` (no shadowing). Reject duplicate declarations,
undeclared/out-of-scope references and reads not definitely initialized.
An `int x;` declaration is valid if `x` is assigned before every possible read.
Join conditional initialization facts by intersection over paths that continue;
a returning arm does not dilute initialization on its surviving sibling. A loop
body may run zero times. Declaration initializers cannot read their own
uninitialized variable.

Phase 1 handles token/grammar errors and constructs the AST; Phase 2 implements
these semantic checks before lowering. Known constants support diagnostics only:
safe literal expressions, straight-line assignments and agreeing branch facts
allow detection of a zero divisor or overflow. They do not rewrite syntax or TAC.
Every variable assigned in a loop body/update loses its known constant before
checking the condition/body and after the loop. This deliberately sacrifices
some first-iteration facts to avoid treating loop-carried values as invariant.
It is not a fixed-point value/range proof. For runtime-dependent cases, later correctness tests
must use defined, terminating inputs and separately report undefined behavior
or timeouts. The project does not claim to decide arbitrary termination or
semantic equivalence. Require an explicit return on every reachable function
exit in the supported study subset; return inside a loop is parseable but makes
that loop ineligible for initial unrolling.

`compiler/semantic.py` performs lexical binding first (including dead syntax),
then conservative dataflow over the structured AST. `analyze(program)` returns
immutable `SemanticAnalysis` annotations: ordered `Symbol` records, a read-only
node-ID-to-symbol mapping, warning diagnostics and dead node IDs. Symbols are
`s0`, `s1`, ... in declaration order, with name, declaration ID and source span.
`validate(program)` discards annotations/warnings and returns `None`; both APIs
are also available through `compiler.ir` for compatibility with the planned API.

Both `if` alternatives are considered possible, including `if(0)`/`if(1)`.
Every `for` may execute zero times, even if its constant condition appears true.
Therefore a literal true `if` alone does not establish initialization or a return,
and a literal false arm still receives semantic checks. Structural code after an
unconditional return (or an `if` with two returning arms), and a loop update after
an always-returning body, receives `UNREACHABLE_STATEMENT` warnings. Dead syntax
still has declaration/name legality checked; its arithmetic and initialization
reads are not evaluated. This policy is intentionally conservative and documented,
not a termination or path-feasibility solver.

V1 user code has no stdin/argv/I/O operations. Examples vary embedded integer
initializers to construct controlled cases. Each such source case is transformed
independently and compared with its own baseline; distinguish case IDs from
program-family IDs. External-input support requires a later explicit language
extension. Full return values must be observed by the validation harness because
exit statuses can hide differences (for example, returns of 0 and 256).

## Implemented AST

`compiler/ast_nodes.py` uses frozen, slotted, keyword-only dataclasses with one
`SourceSpan` per node and deterministic per-parse `n0`, `n1`, ... IDs allocated
during reductions. IDs support provenance/diagnostics, not semantic matching.
Block items are immutable tuples in Python and arrays in JSON. Phase 3
transformations rebuild every syntax node, retaining IDs for one-to-one rewrites
and allocating unique deterministic IDs for copies; separate origin maps retain
input provenance without changing AST classes or source spans.

`SourceSpan` fields are `start_line`, `start_column`, `end_line`, `end_column`,
`start_offset`, `end_offset`. Lines/columns are one-based, character offsets
zero-based and the end is exclusive. Node spans cover their complete syntactic
construct, excluding surrounding comments/whitespace. Parenthesized expressions
retain the inner node kind/ID but widen its span to include the parentheses.

| Node | Fields besides node ID and span |
| --- | --- |
| `Program` | `schema_version=1`, `function: Function` |
| `Function` | `name`, `return_type="int"`, `body: Block` |
| `Block` | `items`: ordered tuple of declarations/statements |
| `Declaration` | `name`, optional initializer expression |
| `Assignment` | `target: Identifier`, `value: Expression` |
| `If` | `condition`, `then_branch`, optional `else_branch` |
| `For` | declaration/assignment `initializer`, `condition`, assignment `update`, `body` |
| `Return` | value expression |
| `EmptyStatement` | no additional fields |
| `IntegerLiteral` | integer value |
| `Identifier` | name |
| `UnaryExpression` | operator, operand |
| `BinaryExpression` | operator, left, right |

`UnaryOperator` and `BinaryOperator` are typed string enums with actual operator
spellings; expression/statement unions provide shared type aliases. Use
`iter_child_nodes(node)` for immediate children and `walk(node)` for iterative
preorder traversal. `ast_to_dict(node)` and `ast_to_json(node, indent=2)` serialize
explicit `kind`, all fields and spans; only the `Program` carries schema version.
PLY internals are never serialized. Serialization itself recursively visits
dataclasses and is bounded by Python's recursion limit. Ordinary nested lab
programs are covered by tests; the CLI handles an exceeded limit without a traceback.

Declaration spans include the semicolon for ordinary declarations; a `for`
initializer span excludes the header separator. Assignment statements include
the semicolon, while assignments inside loop headers do not. Phase 2 symbol
resolution uses a separate node-to-symbol mapping without changing these nodes.

Supported example (the loop structure is exercised by `examples/loops/sum.c`):

```c
int main(void) {
    int total = 0;
    for (int i = 0; i < 4; i = i + 1) {
        total = total + i;
    }
    if (total > 3) {
        return total;
    } else {
        return 0;
    }
}
```

Its AST retains loop initializer/condition/update/body as separate children and
both return branches. Structured AST output and rendered AST diagrams
are implemented. CLI usage and actual output excerpts are in the README.

## Implemented three-address IR

Use a typed, non-SSA representation with `Constant`, `SymbolRef`, and `TempRef`
operands. Source variable storage uses resolved symbol IDs. Allocate temporaries
and labels deterministically per program. Retain source-node provenance per
instruction. Text output is for inspection; downstream modules use records,
not text parsing.

| Instruction | Meaning |
| --- | --- |
| `Label(name)` | Branch target / block boundary |
| `Copy(destination, operand)` | Variable or temporary assignment |
| `Unary(destination, operator, operand)` | Unary expression evaluation |
| `Binary(destination, operator, left, right)` | One arithmetic/comparison operation |
| `Branch(condition, true_label, false_label)` | Explicit two-way control transfer |
| `Jump(label)` | Unconditional control transfer |
| `Return(operand)` | Function termination |

Declarations allocate symbols; initialized declarations emit copies, uninitialized
ones emit no value assignment. Every complex expression is recursively lowered
into temporaries. Example:

```text
int x = 2 + 3 * 4;

%t0 = 3 * 4
%t1 = 2 + %t0
x = %t1
```

An `if` branches to explicit then/else or merge labels, joining only paths that
have not returned. A `for` lowers as initializer → condition → body → update →
condition, with the false edge to exit. Body returns do not acquire a back edge.
Early returns terminate blocks. No implicit fallthrough past return is permitted.
Source after a structural terminal is warned and omitted. This is control-flow
lowering, not a Phase 3 optimization: arithmetic operations, unary operations,
copies and constant-condition branch edges remain intact.

`compiler.ir.lower_ir(program)` validates first, then produces a frozen
`IRProgram(instructions, symbols, schema_version=1, diagnostics=())`. Operands
are frozen `Constant(value)`, `SymbolRef(symbol_id, name)`, and `TempRef(name)`;
only symbol/temp references may be destinations. Instruction records have
mandatory `node_id` and `span` metadata, and typed operator enums from the AST.
`format_instruction`/`format_ir` provide deterministic text, while consumers use
the typed records. Temporaries print `%t0`, `%t1`, ... so a C variable named `t0`
remains distinct. Labels are `L0`, `L1`, ...; unused merge/update labels can leave
allocation gaps when a branch/body terminates. Lowering alone does not fold;
Phase 3 applies explicit AST passes before ordinary validated lowering.

`validate`/`analyze` are re-exported by `compiler.ir`; their implementation lives
in `compiler/semantic.py` to keep binding/dataflow independent from lowering.

## Implemented CFG and diagrams

CFG leaders are entry, branch targets and instructions following terminators.
Partition real IR instructions into basic blocks, with `true`, `false`, `jump`,
`fallthrough`, and `return` edges as applicable. Use explicit entry/exit nodes;
return edges lead to exit. Distinguish unreachable blocks when reporting graphs.
`build_cfg` validates that labels exist and are unique, operators/operands are
typed, and instructions carry metadata. Basic blocks retain TAC labels and use
deterministic `B0`, `B1`, ... IDs; entry/exit are synthetic graph nodes. The first
instruction, every label and every post-terminator instruction is a leader.
Return edges lead only to exit. Loop-back edges are actual jump edges to the
condition block, not an inferred source-level annotation. Reachability follows
both conditional successors. Manual TAC may contain unreachable blocks or a
final fallthrough-to-exit edge; semantic validation prevents a missing return
when IR is generated from user source.

`format_cfg` prints block contents and typed edges. `ast_to_dot` shows actual
syntax children and their field roles; `cfg_to_dot` shows actual blocks/TAC and
edge kinds, with unreachable blocks styled distinctly. Both escape user labels
and need no external executable. `render(dot, path, format)` writes a `.dot`
sidecar, then optionally invokes Graphviz with an argument list for SVG/PNG/PDF.
Missing/failed rendering is explicit and preserves the DOT file. The CLI supports
`--check`, `--tac`, `--cfg`, `--ast-dot`, `--cfg-dot`, `--output` and `--format`.
Syntax-only Phase 1 modes remain unchanged.

## Implemented transformations

### Constant environment and transfer rules

`propagate_and_fold(program)` in `transformations/constant_folding.py` validates
the input, resolves symbols with the existing analyzer, and maps symbol IDs to
known signed 32-bit integers. Absence means unknown. It transforms a fresh tree:

| Construct | Transfer / rewrite |
| --- | --- |
| Literal | Copy; its value is known if in range |
| Identifier read | Replace with a literal only if the symbol has a known fact |
| Declaration / assignment | Rewrite value, replace target fact if known, otherwise invalidate; never rewrite the target identifier |
| Unary/binary expression | Recursively rewrite operands and fold only a fully constant, defined operation |
| `if` | Rewrite condition but retain control structure; process independent environments; join equal facts on all continuing paths |
| `return` | Rewrite value and terminate continuing flow |
| Block | Process in order; remove local facts on exit; copy structurally dead syntax without propagating into it |
| `for` | Rewrite initializer, clear every body/update-written fact before condition/body; process update from continuing body facts; keep only initializer effects for untouched variables after exit |

A missing `else` is an unchanged alternative. Returning alternatives do not
dilute facts on a surviving path. A loop can run zero times, so no body/update
fact escapes. Nested loop assignments, including assignment initializers, count
as writes. Input no-shadowing/scope rules stay unchanged.

Arithmetic helpers in `transformations/common.py` compute C signed 32-bit
addition/subtraction/multiplication, unary signs and comparisons. Division uses
integer magnitudes and sign restoration to truncate toward zero; remainder is
`a - q*b`. Zero divisors, signed overflow, and INT_MIN divided/remainder by -1
return no fold. No `x*0`, `x-x`, reassociation or condition-pruning identities are
introduced. An unsafe raw expression retains its entire structure, including
otherwise safe child expressions, so `0*(1/0)` and `x/(1-1)` are not disguised.

The public `fold_expression(expression)` helper has no variable environment or
whole-program validation; it permits inspecting refusal on invalid raw arithmetic.
Full program passes require semantic validity. `IntegerLiteral` may hold a folded
negative value internally without broadening source-token syntax. The combined
propagation/folding pass reaches a stable repeated AST; a second application
commits no further rewrites to that result.

### Canonical loop proof and expansion

`unroll_loops(program, max_iterations=32)` accepts declaration/assignment
initializers with defined constant-expression starts, conditions with induction
identifier on the left of `<`, `<=`, `>` or `>=` and a constant-expression bound,
and updates `i = i + amount` or `i = i - amount`. Amount is a constant expression;
the mathematical signed step must be nonzero and agree with condition direction.
The explicit Phase 3 request extends the original positive-only plan to safe
negative steps and inclusive/descending comparisons. Reversed operands, `!=`,
unknown headers and uncertain termination remain ineligible.

For positive step d, strict count is `max(0, ceil((bound-start)/d))` and inclusive
count is `max(0, floor((bound-start)/d)+1)`. Descending cases use `start-bound`
and `abs(step)`. Implementation uses integer floor/ceiling formulas, never a
simulation that could hang. It proves `final = start + count*step` fits signed
32-bit. Monotonicity plus in-range endpoints proves all induction updates are
in range, including the last update before the condition becomes false. Proof
arithmetic uses Python integers; generated operations remain the original C AST.

Eligible bodies contain assignments, nested blocks and empty statements only.
Any induction write, declaration, conditional, return or nested `for` is rejected
with a source-located reason. No inner loop is expanded inside an outer loop.
The default maximum is 32; the configuration range 0..1024 bounds expansion.
The replacement is a block containing initializer, then each body/update copy in
order. Every copied subtree gets fresh IDs. The initializer occurs exactly once,
loop-local declaration scope is preserved, and assignment-form induction values
remain visible afterward. Zero trips retain only initializer effects.

Body operations are copied unchanged; unrolling alone does not substitute i or
fold arithmetic. A later constants pass can simplify those copies. Revalidation
may reveal a previously unknown division/overflow; in that case the whole pass
rolls back and reports `REVALIDATION_FAILED`. The proof establishes control/count
safety for defined source executions, not arbitrary runtime arithmetic safety.

### Reports, sequencing and provenance

`TransformationResult(program, report, origins)` always has a fresh program.
`TransformationReport` records pass name/version, parameters, status, actual
committed statistics and source-located decisions. Status is `applied` for a
committed change; without changes, unsafe candidates give `rejected`, and no
opportunity gives `not_applicable`. Applied passes may also report other skipped
loops. Revalidation rejection restores a fresh input and zeroes committed stats.

One-to-one rewrites keep IDs/spans; cloned copies allocate collision-free `uN`
IDs while preserving spans and origin mapping. `apply_transformations` accepts
explicit ordered `constants`/`unroll` names, including repeats or an empty
sequence. Its fresh `PipelineResult` contains exact sequence and reports, with
origins composed back to the initial AST. It continues after rejection using the
valid preserved input. Default sequence is `constants`, then `unroll`; a final
`constants` pass is explicit when further simplification is desired.

Statistics count committed folds, propagated identifier reads, loops replaced,
iterations expanded and changed AST nodes. They are not machine instructions
or performance measurements. Reports are deterministic and JSON-serializable.

### C emission and validation boundary

`compiler/codegen.py` implements pure `emit_c(program)`, re-exported from
`compiler.ir` as planned. The separate module keeps formatting away from IR
records/lowering. It validates, emits `int main(void)`, fully parenthesizes
expressions, braces control bodies and preserves names, blocks/scopes and dead
syntax. Comments/whitespace are not AST fields and are formatted canonically.
Negative folded literals use unary-minus spelling; INT_MIN is emitted as
`(-2147483647 - 1)`, respecting the unchanged decimal literal bound.

Tests use parse/analyze/TAC/CFG round trips and independently derived full integer
expectations via test-only arithmetic/TAC oracles. They cover safety refusals,
scope/freshness, deterministic reports, stable repeats, signed boundaries and
ordering. Phase 3 did not include Clang/process/runtime-equivalence code;
Phase 4 adds those checks below. Emission itself is source generation, not
compilation or execution, and these tests are not a universal equivalence proof.

## Phase 4 — machine validation boundary

`runtime.harness.make_harness(Program)` starts from the existing canonical emitter
and unchanged semantic validator. A round trip confirms the emitted subset.
Only the verified initial `int main(void) {` header is replaced with a structurally
allocated collision-free static entry. No regex or source-string rewriting of
arbitrary C is used. Headers follow the computation so user locals named `EOF`,
`INT_MIN`, `stdin`, etc. keep their meaning. The internal wrapper calls the entry
once, writes a version-1 JSON file containing the complete returned `int`, and
exits 0. Stdout, stderr, full return and wrapper process status remain separate.
Strict observation parsing rejects ambiguous or incomplete records; no exit-code
fallback exists. The wrapper grammar is infrastructure, not supported user syntax.

C static assertions enforce `CHAR_BIT=8`, `sizeof(int)=4`, `INT_MIN=-2147483648`
and `INT_MAX=2147483647`. Original and transformed C are independently compiled
using identical `-std=c11 -O0` or separately selected `-O2`. Default UBSan flags
are `-fsanitize=undefined -fno-sanitize-recover=all`; controlled runtime options
halt on detection. Diagnostic-only extra flags cannot replace this contract.
A known-valid capability program checks the target/sanitizer environment first.
Missing support is explicit, with no silent fallback. A matching unsanitized pair
is inconclusive. Static faults remain the existing source diagnostics; dynamic
arithmetic faults observed by UBSan invalidate comparison even when both fail.

Integer addition/subtraction/multiplication must stay in the signed range.
Division truncates toward zero and remainder follows the dividend's sign via
`a - trunc(a/b)*b`. Zero divisors and both `INT_MIN / -1` and `INT_MIN % -1`
remain undefined. Real tests cover boundary values, negative operands, dynamic
overflow/zero divisors, conditional execution, positive/negative/zero-trip loops
and the final induction update. No wraparound is assumed and Python arithmetic
is never used as the production machine result.

`check_equivalence` reuses the Phase 3 ordered pipeline and preserves input and
composed origins/applicability. It compares full returns, stdout/stderr and normal
process status after independent builds/runs. `compare_sources` supplies actual
negative controls, including 1 versus 257. A rejected/inapplicable pipeline yields
`no_transformation`, not evidence for an unchanged optimization. Compilation
failure, execution failure, timeout, UB, unavailability and inconclusiveness are
distinct from different behavior. Passing comparison is observed equivalence for
the evaluated closed source fixtures/conditions, never formal equivalence.

Context-owned temporary builds/runs, argument-list subprocesses, controlled
environment, process-group termination, bounded captures and available POSIX
resource limits contain accidental runaway work. They are not a security sandbox.
Versioned reports include source/harness hashes and canonical C, keep deterministic
results separate from environmental paths/compiler/platform metadata, and contain
no timings or performance fields. macOS arm64/Apple Clang 21.0.0 has actual O0/O2
coverage; Linux is not yet verified. Details, real emitted programs and commands
are in [PHASE4_VALIDATION.md](PHASE4_VALIDATION.md). Phase 5 has not begun.

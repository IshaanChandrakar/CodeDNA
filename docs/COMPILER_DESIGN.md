# Compiler design

Status: proposed implementation contract, not implemented functionality.
Updated 2026-10-09. This document defines the initial subset and representations
to share between contributors.

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

## Grammar sketch

This EBNF is the planned PLY grammar, not a parser implemented during setup.
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
so it has no expression precedence. Resolve dangling `else` to the nearest
unmatched `if` with explicit grammar/precedence and test the resolution. Document
any intended PLY conflict; unexplained parser conflicts fail Phase 1 acceptance.

## Semantics and validation

Use C signed `int` semantics for a target with 32-bit `int`; the runtime checks
the target and records it. Arithmetic results outside that range are undefined
for this study and must not be folded into Python's unbounded integer values.
Literal magnitudes initially fit `0..2147483647`; spelling `-2147483648` is outside
the initial literal subset and can be extended deliberately later.

Division truncates toward zero, unlike Python floor division for negative values.
Remainder is `a - trunc(a / b) * b`. Division by zero and `INT_MIN / -1` are
undefined; do not evaluate/fold them. Comparisons produce integer `0` or `1`,
and conditions treat zero as false, all other integers as true. Expressions are
side-effect-free because calls and assignments within expressions are unsupported.

Blocks have lexical scope; a declaration in a `for` initializer lives through
that loop only. To simplify the first implementation, declared variable names
must be unique across `main` (no shadowing). Reject duplicate declarations,
undeclared/out-of-scope references and reads not definitely initialized.
An `int x;` declaration is valid if `x` is assigned before every possible read.
Join conditional initialization facts by intersection; a loop body may run zero
times. Declaration initializers cannot read their own uninitialized variable.

Phase 1 handles token/grammar errors and constructs the AST; Phase 2 introduces
these semantic checks before lowering. Detect statically provable undefined
arithmetic in validation; for runtime-dependent cases, later correctness tests
must use defined, terminating inputs and separately report undefined behavior
or timeouts. The project does not claim to decide arbitrary termination or
semantic equivalence. Require an explicit return on every reachable function
exit in the supported study subset; return inside a loop is parseable but makes
that loop ineligible for initial unrolling.

V1 user code has no stdin/argv/I/O operations. Examples vary embedded integer
initializers to construct controlled cases. Each such source case is transformed
independently and compared with its own baseline; distinguish case IDs from
program-family IDs. External-input support requires a later explicit language
extension. Full return values must be observed by the validation harness because
exit statuses can hide differences (for example, returns of 0 and 256).

## Planned AST

Use dataclasses, one source span per node, and deterministic local node IDs.
IDs support provenance and diagnostics, not semantic matching. Keep the baseline
AST immutable in practice; transformation passes return fresh nodes. New nodes
have unique IDs and a separate origin map to original IDs/spans.

| Node | Fields besides node ID and span |
| --- | --- |
| `Program` | `schema_version`, `function: Function` |
| `Function` | `name`, `return_type="int"`, `body: Block` |
| `Block` | ordered list of declarations/statements |
| `Declaration` | `name`, optional initializer expression |
| `Assignment` | target identifier, value expression |
| `If` | condition, then statement, optional else statement |
| `For` | declaration/assignment initializer, condition, assignment update, body |
| `Return` | value expression |
| `EmptyStatement` | no additional fields |
| `IntegerLiteral` | integer value |
| `Identifier` | name |
| `UnaryExpression` | operator, operand |
| `BinaryExpression` | operator, left, right |

Serialize nodes with explicit `kind`, fields, span and schema version. Never
serialize PLY internals. Symbol resolution adds a separate mapping from node IDs
to symbol IDs; downstream IR uses symbols, avoiding accidental scope ambiguity.

Example to parse in Phase 1 (a specification example, not a current fixture):

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

Its AST must retain loop initializer/condition/update/body as separate children
and both return branches. Structured AST output is available in Phase 1; rendered
AST diagrams wait until Phase 2.

## Planned three-address IR

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

t0 = 3 * 4
t1 = 2 + t0
x = t1
```

An `if` branches to explicit then/else or merge labels, joining only paths that
have not returned. A `for` lowers as initializer → condition → body → update →
condition, with the false edge to exit. Body returns do not acquire a back edge.
Early returns terminate blocks. No implicit fallthrough past return is permitted.

CFG leaders are entry, branch targets and instructions following terminators.
Partition real IR instructions into basic blocks, with `true`, `false`, `jump`,
`fallthrough`, and `return` edges as applicable. Use explicit entry/exit nodes;
return edges lead to exit. Distinguish unreachable blocks when reporting graphs.
Validate that each label exists, terminators end blocks, and all successors agree
with the IR. DOT rendering uses structural node IDs with escaped user labels.

## Planned transformation correctness

Constant propagation uses scoped environments with unknown/known-constant facts.
Assignment updates the environment; branches use copies and join only facts that
agree on reachable successors. For loops, conservatively invalidate every
variable the loop can write before folding the condition/body, and invalidate
those facts after the loop. Preserve evaluation and control flow when safety is
not established. Folding computes genuine safe integer operations; it must not
turn `x * 0` into zero if doing so removes an undefined subexpression.

Initial unrolling fully expands only small counted loops (at most 32 iterations):
constant start/bound, condition `i < bound`, positive constant step expressed as
`i = i + step`, and all induction arithmetic proven in range. The body cannot
write `i`, declare variables, contain another loop or return, or otherwise change
the iteration count. Skip every unproven loop with a reason. Keep initializer,
each cloned body and each update, including the final induction value. Preserve
the scope of a loop-local declaration with a block. Zero-iteration loops retain
initializer effects. No speculative partial unrolling or fabricated variants.

Validate both passes structurally and through exact full-return comparisons on
defined fixtures. Include negative division/remainder, branching, zero-iteration
loops, boundary iteration counts, modified induction variables, return-in-loop,
and skipped overflow cases. Dynamic agreement supports tested cases; it does
not constitute proof of equivalence beyond the pass's stated preconditions.

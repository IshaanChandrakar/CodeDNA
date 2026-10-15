# Compiler design

Status: Phases 1–2 lexical/syntax grammar, AST, semantic checks, TAC, CFG and
visualization implemented; transformations remain planned. Updated 2026-10-15.
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

Use C signed `int` semantics for a target with 32-bit `int`; the future runtime
must check and record that target assumption. Arithmetic results outside that range are undefined
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
Block items are immutable tuples in Python and arrays in JSON. Future
transformations return fresh nodes with unique IDs and an origin map; this map
and the passes are not implemented in Phase 1.

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
allocation gaps when a branch/body terminates. No constant folding occurs.

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

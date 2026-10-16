"""Deterministic source emission for the existing restricted C AST.

This is syntax emission, not a compiler runner or an optimization pass.  Every
expression is parenthesized, control bodies use braces, and existing blocks and
dead source statements are retained.  The original tree is never rewritten.
"""

from __future__ import annotations

from compiler import ast_nodes as ast
from compiler.semantic import INT_MIN, analyze


def _expression(node: ast.Expression) -> str:
    if isinstance(node, ast.IntegerLiteral):
        if node.value == INT_MIN:
            # The frontend accepts literal magnitudes only up to INT_MAX.  This
            # defined pair of int operations also represents a folded INT_MIN
            # without extending the lexer or relying on a larger C integer type.
            return "(-2147483647 - 1)"
        return f"({node.value})"
    if isinstance(node, ast.Identifier):
        return f"({node.name})"
    if isinstance(node, ast.UnaryExpression):
        return f"({node.operator.value}{_expression(node.operand)})"
    if isinstance(node, ast.BinaryExpression):
        return f"({_expression(node.left)} {node.operator.value} {_expression(node.right)})"
    raise TypeError(f"Unsupported expression node: {type(node).__name__}")


def _declaration(node: ast.Declaration) -> str:
    initializer = "" if node.initializer is None else f" = {_expression(node.initializer)}"
    return f"int {node.name}{initializer}"


def _assignment(node: ast.Assignment) -> str:
    # The subset grammar requires a bare identifier on the assignment's left.
    return f"{node.target.name} = {_expression(node.value)}"


def _body(node: ast.Statement, level: int) -> list[str]:
    """Emit items within one pair of braces, keeping an existing block's scope."""
    if isinstance(node, ast.Block):
        return [line for item in node.items for line in _statement(item, level)]
    return _statement(node, level)


def _statement(node: ast.Declaration | ast.Statement, level: int) -> list[str]:
    indent = "    " * level
    if isinstance(node, ast.Declaration):
        return [f"{indent}{_declaration(node)};"]
    if isinstance(node, ast.Assignment):
        return [f"{indent}{_assignment(node)};"]
    if isinstance(node, ast.Return):
        return [f"{indent}return {_expression(node.value)};"]
    if isinstance(node, ast.EmptyStatement):
        return [f"{indent};"]
    if isinstance(node, ast.Block):
        return [f"{indent}{{", *_body(node, level + 1), f"{indent}}}"]
    if isinstance(node, ast.If):
        lines = [
            f"{indent}if {_expression(node.condition)} {{",
            *_body(node.then_branch, level + 1),
            f"{indent}}}",
        ]
        if node.else_branch is not None:
            lines[-1] += " else {"
            lines.extend([*_body(node.else_branch, level + 1), f"{indent}}}"])
        return lines
    if isinstance(node, ast.For):
        initializer = (
            _declaration(node.initializer) if isinstance(node.initializer, ast.Declaration)
            else _assignment(node.initializer)
        )
        return [
            f"{indent}for ({initializer}; {_expression(node.condition)}; {_assignment(node.update)}) {{",
            *_body(node.body, level + 1),
            f"{indent}}}",
        ]
    raise TypeError(f"Unsupported statement node: {type(node).__name__}")


def emit_c(program: ast.Program) -> str:
    """Validate and emit canonical subset C with a terminating newline.

    Semantic errors use the existing source-located diagnostics.  Nonfatal dead
    source remains in the emitted function; lowering can independently omit it.
    Folded negative integer nodes use unary-minus spellings accepted by the
    unchanged frontend, including a safe expression for signed 32-bit INT_MIN.
    """
    analyze(program)
    return "\n".join([
        "int main(void) {",
        *_body(program.function.body, 1),
        "}",
        "",
    ])

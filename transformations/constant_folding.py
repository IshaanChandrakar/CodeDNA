"""Conservative, scoped constant propagation and signed-int constant folding.

The environment maps resolved symbol IDs to known signed 32-bit integers;
absence means unknown. Assignments replace that fact, branches intersect equal
facts from continuing arms, and loops forget every possibly written entry fact.
Control flow and expression evaluation remain intact: there is no branch pruning
or algebraic rewrite such as ``unknown * 0``. All returned syntax nodes are fresh.
"""

from __future__ import annotations

from dataclasses import dataclass

from compiler import ast_nodes as ast
from compiler.semantic import SemanticAnalysis, analyze
from transformations.common import (
    CloneFactory, Decision, Statistics, TransformationResult, evaluate_binary,
    evaluate_constant, evaluate_unary, finish_result,
)


Environment = dict[str, int]


@dataclass(slots=True)
class _Expression:
    node: ast.Expression
    constant: int | None
    folds: int = 0
    references: int = 0
    decisions: tuple[Decision, ...] = ()
    unsafe: bool = False


@dataclass(slots=True)
class _Statement:
    node: ast.Declaration | ast.Statement
    environment: Environment
    continues: bool = True


class _Folder:
    def __init__(self, factory: CloneFactory, analysis: SemanticAnalysis | None = None) -> None:
        self.factory = factory
        self.analysis = analysis
        self.expressions_folded = 0
        self.references_propagated = 0
        self.decisions: list[Decision] = []

    def expression(self, node: ast.Expression, environment: Environment) -> _Expression:
        if isinstance(node, ast.IntegerLiteral):
            return _Expression(self.factory.clone(node), evaluate_constant(node))
        if isinstance(node, ast.Identifier):
            symbol = self.analysis.bindings[node.node_id] if self.analysis is not None else None
            if symbol is not None and symbol.symbol_id in environment:
                value = environment[symbol.symbol_id]
                return _Expression(ast.IntegerLiteral(**self.factory.metadata(node), value=value), value, references=1)
            return _Expression(self.factory.clone(node), None)
        if isinstance(node, ast.UnaryExpression):
            operand = self.expression(node.operand, environment)
            if operand.unsafe:
                return _Expression(self.factory.clone(node), None, decisions=operand.decisions, unsafe=True)
            if operand.constant is not None:
                value = evaluate_unary(node.operator, operand.constant)
                if value is None:
                    return self.unsafe(node)
                return _Expression(
                    ast.IntegerLiteral(**self.factory.metadata(node), value=value), value,
                    operand.folds + 1, operand.references, operand.decisions,
                )
            return _Expression(
                ast.UnaryExpression(**self.factory.metadata(node), operator=node.operator, operand=operand.node),
                None, operand.folds, operand.references, operand.decisions,
            )
        if not isinstance(node, ast.BinaryExpression):
            raise TypeError(f"Unsupported expression node: {type(node).__name__}")
        left = self.expression(node.left, environment)
        right = self.expression(node.right, environment)
        decisions = left.decisions + right.decisions
        # A failed child operation must not disappear through a parent rewrite.
        # Restore the full enclosing expression, including any safe child folds.
        if left.unsafe or right.unsafe:
            return _Expression(self.factory.clone(node), None, decisions=decisions, unsafe=True)
        if right.constant == 0 and node.operator in (ast.BinaryOperator.DIVIDE, ast.BinaryOperator.REMAINDER):
            return self.unsafe(node)
        if left.constant is not None and right.constant is not None:
            value = evaluate_binary(node.operator, left.constant, right.constant)
            if value is None:
                return self.unsafe(node)
            return _Expression(
                ast.IntegerLiteral(**self.factory.metadata(node), value=value), value,
                left.folds + right.folds + 1, left.references + right.references, decisions,
            )
        return _Expression(
            ast.BinaryExpression(
                **self.factory.metadata(node), operator=node.operator, left=left.node, right=right.node,
            ), None, left.folds + right.folds, left.references + right.references, decisions,
        )

    def unsafe(self, node: ast.Expression) -> _Expression:
        decision = Decision(
            node_id=node.node_id, code="UNSAFE_ARITHMETIC",
            message="Constant operation is undefined for signed 32-bit int; its expression is preserved",
            status="rejected", span=node.span,
        )
        return _Expression(self.factory.clone(node), None, decisions=(decision,), unsafe=True)

    def use(self, node: ast.Expression, environment: Environment) -> tuple[ast.Expression, int | None]:
        expression = self.expression(node, environment)
        self.expressions_folded += expression.folds
        self.references_propagated += expression.references
        self.decisions.extend(expression.decisions)
        return expression.node, expression.constant

    def symbol_id(self, node: ast.Declaration | ast.Identifier) -> str:
        assert self.analysis is not None
        return self.analysis.bindings[node.node_id].symbol_id

    @staticmethod
    def join(left: _Statement, right: _Statement) -> tuple[Environment, bool]:
        if not left.continues and not right.continues:
            return {}, False
        if not left.continues:
            return right.environment, True
        if not right.continues:
            return left.environment, True
        return {
            symbol_id: value for symbol_id, value in left.environment.items()
            if right.environment.get(symbol_id) == value
        }, True

    def statement(self, node: ast.Declaration | ast.Statement, environment: Environment) -> _Statement:
        if isinstance(node, ast.Declaration):
            value = None
            constant = None
            if node.initializer is not None:
                value, constant = self.use(node.initializer, environment)
            symbol_id = self.symbol_id(node)
            environment.pop(symbol_id, None)
            if constant is not None:
                environment[symbol_id] = constant
            return _Statement(ast.Declaration(**self.factory.metadata(node), name=node.name, initializer=value), environment)
        if isinstance(node, ast.Assignment):
            value, constant = self.use(node.value, environment)
            symbol_id = self.symbol_id(node.target)
            environment.pop(symbol_id, None)
            if constant is not None:
                environment[symbol_id] = constant
            return _Statement(ast.Assignment(
                **self.factory.metadata(node), target=self.factory.clone(node.target), value=value,
            ), environment)
        if isinstance(node, ast.Return):
            value, _ = self.use(node.value, environment)
            return _Statement(ast.Return(**self.factory.metadata(node), value=value), environment, False)
        if isinstance(node, ast.EmptyStatement):
            return _Statement(self.factory.clone(node), environment)
        if isinstance(node, ast.Block):
            items: list[ast.Declaration | ast.Statement] = []
            continues = True
            for item in node.items:
                if continues:
                    transformed = self.statement(item, environment)
                    items.append(transformed.node)
                    environment = transformed.environment
                    continues = transformed.continues
                else:
                    # Binding legality was checked by analyze(). Evaluated facts
                    # must never be propagated into structurally dead syntax.
                    items.append(self.factory.clone(item))
            for item in node.items:
                if isinstance(item, ast.Declaration):
                    environment.pop(self.symbol_id(item), None)
            return _Statement(ast.Block(**self.factory.metadata(node), items=tuple(items)), environment, continues)
        if isinstance(node, ast.If):
            condition, _ = self.use(node.condition, environment)
            then_branch = self.statement(node.then_branch, environment.copy())
            else_branch = (
                self.statement(node.else_branch, environment.copy())
                if node.else_branch is not None else _Statement(node, environment.copy())
            )
            joined, continues = self.join(then_branch, else_branch)
            return _Statement(ast.If(
                **self.factory.metadata(node), condition=condition, then_branch=then_branch.node,
                else_branch=else_branch.node if node.else_branch is not None else None,
            ), joined, continues)
        if isinstance(node, ast.For):
            initializer = self.statement(node.initializer, environment)
            written = {
                self.symbol_id(item.target)
                for part in (node.body, node.update)
                for item in ast.walk(part) if isinstance(item, ast.Assignment)
            }
            iteration_environment = initializer.environment.copy()
            for symbol_id in written:
                iteration_environment.pop(symbol_id, None)
            condition, _ = self.use(node.condition, iteration_environment)
            body = self.statement(node.body, iteration_environment.copy())
            update = (
                self.statement(node.update, body.environment).node
                if body.continues else self.factory.clone(node.update)
            )
            # A loop may execute zero times. Keep initializer effects, but neither
            # first-iteration nor final-iteration body facts escape the loop.
            after = initializer.environment.copy()
            for symbol_id in written:
                after.pop(symbol_id, None)
            if isinstance(node.initializer, ast.Declaration):
                after.pop(self.symbol_id(node.initializer), None)
            return _Statement(ast.For(
                **self.factory.metadata(node), initializer=initializer.node,
                condition=condition, update=update, body=body.node,
            ), after)
        raise TypeError(f"Unsupported statement node: {type(node).__name__}")


def fold_expression(expression: ast.Expression) -> ast.Expression:
    """Fold a raw expression using safe arithmetic; unknown/unsafe structure stays.

    This helper deliberately performs no whole-program semantic validation, so
    callers can inspect refusal to fold undefined arithmetic. It has no variable
    environment and therefore never replaces identifier references.
    """
    return _Folder(CloneFactory(expression)).expression(expression, {}).node


def propagate_and_fold(program: ast.Program) -> TransformationResult:
    """Return a fresh, revalidated constant-propagated/folded program and report."""
    analysis = analyze(program)
    factory = CloneFactory(program)
    folder = _Folder(factory, analysis)
    body = folder.statement(program.function.body, {}).node
    function = ast.Function(
        **factory.metadata(program.function), name=program.function.name,
        body=body, return_type=program.function.return_type,
    )
    candidate = ast.Program(**factory.metadata(program), function=function, schema_version=program.schema_version)
    statistics = Statistics(
        expressions_folded=folder.expressions_folded,
        references_propagated=folder.references_propagated,
        changed_nodes=folder.expressions_folded + folder.references_propagated,
    )
    return finish_result(
        program, candidate, name="constant_propagation_folding", statistics=statistics,
        decisions=tuple(folder.decisions), origins=factory.origins,
    )

"""Conservative full unrolling of small, canonical counted ``for`` loops.

This pass only copies assignments, empty statements and blocks.  It neither
substitutes induction values nor folds expressions.  Counts are proven by
integer arithmetic, never by simulating a possibly nonterminating loop.
"""

from __future__ import annotations

from compiler import ast_nodes as ast
from compiler.semantic import INT_MAX, INT_MIN, SemanticAnalysis, analyze
from transformations.common import (
    CloneFactory,
    Decision,
    MAX_UNROLL_LIMIT,
    Statistics,
    TransformationResult,
    evaluate_constant,
    finish_result,
)


MAX_UNROLL_ITERATIONS = MAX_UNROLL_LIMIT


class _Unroller:
    def __init__(self, program: ast.Program, analysis: SemanticAnalysis, maximum: int) -> None:
        self.analysis = analysis
        self.maximum = maximum
        self.factory = CloneFactory(program)
        self.decisions: list[Decision] = []
        self.loops_unrolled = 0
        self.iterations_expanded = 0

    def decision(self, node: ast.For, code: str, message: str, *, status: str = "rejected") -> None:
        self.decisions.append(Decision(
            node_id=node.node_id, code=code, message=message, status=status, span=node.span,
        ))

    def symbol_id(self, node: ast.Identifier | ast.Declaration) -> str:
        return self.analysis.bindings[node.node_id].symbol_id

    def reject(self, node: ast.For, code: str, message: str) -> ast.For:
        self.decision(node, code, message)
        # No loop nested inside another loop is independently transformed.
        # Report every nested occurrence even if the outer header was rejected.
        for descendant in ast.walk(node.body):
            if isinstance(descendant, ast.For):
                self.decision(descendant, "NESTED_LOOP_CONTEXT", "Loops nested inside another loop are outside the initial unrolling subset")
        return self.factory.clone(node)

    def visit(self, node: ast.Node) -> ast.Node:
        if node.node_id in self.analysis.unreachable_node_ids:
            for descendant in ast.walk(node):
                if isinstance(descendant, ast.For):
                    self.decision(descendant, "UNREACHABLE_LOOP", "Structurally unreachable loops are preserved without transformation", status="not_applicable")
            return self.factory.clone(node)
        metadata = self.factory.metadata
        if isinstance(node, ast.Program):
            return ast.Program(**metadata(node), function=self.visit(node.function), schema_version=node.schema_version)
        if isinstance(node, ast.Function):
            return ast.Function(**metadata(node), name=node.name, body=self.visit(node.body), return_type=node.return_type)
        if isinstance(node, ast.Block):
            return ast.Block(**metadata(node), items=tuple(self.visit(item) for item in node.items))
        if isinstance(node, ast.If):
            return ast.If(
                **metadata(node), condition=self.factory.clone(node.condition),
                then_branch=self.visit(node.then_branch),
                else_branch=self.visit(node.else_branch) if node.else_branch is not None else None,
            )
        if isinstance(node, ast.For):
            return self.unroll(node)
        return self.factory.clone(node)

    def unroll(self, node: ast.For) -> ast.Block | ast.For:
        initializer = node.initializer
        induction = initializer if isinstance(initializer, ast.Declaration) else initializer.target
        start_expression = initializer.initializer if isinstance(initializer, ast.Declaration) else initializer.value
        start = evaluate_constant(start_expression) if start_expression is not None else None
        if start is None:
            return self.reject(node, "NONCONSTANT_START", "The induction initializer must be a defined constant expression")
        induction_id = self.symbol_id(induction)

        condition = node.condition
        comparisons = {
            ast.BinaryOperator.LESS, ast.BinaryOperator.LESS_EQUAL,
            ast.BinaryOperator.GREATER, ast.BinaryOperator.GREATER_EQUAL,
        }
        if not (
            isinstance(condition, ast.BinaryExpression)
            and condition.operator in comparisons
            and isinstance(condition.left, ast.Identifier)
            and self.symbol_id(condition.left) == induction_id
        ):
            return self.reject(node, "NONCANONICAL_CONDITION", "Use the induction variable on the left of <, <=, > or >=")
        bound = evaluate_constant(condition.right)
        if bound is None:
            return self.reject(node, "NONCONSTANT_BOUND", "The loop bound must be a defined constant expression")

        update = node.update
        expression = update.value
        if not (
            self.symbol_id(update.target) == induction_id
            and isinstance(expression, ast.BinaryExpression)
            and expression.operator in {ast.BinaryOperator.ADD, ast.BinaryOperator.SUBTRACT}
            and isinstance(expression.left, ast.Identifier)
            and self.symbol_id(expression.left) == induction_id
        ):
            return self.reject(node, "NONCANONICAL_UPDATE", "Use an update of the form i = i + constant or i = i - constant")
        amount = evaluate_constant(expression.right)
        if amount is None:
            return self.reject(node, "NONCONSTANT_STEP", "The induction update must use a defined constant step")
        step = amount if expression.operator == ast.BinaryOperator.ADD else -amount
        if step == 0:
            return self.reject(node, "ZERO_STEP", "A zero induction step does not establish finite termination")
        ascending = condition.operator in {ast.BinaryOperator.LESS, ast.BinaryOperator.LESS_EQUAL}
        if (ascending and step < 0) or (not ascending and step > 0):
            return self.reject(node, "STEP_DIRECTION", "The induction step must move toward the comparison bound")

        for descendant in ast.walk(node.body):
            if isinstance(descendant, ast.For):
                return self.reject(node, "NESTED_LOOP_BODY", "Bodies containing nested loops are outside the initial unrolling subset")
            if isinstance(descendant, ast.Declaration):
                return self.reject(node, "DECLARATION_IN_BODY", "Loop-body declarations cannot be safely duplicated under the unique-name scope rules")
            if isinstance(descendant, ast.Return):
                return self.reject(node, "RETURN_IN_BODY", "Loop bodies containing returns are outside the initial unrolling subset")
            if isinstance(descendant, ast.If):
                return self.reject(node, "CONDITIONAL_BODY", "Conditional loop bodies are outside the initial straight-line unrolling subset")
            if isinstance(descendant, ast.Assignment) and self.symbol_id(descendant.target) == induction_id:
                return self.reject(node, "INDUCTION_WRITE", "The body must not assign to the induction variable")

        # A strict comparison uses a ceiling; an inclusive one includes the
        # boundary value.  Python integers are used only for this proof, never
        # as a replacement for C arithmetic in the generated body or updates.
        distance = bound - start if ascending else start - bound
        magnitude = abs(step)
        inclusive = condition.operator in {ast.BinaryOperator.LESS_EQUAL, ast.BinaryOperator.GREATER_EQUAL}
        count = max(0, distance // magnitude + 1) if inclusive else max(0, (distance + magnitude - 1) // magnitude)
        final_value = start + count * step
        # The monotone sequence from start through its final executed update
        # stays in range iff its endpoints do.  Checking only body values would
        # miss overflow in the last update before the terminating condition.
        if not INT_MIN <= final_value <= INT_MAX:
            return self.reject(node, "INDUCTION_OVERFLOW", "The final induction update would exceed the signed 32-bit int range")
        if count > self.maximum:
            return self.reject(node, "ITERATION_LIMIT", f"Proven iteration count {count} exceeds max_iterations={self.maximum}")

        items: list[ast.Declaration | ast.Statement] = [self.factory.clone(initializer)]
        for _ in range(count):
            items.append(self.factory.clone(node.body, fresh_ids=True))
            items.append(self.factory.clone(node.update, fresh_ids=True))
        self.loops_unrolled += 1
        self.iterations_expanded += count
        return ast.Block(**self.factory.metadata(node), items=tuple(items))


def unroll_loops(program: ast.Program, max_iterations: int = 32) -> TransformationResult:
    """Return a fresh AST and report for safe full loop unrolling.

    Starts, bounds and update amounts must be constant expressions independent
    of program state.  The comparison is ``i <, <=, >, >= bound``; updates are
    ``i = i + amount`` or ``i = i - amount`` with a nonzero compatible direction.
    Each body is a straight-line combination of assignments, blocks and empty
    statements, with no induction writes.  Nested loops, declarations, branches
    and returns are preserved with explicit safety decisions.

    A replacement block retains the initializer and loop scope.  Every body and
    update copy has fresh IDs, and updates remain after every copied iteration,
    preserving the final induction value for assignment-form initializers.
    Zero-trip loops retain only their initializer.  The original is validated
    before planning and the candidate is revalidated before being accepted.
    """
    if type(max_iterations) is not int or not 0 <= max_iterations <= MAX_UNROLL_ITERATIONS:
        raise ValueError(f"max_iterations must be an integer from 0 to {MAX_UNROLL_ITERATIONS}")
    analysis = analyze(program)
    unroller = _Unroller(program, analysis, max_iterations)
    candidate = unroller.visit(program)
    return finish_result(
        program, candidate, name="loop_unrolling",
        statistics=Statistics(
            loops_unrolled=unroller.loops_unrolled,
            iterations_expanded=unroller.iterations_expanded,
            changed_nodes=unroller.loops_unrolled,
        ),
        decisions=tuple(unroller.decisions), parameters=(("max_iterations", max_iterations),),
        origins=unroller.factory.origins,
    )

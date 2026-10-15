"""Genuine PLY LALR grammar; syntax construction only, not semantic analysis."""

from dataclasses import replace

from ply import yacc

from compiler.ast_nodes import (
    Assignment, BinaryExpression, BinaryOperator, Block, Declaration, EmptyStatement,
    For, Function, Identifier, If, IntegerLiteral, Program, Return, UnaryExpression,
    UnaryOperator,
)
from compiler.diagnostics import Diagnostic, ParseError
from compiler.lexer import CLexer, build_lexer, tokens


class _Grammar:
    tokens = tokens
    start = "program"
    # Expressions use layered productions. Only dangling else needs precedence.
    precedence = (("nonassoc", "IF_WITHOUT_ELSE"), ("nonassoc", "ELSE"))

    def __init__(self, lexer: CLexer) -> None:
        self.lexer = lexer
        self._next_id = 0

    def _node(self, node_type, first, last=None, **fields):
        first_span = first.span
        last_span = (first if last is None else last).span
        span = self.lexer.source_map.span(first_span.start_offset, last_span.end_offset)
        node_id = f"n{self._next_id}"
        self._next_id += 1
        return node_type(node_id=node_id, span=span, **fields)

    def p_program(self, p):
        "program : INT ID LPAREN parameters RPAREN block"
        if p[2] != "main":
            raise ParseError(Diagnostic(
                "parser", "INVALID_ENTRY_POINT", "Only a single int main() or int main(void) is supported",
                p.slice[2].span,
            ))
        function = self._node(Function, p.slice[1], p[6], name=p[2], body=p[6])
        p[0] = self._node(Program, function, function=function)

    def p_parameters(self, p):
        """parameters : VOID
                      | empty"""

    def p_block(self, p):
        "block : LBRACE block_items RBRACE"
        p[0] = self._node(Block, p.slice[1], p.slice[3], items=tuple(p[2]))

    def p_block_items(self, p):
        """block_items : block_items block_item
                       | empty"""
        if len(p) == 3:
            p[1].append(p[2])
            p[0] = p[1]
        else:
            p[0] = []

    def p_block_item(self, p):
        """block_item : declaration
                      | statement"""
        p[0] = p[1]

    def p_declaration(self, p):
        "declaration : INT ID initializer SEMICOLON"
        p[0] = self._node(Declaration, p.slice[1], p.slice[4], name=p[2], initializer=p[3])

    def p_initializer(self, p):
        """initializer : ASSIGN expression
                       | empty"""
        p[0] = p[2] if len(p) == 3 else None

    def p_statement(self, p):
        """statement : block
                     | assignment SEMICOLON
                     | if_statement
                     | for_statement
                     | RETURN expression SEMICOLON
                     | SEMICOLON"""
        if p.slice[1].type == "RETURN":
            p[0] = self._node(Return, p.slice[1], p.slice[3], value=p[2])
        elif p.slice[1].type == "SEMICOLON":
            p[0] = self._node(EmptyStatement, p.slice[1])
        elif len(p) == 3:
            p[0] = replace(p[1], span=self.lexer.source_map.span(
                p[1].span.start_offset, p.slice[2].span.end_offset,
            ))
        else:
            p[0] = p[1]

    def p_assignment(self, p):
        "assignment : ID ASSIGN expression"
        target = self._node(Identifier, p.slice[1], name=p[1])
        p[0] = self._node(Assignment, target, p[3], target=target, value=p[3])

    def p_if_statement(self, p):
        """if_statement : IF LPAREN expression RPAREN statement %prec IF_WITHOUT_ELSE
                        | IF LPAREN expression RPAREN statement ELSE statement"""
        p[0] = self._node(
            If, p.slice[1], p[len(p) - 1], condition=p[3], then_branch=p[5],
            else_branch=p[7] if len(p) == 8 else None,
        )

    def p_for_statement(self, p):
        "for_statement : FOR LPAREN for_initializer SEMICOLON expression SEMICOLON assignment RPAREN statement"
        p[0] = self._node(For, p.slice[1], p[9], initializer=p[3], condition=p[5], update=p[7], body=p[9])

    def p_for_initializer(self, p):
        """for_initializer : assignment
                           | INT ID ASSIGN expression"""
        p[0] = p[1] if len(p) == 2 else self._node(
            Declaration, p.slice[1], p[4], name=p[2], initializer=p[4],
        )

    def p_expression(self, p):
        "expression : equality"
        p[0] = p[1]

    def p_binary_expression(self, p):
        """equality : equality EQ relation
                    | equality NE relation
                    | relation
           relation : relation LT sum
                    | relation LE sum
                    | relation GT sum
                    | relation GE sum
                    | sum
           sum : sum PLUS product
               | sum MINUS product
               | product
           product : product STAR unary
                   | product SLASH unary
                   | product PERCENT unary
                   | unary"""
        p[0] = p[1] if len(p) == 2 else self._node(
            BinaryExpression, p[1], p[3], operator=BinaryOperator(p[2]), left=p[1], right=p[3],
        )

    def p_unary(self, p):
        """unary : PLUS unary
                 | MINUS unary
                 | primary"""
        p[0] = p[1] if len(p) == 2 else self._node(
            UnaryExpression, p.slice[1], p[2], operator=UnaryOperator(p[1]), operand=p[2],
        )

    def p_primary(self, p):
        """primary : INTEGER
                   | ID
                   | LPAREN expression RPAREN"""
        if len(p) == 4:
            # Parentheses change the grouping/span, not the documented node kinds.
            p[0] = replace(p[2], span=self.lexer.source_map.span(
                p.slice[1].span.start_offset, p.slice[3].span.end_offset,
            ))
        elif p.slice[1].type == "INTEGER":
            p[0] = self._node(IntegerLiteral, p.slice[1], value=p[1])
        else:
            p[0] = self._node(Identifier, p.slice[1], name=p[1])

    def p_empty(self, p):
        "empty :"

    def p_error(self, token):
        if token is None:
            end = len(self.lexer.source_map.source)
            diagnostic = Diagnostic(
                "parser", "UNEXPECTED_EOF", "Unexpected end of input; expected a complete int main function",
                self.lexer.source_map.span(end, end),
            )
        else:
            diagnostic = Diagnostic(
                "parser", "UNEXPECTED_TOKEN", f"Unexpected {token.type} token {token.lexeme!r}", token.span,
            )
        raise ParseError(diagnostic)


def parse(source: str) -> Program:
    """Parse one source into a fresh typed AST or raise a frontend diagnostic."""
    lexer = build_lexer(source)
    grammar = _Grammar(lexer)
    parser = yacc.yacc(
        module=grammar, start="program", debug=False, write_tables=False,
        tabmodule="compiler._ply_tables",
    )
    return parser.parse(lexer=lexer)

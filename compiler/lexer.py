"""PLY lexer for the documented C subset, with reusable per-source state."""

from dataclasses import dataclass
import re

from ply import lex

from compiler.ast_nodes import SourceSpan
from compiler.diagnostics import Diagnostic, LexicalError, SourceMap


KEYWORDS = {
    "int": "INT", "void": "VOID", "return": "RETURN", "if": "IF",
    "else": "ELSE", "for": "FOR",
}
# C11 reserved words that are not legal identifiers or supported syntax here.
UNSUPPORTED_KEYWORDS = frozenset("""
    auto break case char const continue default do double enum extern float goto
    inline long register restrict short signed sizeof static struct switch typedef
    union unsigned volatile while _Alignas _Alignof _Atomic _Bool _Complex _Generic
    _Imaginary _Noreturn _Static_assert _Thread_local
""".split())

OPERATORS = {
    "+": "PLUS", "-": "MINUS", "*": "STAR", "/": "SLASH", "%": "PERCENT",
    "=": "ASSIGN", "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE",
    ">": "GT", ">=": "GE", "(": "LPAREN", ")": "RPAREN",
    "{": "LBRACE", "}": "RBRACE", ";": "SEMICOLON",
}

tokens = (*KEYWORDS.values(), "ID", "INTEGER", *OPERATORS.values())


@dataclass(frozen=True, slots=True)
class TokenRecord:
    type: str
    value: str | int
    lexeme: str
    span: SourceSpan


class CLexer:
    """PLY-compatible input/token interface; input() resets all source state."""

    tokens = tokens
    t_ignore = " \t\f\v"

    def __init__(self, source: str = "") -> None:
        self.source_map = SourceMap(source)
        self._lexer = lex.lex(module=self)
        self.input(source)

    @property
    def lineno(self) -> int:
        # PLY reflects every attribute while constructing the underlying lexer.
        return self._lexer.lineno if hasattr(self, "_lexer") else 1

    @property
    def lexpos(self) -> int:
        return self._lexer.lexpos if hasattr(self, "_lexer") else 0

    def input(self, source: str) -> None:
        self.source_map = SourceMap(source)
        self._lexer.lineno = 1
        self._lexer.input(source)

    def token(self):
        token = self._lexer.token()
        if token is not None:
            token.lexeme = getattr(token, "lexeme", token.value)
            token.span = self.source_map.span(token.lexpos, token.lexpos + len(token.lexeme))
        return token

    def _error(self, code: str, message: str, start: int, end: int) -> None:
        raise LexicalError(Diagnostic("lexer", code, message, self.source_map.span(start, end)))

    def t_line_comment(self, token):
        r"//[^\r\n]*"
        # No token; the following newline is processed by t_newline.

    def t_block_comment(self, token):
        r"/\*"
        source = self.source_map.source
        closing = source.find("*/", token.lexer.lexpos)
        if closing < 0:
            self._error("UNTERMINATED_COMMENT", "Unterminated block comment", token.lexpos, len(source))
        end = closing + 2
        token.lexer.lineno += len(re.findall(r"\r\n|\r|\n", source[token.lexpos:end]))
        token.lexer.lexpos = end

    def t_newline(self, token):
        r"(?:\r\n|\r|\n)+"
        token.lexer.lineno += len(re.findall(r"\r\n|\r|\n", token.value))

    def t_INTEGER(self, token):
        r"[0-9][A-Za-z0-9_.]*"
        raw = token.value
        if not re.fullmatch(r"0|[1-9][0-9]*", raw):
            self._error(
                "INVALID_INTEGER_LITERAL", f"Expected a decimal integer without a suffix or leading zeros, got {raw!r}",
                token.lexpos, token.lexpos + len(raw),
            )
        # Compare strings before int() so even huge input cannot hit Python's digit limit.
        if len(raw) > 10 or (len(raw) == 10 and raw > "2147483647"):
            self._error("INTEGER_OUT_OF_RANGE", "Integer literal exceeds 2147483647", token.lexpos, token.lexpos + len(raw))
        token.lexeme = raw
        token.value = int(raw)
        return token

    def t_ID(self, token):
        r"[A-Za-z_][A-Za-z0-9_]*"
        if token.value in UNSUPPORTED_KEYWORDS:
            self._error(
                "UNSUPPORTED_KEYWORD", f"C keyword {token.value!r} is outside the supported subset",
                token.lexpos, token.lexpos + len(token.value),
            )
        token.type = KEYWORDS.get(token.value, "ID")
        return token

    def t_OPERATOR(self, token):
        r"\+\+|--|\+=|-=|\*=|/=|%=|&&|\|\||<<=?|>>=?|&=|\|=|\^=|->|==|!=|<=|>=|[+*/%=<>();{}-]"
        if token.value not in OPERATORS:
            self._error(
                "UNSUPPORTED_OPERATOR", f"Operator {token.value!r} is outside the supported subset",
                token.lexpos, token.lexpos + len(token.value),
            )
        token.type = OPERATORS[token.value]
        return token

    def t_error(self, token):
        self._error(
            "ILLEGAL_CHARACTER", f"Illegal character {token.value[0]!r}", token.lexpos, token.lexpos + 1,
        )


def build_lexer(source: str = "") -> CLexer:
    return CLexer(source)


def tokenize(source: str) -> list[TokenRecord]:
    lexer = build_lexer(source)
    result = []
    while (token := lexer.token()) is not None:
        result.append(TokenRecord(token.type, token.value, token.lexeme, token.span))
    return result


def format_tokens(records: list[TokenRecord]) -> str:
    """Readable positions, types, and typed values; no synthetic EOF token."""
    return "\n".join(
        f"{token.span.start_line}:{token.span.start_column} {token.type} {token.value!r}"
        for token in records
    )

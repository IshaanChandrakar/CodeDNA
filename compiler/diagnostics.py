"""Shared frontend diagnostics and source positioning, separate from syntax."""

from bisect import bisect_right
from dataclasses import dataclass
import re
from typing import Literal

from compiler.ast_nodes import SourceSpan


class SourceMap:
    """Map character offsets without normalizing LF, CRLF, or lone CR."""

    def __init__(self, source: str) -> None:
        self.source = source
        self._line_starts = [0, *(match.end() for match in re.finditer(r"\r\n|\r|\n", source))]

    def _position(self, offset: int) -> tuple[int, int]:
        line_index = bisect_right(self._line_starts, offset) - 1
        return line_index + 1, offset - self._line_starts[line_index] + 1

    def span(self, start: int, end: int) -> SourceSpan:
        if not 0 <= start <= end <= len(self.source):
            raise ValueError("Source offsets must be ordered and within the source")
        start_line, start_column = self._position(start)
        end_line, end_column = self._position(end)
        return SourceSpan(start_line, start_column, end_line, end_column, start, end)


@dataclass(frozen=True, slots=True)
class Diagnostic:
    stage: Literal["lexer", "parser", "semantic"]
    code: str
    message: str
    span: SourceSpan
    severity: Literal["error", "warning"] = "error"

    def format(self, filename: str = "<input>") -> str:
        return (
            f"{filename}:{self.span.start_line}:{self.span.start_column}: "
            f"{self.stage} {self.severity} [{self.code}]: {self.message}"
        )


class FrontendError(Exception):
    """A user-source error; no partial token stream/AST is returned."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(diagnostic.format())


class LexicalError(FrontendError):
    pass


class ParseError(FrontendError):
    pass


class SemanticError(FrontendError):
    pass

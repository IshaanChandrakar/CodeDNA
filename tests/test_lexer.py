"""Token values, longest matches, positions, and fail-fast lexical diagnostics."""

import pytest

from compiler.diagnostics import LexicalError
from compiler.lexer import KEYWORDS, UNSUPPORTED_KEYWORDS, build_lexer, format_tokens, tokenize


def test_full_program_tokens_and_typed_values():
    source = "int main(void) { int x = 12; x = x + 3; return x; }"
    records = tokenize(source)
    assert [record.type for record in records] == [
        "INT", "ID", "LPAREN", "VOID", "RPAREN", "LBRACE", "INT", "ID", "ASSIGN",
        "INTEGER", "SEMICOLON", "ID", "ASSIGN", "ID", "PLUS", "INTEGER", "SEMICOLON",
        "RETURN", "ID", "SEMICOLON", "RBRACE",
    ]
    assert records[1].value == "main"
    assert records[9].value == 12 and type(records[9].value) is int
    assert records[9].lexeme == "12"
    for record in records:
        assert source[record.span.start_offset:record.span.end_offset] == record.lexeme


@pytest.mark.parametrize("word,token_type", KEYWORDS.items())
def test_reserved_keywords(word, token_type):
    assert tokenize(word)[0].type == token_type
    assert tokenize(word + "_value")[0].type == "ID"


@pytest.mark.parametrize("word", ["Int", "main", "_name", "x12", "integer", "elsewhere"])
def test_identifiers_are_case_sensitive(word):
    assert [(token.type, token.value) for token in tokenize(word)] == [("ID", word)]


def test_operators_use_longest_match():
    source = "== != <= >= = < > + - * / % ( ) { } ;"
    assert [token.type for token in tokenize(source)] == [
        "EQ", "NE", "LE", "GE", "ASSIGN", "LT", "GT", "PLUS", "MINUS", "STAR",
        "SLASH", "PERCENT", "LPAREN", "RPAREN", "LBRACE", "RBRACE", "SEMICOLON",
    ]


@pytest.mark.parametrize("source", ["", " \t\f\v\n\r\n\r", "// comment", "/**/", "/* multi\nline */"])
def test_empty_and_comment_only_sources(source):
    assert tokenize(source) == []


def test_comments_do_not_consume_real_division_or_following_tokens():
    assert [token.value for token in tokenize("8/* stars ** / */ / 2 // done\n+ 1")] == [8, "/", 2, "+", 1]
    assert [token.value for token in tokenize("1/**/+/**/2")] == [1, "+", 2]


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_line_column_offsets_after_multiline_comments(newline):
    source = f" \tint/* a{newline}b */{newline}  x=10;"
    records = tokenize(source)
    assert (records[0].span.start_line, records[0].span.start_column) == (1, 3)
    identifier = records[1]
    assert (identifier.span.start_line, identifier.span.start_column) == (3, 3)
    assert (identifier.span.end_line, identifier.span.end_column) == (3, 4)
    assert identifier.span.start_offset == source.index("x")
    assert records[3].span.end_offset - records[3].span.start_offset == 2


def test_ply_token_line_numbers_match_source_spans():
    lexer = build_lexer("//a\r\n/*b\rc*/\n  return")
    token = lexer.token()
    assert token.lineno == token.span.start_line == 4
    assert token.span.start_column == 3
    assert lexer.token() is None


@pytest.mark.parametrize("character", ["@", "#", "&", "|", "!", "~", "?", ":", "[", "]", '"', "'", "é"])
def test_illegal_character_diagnostic(character):
    with pytest.raises(LexicalError) as caught:
        tokenize("\n  " + character)
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == "ILLEGAL_CHARACTER"
    assert diagnostic.stage == "lexer"
    assert (diagnostic.span.start_line, diagnostic.span.start_column) == (2, 3)
    assert diagnostic.span.end_offset - diagnostic.span.start_offset == 1
    assert "source.c:2:3: lexer error" in diagnostic.format("source.c")


@pytest.mark.parametrize("literal", ["00", "012", "0x10", "0XFF", "0b10", "1.5", "1e3", "123abc", "1u", "1L", "1_000"])
def test_malformed_or_unsupported_integer_literals(literal):
    with pytest.raises(LexicalError) as caught:
        tokenize(literal)
    assert caught.value.diagnostic.code == "INVALID_INTEGER_LITERAL"
    assert caught.value.diagnostic.span.end_offset == len(literal)


@pytest.mark.parametrize("literal", ["2147483648", "9999999999", "9" * 5000])
def test_out_of_range_literals_do_not_escape_as_python_conversion_errors(literal):
    with pytest.raises(LexicalError) as caught:
        tokenize(literal)
    assert caught.value.diagnostic.code == "INTEGER_OUT_OF_RANGE"


def test_literal_boundaries_and_separate_unary_sign():
    assert [token.value for token in tokenize("0 2147483647 -12")] == [0, 2147483647, "-", 12]


@pytest.mark.parametrize("operator", ["++", "--", "+=", "-=", "*=", "/=", "%=", "&&", "||", "<<", ">>", "<<=", ">>=", "&=", "|=", "^=", "->"])
def test_unsupported_operators_are_not_split_into_valid_tokens(operator):
    with pytest.raises(LexicalError) as caught:
        tokenize("x" + operator + "1")
    assert caught.value.diagnostic.code == "UNSUPPORTED_OPERATOR"
    assert caught.value.diagnostic.span.start_offset == 1
    assert caught.value.diagnostic.span.end_offset == 1 + len(operator)


@pytest.mark.parametrize("word", sorted(UNSUPPORTED_KEYWORDS))
def test_unsupported_c_keywords_cannot_be_used_as_identifiers(word):
    with pytest.raises(LexicalError) as caught:
        tokenize(word)
    assert caught.value.diagnostic.code == "UNSUPPORTED_KEYWORD"


def test_unterminated_comment_points_to_opening_and_reaches_eof():
    source = "int\n /* unfinished\n"
    with pytest.raises(LexicalError) as caught:
        tokenize(source)
    span = caught.value.diagnostic.span
    assert caught.value.diagnostic.code == "UNTERMINATED_COMMENT"
    assert (span.start_line, span.start_column) == (2, 2)
    assert (span.end_line, span.end_column) == (3, 1)
    assert span.end_offset == len(source)


def test_reusable_lexer_resets_after_success_and_failure():
    lexer = build_lexer("\nint")
    assert lexer.token().lineno == 2
    lexer.input("@")
    with pytest.raises(LexicalError):
        lexer.token()
    lexer.input("return 1;")
    assert lexer.token().lineno == 1
    assert lexer.token().value == 1
    assert lexer.token().type == "SEMICOLON"
    assert lexer.token() is None


def test_debug_display_contains_actual_values_and_positions():
    assert format_tokens(tokenize("int x=12;")) == (
        "1:1 INT 'int'\n1:5 ID 'x'\n1:6 ASSIGN '='\n1:7 INTEGER 12\n1:9 SEMICOLON ';'"
    )

"""Lexer unit tests: token kinds, literals, comments, spans, lexical errors."""

from __future__ import annotations

import pytest

from forgecompile.diagnostics import SourceFile
from forgecompile.frontend.lexer import tokenize
from forgecompile.frontend.tokens import Token, TokenKind

K = TokenKind


def lex(text: str) -> list[Token]:
    tokens, errors = tokenize(SourceFile("<test>", text))
    assert errors == [], [e.message for e in errors]
    return tokens


def kinds(text: str) -> list[TokenKind]:
    return [t.kind for t in lex(text)][:-1]  # drop EOF


def lex_errors(text: str) -> list[str]:
    _, errors = tokenize(SourceFile("<test>", text))
    return [e.message for e in errors]


def test_empty_input_is_just_eof() -> None:
    tokens = lex("")
    assert [t.kind for t in tokens] == [K.EOF]


def test_keywords_vs_identifiers() -> None:
    assert kinds("fn let if else while for in return break continue true false as") == [
        K.FN, K.LET, K.IF, K.ELSE, K.WHILE, K.FOR, K.IN, K.RETURN,
        K.BREAK, K.CONTINUE, K.TRUE, K.FALSE, K.AS,
    ]  # fmt: skip
    assert kinds("int float bool") == [K.INT_TYPE, K.FLOAT_TYPE, K.BOOL_TYPE]
    # Keywords embedded in longer names are identifiers.
    assert kinds("iffy fn_name _x lettuce x1") == [K.IDENT] * 5


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<= < >= > == = != !", [K.LE, K.LT, K.GE, K.GT, K.EQ, K.ASSIGN, K.NE, K.NOT]),
        ("&& || -> - ..", [K.AND, K.OR, K.ARROW, K.MINUS, K.DOTDOT]),
        ("+-*/%", [K.PLUS, K.MINUS, K.STAR, K.SLASH, K.PERCENT]),
        ("(){}[],;:", [K.LPAREN, K.RPAREN, K.LBRACE, K.RBRACE, K.LBRACKET, K.RBRACKET,
                       K.COMMA, K.SEMICOLON, K.COLON]),
        # Maximal munch: "<==" is "<=" then "=".
        ("<==", [K.LE, K.ASSIGN]),
        ("a-->b", [K.IDENT, K.MINUS, K.ARROW, K.IDENT]),
    ],
)  # fmt: skip
def test_operators_maximal_munch(text: str, expected: list[TokenKind]) -> None:
    assert kinds(text) == expected


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("0", K.INT, 0),
        ("42", K.INT, 42),
        ("9223372036854775807", K.INT, 2**63 - 1),
        ("1.5", K.FLOAT, 1.5),
        ("0.25", K.FLOAT, 0.25),
        ("1e3", K.FLOAT, 1000.0),
        ("2.5E-2", K.FLOAT, 0.025),
        ("7e+1", K.FLOAT, 70.0),
    ],
)
def test_number_literals(text: str, kind: TokenKind, value: float) -> None:
    token = lex(text)[0]
    assert token.kind is kind
    assert token.value == value
    assert type(token.value) is (int if kind is K.INT else float)


def test_range_is_not_a_float() -> None:
    """`0..10` must lex as INT DOTDOT INT, not FLOAT(0.) DOT ..."""
    assert kinds("0..10") == [K.INT, K.DOTDOT, K.INT]


def test_dangling_exponent_is_not_consumed() -> None:
    # "1e" is INT 1 followed by identifier "e"; the exponent needs digits.
    assert kinds("1e") == [K.INT, K.IDENT]


def test_comments_are_skipped() -> None:
    text = """
    // line comment with symbols: fn let && ||
    let /* inline */ x /* multi
    line */ = 1; // trailing
    """
    assert kinds(text) == [K.LET, K.IDENT, K.ASSIGN, K.INT, K.SEMICOLON]


def test_spans_track_lines_and_columns() -> None:
    tokens = lex("fn main() {\n    return 10;\n}")
    ret = next(t for t in tokens if t.kind is K.RETURN)
    assert (ret.span.line, ret.span.column) == (2, 5)
    ten = next(t for t in tokens if t.kind is K.INT)
    assert (ten.span.line, ten.span.column) == (2, 12)
    assert ten.span.end - ten.span.start == 2
    eof = tokens[-1]
    assert eof.kind is K.EOF and eof.span.line == 3


def test_crlf_line_endings() -> None:
    tokens = lex("let x = 1;\r\nlet y = 2;\r\n")
    second_let = [t for t in tokens if t.kind is K.LET][1]
    assert (second_let.span.line, second_let.span.column) == (2, 1)


def test_unexpected_character_reports_and_continues() -> None:
    tokens, errors = tokenize(SourceFile("<t>", "let x = 1 @ 2; $"))
    assert [e.message for e in errors] == ["unexpected character '@'", "unexpected character '$'"]
    assert errors[0].span is not None and errors[0].span.column == 11
    # Lexing continued past the bad characters.
    assert K.SEMICOLON in [t.kind for t in tokens]


def test_single_ampersand_suggests_double_and_recovers() -> None:
    tokens, errors = tokenize(SourceFile("<t>", "a & b | c"))
    assert len(errors) == 2
    assert errors[0].notes == ("did you mean '&&'?",)
    assert errors[1].notes == ("did you mean '||'?",)
    # Recovery: the intended logical operators are still emitted.
    assert [t.kind for t in tokens][:-1] == [K.IDENT, K.AND, K.IDENT, K.OR, K.IDENT]


def test_integer_literal_overflow() -> None:
    assert lex_errors("9223372036854775808") == [
        "integer literal 9223372036854775808 does not fit in a 64-bit int"
    ]


def test_unterminated_block_comment() -> None:
    assert lex_errors("let x /* never closed") == ["unterminated block comment"]


def test_unicode_digits_and_letters_are_rejected() -> None:
    # str.isdigit() accepts '²' and str.isalpha() accepts 'é'; the lexer must not.
    assert lex_errors("x²") == ["unexpected character '²'"]
    assert lex_errors("café") == ["unexpected character 'é'"]


def test_lone_dot_is_an_error() -> None:
    assert lex_errors("1.x") == ["unexpected character '.'"]

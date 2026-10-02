"""Syntax error reporting: messages, locations, and multi-error recovery."""

from __future__ import annotations

import pytest

from forgecompile.diagnostics import CompileError, Diagnostic, SourceFile, render
from forgecompile.frontend import parse_source


def errors_of(text: str) -> list[Diagnostic]:
    with pytest.raises(CompileError) as excinfo:
        parse_source(text, "t.mini")
    return excinfo.value.diagnostics


def messages(text: str) -> list[str]:
    return [d.message for d in errors_of(text)]


def wrap(body: str) -> str:
    return f"fn main() {{\n{body}\n}}\n"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("let x = 5", "expected ';' after variable declaration, found '}'"),
        ("x = ;", "expected an expression, found ';'"),
        ("let = 4;", "expected identifier after 'let', found '='"),
        ("let x;", "variable 'x' needs a type annotation or an initializer"),
        ("let x: string = 1;", "expected a type, found identifier 'string'"),
        ("let a: [int; 0];", "array size must be positive"),
        ("let a: [int; n];", "expected integer literal for array size, found identifier 'n'"),
        ("let a: [int 3];", "expected ';' between array element type and size, found integer literal '3'"),
        ("f(1, 2;", "expected ')' to close the argument list, found ';'"),
        ("x = a[1;", "expected ']' to close the index, found ';'"),
        ("x = (1 + 2;", "expected ')' to close the parenthesized expression, found ';'"),
        ("1 + 2 = x;", "invalid assignment target"),
        ("f(x) = 3;", "invalid assignment target"),
        ("for i 0..10 { }", "expected 'in' after loop variable, found integer literal '0'"),
        ("for i in 0, 10 { }", "expected '..' in range (write 'start..end'), found ','"),
        ("while x < 3 x = 1;", "expected '{' to start a block, found identifier 'x'"),
        ("if x { } else return;", "expected '{' to start a block, found 'return'"),
        ("break", "expected ';' after 'break', found '}'"),
        ("return 1 2;", "expected ';' after return statement, found integer literal '2'"),
    ],
)  # fmt: skip
def test_single_error_messages(body: str, expected: str) -> None:
    assert messages(wrap(body)) == [expected]


def test_missing_semicolon_points_after_previous_token() -> None:
    (diag,) = errors_of("fn main() {\n    let x = 5\n}\n")
    assert diag.span is not None
    assert (diag.span.line, diag.span.column) == (2, 14)


def test_top_level_statement() -> None:
    assert messages("let x = 1;") == ["expected 'fn' at top level, found 'let'"]


def test_keyword_as_name_has_hint_and_no_cascade() -> None:
    (diag,) = errors_of(wrap("let while = 1;"))
    assert diag.notes == ("'while' is a reserved keyword",)


def test_multiple_errors_are_reported_in_one_run() -> None:
    source = wrap("let a = 1\nlet b = ;\nif x < y < z { }\nreturn 0;")
    assert messages(source) == [
        "expected ';' after variable declaration, found 'let'",
        "expected an expression, found ';'",
        "comparison operators cannot be chained",
    ]


def test_recovery_skips_nested_braces_in_broken_statement() -> None:
    """Regression test for F-002: the '}' of a skipped `{ }` must not close the function."""
    source = wrap("if a < b < c { x = 1; }\nlet let = 2;")
    assert messages(source) == [
        "comparison operators cannot be chained",
        "expected identifier after 'let', found 'let'",
    ]


def test_error_in_one_function_does_not_hide_the_next() -> None:
    source = "fn broken( {\n}\nfn fine() { let x = ; }\n"
    assert messages(source) == [
        "expected identifier for parameter name, found '{'",
        "expected an expression, found ';'",
    ]


def test_missing_closing_brace_before_next_function() -> None:
    source = "fn a() {\n    let x = 1;\n\nfn b() { let y = ; }\n"
    msgs = messages(source)
    assert msgs[0] == "expected '}' to close the block, found 'fn'"
    assert "expected an expression, found ';'" in msgs  # fn b still parsed


def test_lexer_and_parser_errors_are_merged_in_source_order() -> None:
    diagnostics = errors_of(wrap("let x = 1 @ 2;\nlet = 3;"))
    msgs = [d.message for d in diagnostics]
    assert "unexpected character '@'" in msgs
    assert "expected identifier after 'let', found '='" in msgs
    offsets = [d.span.start for d in diagnostics if d.span is not None]
    assert offsets == sorted(offsets)


def test_rendered_diagnostic_shows_source_line_and_caret() -> None:
    text = wrap("let x = 5")
    (diag,) = errors_of(text)
    rendered = render(diag, SourceFile("t.mini", text))
    assert rendered.splitlines() == [
        "error: expected ';' after variable declaration, found '}'",
        "  --> t.mini:2:10",
        "  |",
        "2 | let x = 5",
        "  |          ^",
    ]

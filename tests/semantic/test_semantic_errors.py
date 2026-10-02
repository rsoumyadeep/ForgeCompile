"""Negative tests: every semantic diagnostic, with its exact message.

Each case is a complete program with exactly one semantic error, so a test
also proves that the checker does not produce cascading errors.
"""

from __future__ import annotations

import pytest

from forgecompile.diagnostics import CompileError, Diagnostic
from forgecompile.driver import check_source


def diagnostics_of(source: str) -> list[Diagnostic]:
    with pytest.raises(CompileError) as excinfo:
        check_source(source)
    return excinfo.value.diagnostics


def single_error(source: str) -> Diagnostic:
    diagnostics = diagnostics_of(source)
    assert len(diagnostics) == 1, [d.message for d in diagnostics]
    return diagnostics[0]


def in_main(body: str, extra: str = "") -> str:
    return f"{extra}\nfn main() -> int {{\n{body}\nreturn 0;\n}}\n"


# ----------------------------------------------------------------------------- program level

PROGRAM_CASES = [
    ("fn print(x: int) {}\nfn main() {}", "'print' is a built-in function and cannot be redefined"),
    ("fn f() {}\nfn f() {}\nfn main() {}", "function 'f' is already defined"),
    ("fn helper() {}", "program has no 'main' function"),
    ("fn main(argc: int) {}", "'main' must not take parameters"),
    ("fn main() -> float { return 1.0; }", "'main' must return int or nothing, not float"),
    ("fn f(a: int, a: int) {}\nfn main() {}", "'a' is already declared in this scope"),
    ("fn f(n: int) { let n = 2; }\nfn main() {}", "'n' is already declared in this scope"),
    (
        "fn f(n: int) -> int { if n > 0 { return 1; } }\nfn main() {}",
        "function 'f' may reach the end of its body without returning a value",
    ),
    (
        "fn f() -> int { while true { break; } }\nfn main() {}",
        "function 'f' may reach the end of its body without returning a value",
    ),
]


@pytest.mark.parametrize(("source", "message"), PROGRAM_CASES)
def test_program_level_errors(source: str, message: str) -> None:
    assert single_error(source).message == message


# ----------------------------------------------------------------------------- statements

STATEMENT_CASES = [
    # declarations and scoping
    ("let x = 1; let x = 2;", "'x' is already declared in this scope"),
    ("let total: float = 1;", "mismatched types: 'total' is declared as float but initialized with int"),
    ("let a: [int; 3] = [1, 2];", "mismatched types: 'a' is declared as [int; 3] but initialized with [int; 2]"),
    ("let a: [int; 2]; let b = a;", "arrays cannot be copied"),
    ("let a: [int; 2]; let b: [int; 2] = a;", "arrays cannot be copied"),
    ("let r = print(1);", "'print' does not return a value"),
    # assignment
    ("for i in 0..3 { i = 5; }", "cannot assign to loop variable 'i'"),
    ("let a: [int; 2]; let b: [int; 2]; a = b;", "cannot assign to an entire array"),
    ("let m: [[int; 2]; 2]; let r: [int; 2]; m[0] = r;", "cannot assign to an entire array"),
    ("let x = 1; x = 2.0;", "mismatched types: cannot assign float to int"),
    ("let b = true; b = 1;", "mismatched types: cannot assign int to bool"),
    # control flow
    ("if 1 { }", "'if' condition must be bool, found int"),
    ("while 2.5 { }", "'while' condition must be bool, found float"),
    ("for i in 0.0..3 { }", "range start must be int, found float"),
    ("for i in 0..true { }", "range end must be int, found bool"),
    ("break;", "'break' outside of a loop"),
    ("continue;", "'continue' outside of a loop"),
    ("return;", "function 'main' must return a value of type int"),
    ("return 1.5;", "mismatched types: function 'main' returns int, found float"),
    # expression statements
    ("1 + 2;", "expression result is unused"),
]  # fmt: skip


@pytest.mark.parametrize(("body", "message"), STATEMENT_CASES)
def test_statement_errors(body: str, message: str) -> None:
    assert single_error(in_main(body)).message == message


def test_return_value_from_void_function() -> None:
    error = single_error("fn f() { return 1; }\nfn main() {}")
    assert error.message == "function 'f' does not return a value"


# ----------------------------------------------------------------------------- expressions

EXPRESSION_CASES = [
    # names
    ("let y = undefined_thing;", "undefined variable 'undefined_thing'"),
    ("let y = helper;", "'helper' is a function, not a variable"),
    ("let y = print;", "'print' is a function, not a variable"),
    # operators
    ("let y = -true;", "operator '-' cannot be applied to bool"),
    ("let y = !5;", "operator '!' cannot be applied to int"),
    ("let y = 1 && true;", "operator '&&' requires bool operands, found int and bool"),
    ("let y = 1 + 2.0;", "operator '+' cannot be applied to int and float"),
    ("let y = true < false;", "operator '<' cannot be applied to bool and bool"),
    ("let y = 1 == 1.0;", "operator '==' cannot be applied to int and float"),
    ("let a: [int; 2]; let b: [int; 2]; let y = a == b;", "operator '==' cannot be applied to [int; 2] and [int; 2]"),
    ("let y = (1 + true) * 2;", "operator '+' cannot be applied to int and bool"),  # reported once
    # casts
    ("let a: [int; 2]; let y = a as int;", "cannot cast [int; 2] to int"),
    # indexing
    ("let a: [int; 2]; let y = a[1.0];", "array index must be int, found float"),
    ("let x = 1; let y = x[0];", "cannot index into a value of type int"),
    ("let a: [int; 2]; let y = a[2];", "index 2 is out of bounds for an array of length 2"),
    ("let a: [int; 2]; let y = a[-1];", "index -1 is out of bounds for an array of length 2"),
    # calls
    ("let x = 1; x(2);", "'x' is a variable, not a function"),
    ("helpr(1);", "undefined function 'helpr'"),
    ("helper(1, 2);", "function 'helper' takes 1 argument, but 2 were given"),
    ("helper(true);", "argument 1 of 'helper' has type bool, expected int"),
    ("let a: [int; 3]; takes_array(a);", "argument 1 of 'takes_array' has type [int; 3], expected [int; 2]"),
    ("print(1, 2);", "'print' takes exactly 1 argument, but 2 were given"),
    ("let a: [int; 2]; print(a);", "'print' cannot print a value of type [int; 2]"),
    ("let y = noop() + 1;", "'noop' does not return a value"),
    # array literals
    ("helper([1, 2]);", "array literals are only allowed as 'let' initializers"),
    ("let a: [int; 2]; a[0] = [1][0];", "array literals are only allowed as 'let' initializers"),
    ("let a: [int; 1] = [];", "empty array literal"),
    ("let a = [1, 2.0];", "array elements must all have the same type: expected int, found float"),
]  # fmt: skip

HELPERS = """
fn helper(n: int) -> int { return n; }
fn takes_array(a: [int; 2]) {}
fn noop() {}
"""


@pytest.mark.parametrize(("body", "message"), EXPRESSION_CASES)
def test_expression_errors(body: str, message: str) -> None:
    assert single_error(in_main(body, HELPERS)).message == message


# ----------------------------------------------------------------------------- notes and recovery


def test_did_you_mean_for_variables_and_functions() -> None:
    error = single_error(in_main("let count = 1; print(cuont);"))
    assert error.notes == ("did you mean 'count'?",)
    error = single_error(in_main("helpr(1);", HELPERS))
    assert error.notes == ("did you mean 'helper'?",)


def test_numeric_mismatch_explains_explicit_conversion() -> None:
    error = single_error(in_main("let y = 1 + 2.0;"))
    assert "convert explicitly with 'as'" in error.notes[0]


def test_redeclaration_points_to_previous_declaration() -> None:
    error = single_error(in_main("let x = 1;\nlet x = 2;"))
    assert error.notes and "previous declaration as local variable at line" in error.notes[0]


def test_many_independent_errors_reported_together() -> None:
    source = in_main(
        """
        let a: float = 1;
        let b = c;
        if 3 { }
        break;
        """
    )
    assert [d.message for d in diagnostics_of(source)] == [
        "mismatched types: 'a' is declared as float but initialized with int",
        "undefined variable 'c'",
        "'if' condition must be bool, found int",
        "'break' outside of a loop",
    ]


def test_use_of_undefined_variable_does_not_cascade() -> None:
    # `y` gets the error type; its later uses must not produce more errors.
    source = in_main("let y = nope; let z = y + 1; print(z * 2);")
    assert [d.message for d in diagnostics_of(source)] == ["undefined variable 'nope'"]


def test_out_of_scope_variable() -> None:
    error = single_error(in_main("{ let inner = 1; } print(inner);"))
    assert error.message == "undefined variable 'inner'"


def test_loop_variable_not_visible_after_loop() -> None:
    error = single_error(in_main("for i in 0..3 { } print(i);"))
    assert error.message == "undefined variable 'i'"

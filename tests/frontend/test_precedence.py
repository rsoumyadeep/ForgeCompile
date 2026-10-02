"""Operator precedence and associativity, checked via S-expressions."""

from __future__ import annotations

import pytest

from forgecompile.ast import nodes as ast
from forgecompile.ast.dump import sexpr
from forgecompile.diagnostics import CompileError
from forgecompile.frontend import parse_source


def parse_expr(text: str) -> ast.Expr:
    program = parse_source(f"fn main() {{ {text}; }}")
    stmt = program.functions[0].body.statements[0]
    assert isinstance(stmt, ast.ExprStmt)
    return stmt.expr


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # multiplicative binds tighter than additive
        ("1 + 2 * 3", "(+ 1 (* 2 3))"),
        ("1 * 2 + 3", "(+ (* 1 2) 3)"),
        ("a % b - c / d", "(- (% a b) (/ c d))"),
        # left associativity
        ("a - b - c", "(- (- a b) c)"),
        ("a / b / c", "(/ (/ a b) c)"),
        ("a - b + c", "(+ (- a b) c)"),
        # parentheses override
        ("a - (b - c)", "(- a (- b c))"),
        ("(1 + 2) * 3", "(* (+ 1 2) 3)"),
        # comparison < arithmetic, equality < comparison
        ("a + 1 < b * 2", "(< (+ a 1) (* b 2))"),
        ("a < b == c > d", "(== (< a b) (> c d))"),
        # logical operators: && tighter than ||
        ("a || b && c", "(|| a (&& b c))"),
        ("a && b || c && d", "(|| (&& a b) (&& c d))"),
        ("a == 1 || b != 2 && c", "(|| (== a 1) (&& (!= b 2) c))"),
        # unary binds tighter than binary, looser than postfix
        ("-a * b", "(* (- a) b)"),
        ("-a[0]", "(- (index a 0))"),
        ("!a && b", "(&& (! a) b)"),
        ("!!a", "(! (! a))"),
        ("- -a", "(- (- a))"),
        ("--a", "(- (- a))"),
        # cast: tighter than binary, looser than unary
        ("a * b as float", "(* a (as b float))"),
        ("-a as float", "(as (- a) float)"),
        ("(a + b) as float", "(as (+ a b) float)"),
        ("a as float < b", "(< (as a float) b)"),
        # postfix chains
        ("m[i][j] + f(x)[0]", "(+ (index (index m i) j) (index (call f x) 0))"),
        # deeply nested
        ("((a + b) * (c - d)) / -(e % f)", "(/ (* (+ a b) (- c d)) (- (% e f)))"),
    ],
)
def test_precedence(source: str, expected: str) -> None:
    assert sexpr(parse_expr(source)) == expected


@pytest.mark.parametrize("source", ["a < b < c", "a == b == c", "a <= b > c", "a != b == c"])
def test_chained_comparisons_are_rejected(source: str) -> None:
    with pytest.raises(CompileError) as excinfo:
        parse_expr(source)
    assert excinfo.value.diagnostics[0].message == "comparison operators cannot be chained"


def test_parenthesized_comparison_chain_is_allowed() -> None:
    # Syntactically fine (it is a type error, reported in Phase 2).
    assert sexpr(parse_expr("(a < b) == c")) == "(== (< a b) c)"


def test_deep_nesting_does_not_overflow() -> None:
    depth = 200
    expr = parse_expr("(" * depth + "1" + ")" * depth + " + " + " + ".join(["x"] * 500))
    assert isinstance(expr, ast.Binary)

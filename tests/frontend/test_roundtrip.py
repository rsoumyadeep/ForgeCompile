"""Round-trip property: parse(format(ast)) == ast.

Two kinds of inputs:

1. The example programs: parse -> format -> parse must give an equal AST, and
   formatting must be idempotent (format(parse(format(x))) == format(x)).
2. Randomly generated expression trees (seeded, reproducible): format -> parse
   must reconstruct the exact tree. This checks that formatter and parser agree
   on every precedence/associativity combination, including ones nobody
   thought to write a test for.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from forgecompile.ast import nodes as ast
from forgecompile.ast.formatter import format_expr, format_program
from forgecompile.ast.operators import BinaryOp, UnaryOp
from forgecompile.ast.types import BOOL, FLOAT, INT, ArrayType
from forgecompile.diagnostics import Span
from forgecompile.frontend import parse_source

EXAMPLES = sorted((Path(__file__).parents[2] / "examples").glob("*.mini"))
NO_SPAN = Span(0, 0, 1, 1)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_round_trip(path: Path) -> None:
    original = parse_source(path.read_text("utf-8"))
    formatted = format_program(original)
    reparsed = parse_source(formatted)
    assert reparsed == original
    assert format_program(reparsed) == formatted  # idempotent


# --------------------------------------------------------------------------- random trees


def random_expr(rng: random.Random, depth: int) -> ast.Expr:
    if depth == 0 or rng.random() < 0.2:
        choice = rng.randrange(4)
        if choice == 0:
            return ast.IntLiteral(rng.randrange(1000), span=NO_SPAN)
        if choice == 1:
            return ast.FloatLiteral(rng.choice([0.5, 1.0, 2.25, 1e-07, 3e20]), span=NO_SPAN)
        if choice == 2:
            return ast.BoolLiteral(rng.random() < 0.5, span=NO_SPAN)
        return ast.Name(rng.choice(["a", "b", "x", "count"]), span=NO_SPAN)

    kind = rng.randrange(10)
    if kind < 5:
        op = rng.choice(list(BinaryOp))
        left = random_expr(rng, depth - 1)
        right = random_expr(rng, depth - 1)
        # Comparisons are non-associative: the parser rejects `a < b < c` but
        # the formatter adds parentheses, so any tree is still representable.
        return ast.Binary(op, left, right, span=NO_SPAN)
    if kind == 5:
        return ast.Unary(rng.choice(list(UnaryOp)), random_expr(rng, depth - 1), span=NO_SPAN)
    if kind == 6:
        return ast.Cast(random_expr(rng, depth - 1), rng.choice([INT, FLOAT, BOOL]), span=NO_SPAN)
    if kind == 7:
        return ast.Index(random_expr(rng, depth - 1), random_expr(rng, depth - 1), span=NO_SPAN)
    if kind == 8:
        args = [random_expr(rng, depth - 1) for _ in range(rng.randrange(3))]
        return ast.Call(rng.choice(["f", "g"]), args, span=NO_SPAN)
    elements = [random_expr(rng, depth - 1) for _ in range(rng.randrange(1, 3))]
    return ast.ArrayLiteral(elements, span=NO_SPAN)


def parse_expr(text: str) -> ast.Expr:
    stmt = parse_source(f"fn main() {{ {text}; }}").functions[0].body.statements[0]
    assert isinstance(stmt, ast.ExprStmt)
    return stmt.expr


@pytest.mark.parametrize("seed", range(20))
def test_random_expressions_round_trip(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(50):
        tree = random_expr(rng, depth=5)
        text = format_expr(tree)
        assert parse_expr(text) == tree, text


def test_formatter_uses_minimal_parentheses() -> None:
    cases = {
        "a - (b - c)": "a - (b - c)",
        "(a - b) - c": "a - b - c",
        "(a * b) + c": "a * b + c",
        "a * (b + c)": "a * (b + c)",
        "-(a)": "-a",
        "-(a + b)": "-(a + b)",
        "(-a) as float": "-a as float",
        "-(a as float)": "-(a as float)",
        # `<` binds tighter than `==`, so these parentheses are redundant...
        "(a < b) == c": "a < b == c",
        # ...but chaining the *same* non-associative level needs them (F-003).
        "(a != b) != c": "(a != b) != c",
        "a || (b && c)": "a || b && c",
        "(a || b) && c": "(a || b) && c",
    }
    for source, expected in cases.items():
        assert format_expr(parse_expr(source)) == expected


def test_array_type_formatting() -> None:
    program = parse_source("fn f(m: [[float; 2]; 3]) -> int { let b: [bool; 4]; return 0; }")
    assert program.functions[0].params[0].type == ArrayType(ArrayType(FLOAT, 2), 3)
    assert "fn f(m: [[float; 2]; 3]) -> int {" in format_program(program)

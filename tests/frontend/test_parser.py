"""Parser tests on valid programs: statements, functions, loops, arrays, desugaring."""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecompile.ast import nodes as ast
from forgecompile.ast.dump import sexpr
from forgecompile.ast.operators import BinaryOp
from forgecompile.ast.types import BOOL, FLOAT, INT, VOID, ArrayType
from forgecompile.frontend import parse_source

EXAMPLES = sorted((Path(__file__).parents[2] / "examples").glob("*.mini"))


def parse_body(body: str) -> list[ast.Stmt]:
    """Parse statements wrapped in `fn main() { ... }`."""
    program = parse_source(f"fn main() {{\n{body}\n}}")
    return program.functions[0].body.statements


def parse_expr(text: str) -> ast.Expr:
    (stmt,) = parse_body(f"{text};")
    assert isinstance(stmt, ast.ExprStmt)
    return stmt.expr


def test_empty_program() -> None:
    assert parse_source("").functions == []


def test_function_signatures() -> None:
    program = parse_source(
        """
        fn nothing() {}
        fn add(a: int, b: float,) -> float { return b; }
        fn grid(m: [[bool; 3]; 4]) -> bool { return m[0][0]; }
        """
    )
    nothing, add, grid = program.functions
    assert nothing.name == "nothing" and nothing.params == [] and nothing.return_type == VOID
    assert [(p.name, p.type) for p in add.params] == [("a", INT), ("b", FLOAT)]
    assert add.return_type == FLOAT
    assert grid.params[0].type == ArrayType(ArrayType(BOOL, 3), 4)


def test_let_forms() -> None:
    a, b, c, d = parse_body(
        "let a = 1; let b: float; let c: bool = true; let d: [int; 3] = [1, 2, 3];"
    )
    assert a == ast.LetStmt("a", None, ast.IntLiteral(1, span=a.span), span=a.span)
    assert isinstance(b, ast.LetStmt) and b.declared_type == FLOAT and b.init is None
    assert isinstance(c, ast.LetStmt) and c.declared_type == BOOL
    assert isinstance(d, ast.LetStmt) and isinstance(d.init, ast.ArrayLiteral)
    assert len(d.init.elements) == 3


def test_assignment_targets() -> None:
    first, second = parse_body("x = 1; grid[i][j + 1] = 2;")
    assert isinstance(first, ast.AssignStmt) and isinstance(first.target, ast.Name)
    assert isinstance(second, ast.AssignStmt)
    assert sexpr(second.target) == "(index (index grid i) (+ j 1))"


def test_if_else_if_chain_is_desugared() -> None:
    (stmt,) = parse_body("if a { x = 1; } else if b { x = 2; } else { x = 3; }")
    assert isinstance(stmt, ast.IfStmt)
    assert stmt.else_body is not None
    (nested,) = stmt.else_body.statements
    assert isinstance(nested, ast.IfStmt)
    assert sexpr(nested.condition) == "b"
    assert nested.else_body is not None and len(nested.else_body.statements) == 1


def test_if_without_else() -> None:
    (stmt,) = parse_body("if x < 3 { return; }")
    assert isinstance(stmt, ast.IfStmt) and stmt.else_body is None


def test_loops() -> None:
    w, f = parse_body("while i < n { i = i + 1; break; } for k in 0..n * 2 { continue; }")
    assert isinstance(w, ast.WhileStmt)
    assert isinstance(w.body.statements[1], ast.BreakStmt)
    assert isinstance(f, ast.ForStmt)
    assert f.var == "k"
    assert sexpr(f.start) == "0" and sexpr(f.end) == "(* n 2)"
    assert isinstance(f.body.statements[0], ast.ContinueStmt)


def test_nested_blocks_and_return_forms() -> None:
    outer, ret_value, ret_void = parse_body("{ { let x = 1; } } return 1 + 2; return;")
    assert isinstance(outer, ast.Block)
    assert isinstance(outer.statements[0], ast.Block)
    assert isinstance(ret_value, ast.ReturnStmt) and ret_value.value is not None
    assert isinstance(ret_void, ast.ReturnStmt) and ret_void.value is None


def test_calls() -> None:
    expr = parse_expr("f(1, g(x), a[2],)")
    assert sexpr(expr) == "(call f 1 (call g x) (index a 2))"
    assert sexpr(parse_expr("h()")) == "(call h)"


def test_casts() -> None:
    assert sexpr(parse_expr("x as float")) == "(as x float)"
    assert sexpr(parse_expr("x as float as int")) == "(as (as x float) int)"


def test_nested_parentheses_are_transparent() -> None:
    assert parse_expr("(((1 + 2)))") == parse_expr("1 + 2")


def test_spans_cover_whole_constructs() -> None:
    program = parse_source("fn main() {\n    let total = a + b * c;\n}")
    let = program.functions[0].body.statements[0]
    assert isinstance(let, ast.LetStmt) and let.init is not None
    assert (let.span.line, let.span.column) == (2, 5)
    assert let.init.span.end - let.init.span.start == len("a + b * c")
    assert isinstance(let.init, ast.Binary) and let.init.op is BinaryOp.ADD


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_parse(path: Path) -> None:
    program = parse_source(path.read_text("utf-8"), str(path))
    assert any(fn.name == "main" for fn in program.functions)

"""Positive semantic tests: type annotation, name resolution, scoping, accepted programs."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest

from forgecompile.ast import nodes as ast
from forgecompile.ast.types import BOOL, ERROR, FLOAT, INT, VOID, ArrayType
from forgecompile.driver import CheckedProgram, check_source
from forgecompile.semantic.symbols import VariableKind

EXAMPLES = sorted((Path(__file__).parents[2] / "examples").glob("*.mini"))


def walk(node: ast.Node) -> Iterator[ast.Node]:
    yield node
    for f in dataclasses.fields(node):
        if not f.compare:
            continue
        value = getattr(node, f.name)
        if isinstance(value, ast.Node):
            yield from walk(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, ast.Node):
                    yield from walk(item)


def names_called(checked: CheckedProgram, ident: str) -> list[ast.Name]:
    return [n for n in walk(checked.ast) if isinstance(n, ast.Name) and n.ident == ident]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_type_check_and_every_expression_is_annotated(path: Path) -> None:
    checked = check_source(path.read_text("utf-8"), str(path))
    for node in walk(checked.ast):
        if isinstance(node, ast.Expr):
            assert node.ty is not None and node.ty != ERROR, node
        if isinstance(node, ast.Name):
            assert node.symbol is not None
        if isinstance(node, ast.Call):
            assert node.function is not None


def test_expression_types() -> None:
    checked = check_source(
        """
        fn main() -> int {
            let i = 1 + 2 * 3;
            let f = 1.5 / 2.0;
            let b = i < 3 && !(f >= 0.5);
            let c = i as float + f;
            let m: [[float; 2]; 3];
            let row_elem = m[2][1];
            return i % 2;
        }
        """
    )
    lets = {
        s.name: s for s in checked.ast.functions[0].body.statements if isinstance(s, ast.LetStmt)
    }
    assert lets["i"].symbol is not None and lets["i"].symbol.type == INT
    assert lets["f"].symbol is not None and lets["f"].symbol.type == FLOAT
    assert lets["b"].symbol is not None and lets["b"].symbol.type == BOOL
    assert lets["c"].symbol is not None and lets["c"].symbol.type == FLOAT
    assert lets["m"].symbol is not None
    assert lets["m"].symbol.type == ArrayType(ArrayType(FLOAT, 2), 3)
    row_elem = lets["row_elem"]
    assert row_elem.init is not None and isinstance(row_elem.init, ast.Index)
    assert row_elem.init.ty == FLOAT
    assert isinstance(row_elem.init.base, ast.Index)
    assert row_elem.init.base.ty == ArrayType(FLOAT, 2)


def test_shadowing_creates_distinct_symbols() -> None:
    checked = check_source(
        """
        fn main() {
            let x = 1;
            {
                let x = 2.5;
                print(x);
            }
            print(x);
        }
        """
    )
    inner_use, outer_use = names_called(checked, "x")
    assert inner_use.symbol is not None and outer_use.symbol is not None
    assert inner_use.symbol is not outer_use.symbol
    assert inner_use.symbol.uid != outer_use.symbol.uid
    assert (inner_use.ty, outer_use.ty) == (FLOAT, INT)


def test_let_initializer_sees_outer_binding() -> None:
    checked = check_source("fn main() { let x = 1; { let x = x + 1; print(x); } }")
    init_use, print_use = names_called(checked, "x")
    assert init_use.symbol is not None and print_use.symbol is not None
    assert init_use.symbol is not print_use.symbol  # `x + 1` refers to the outer x


def test_forward_calls_and_mutual_recursion() -> None:
    check_source(
        """
        fn main() -> int { return is_even(10) as int; }
        fn is_even(n: int) -> bool { if n == 0 { return true; } return is_odd(n - 1); }
        fn is_odd(n: int) -> bool { if n == 0 { return false; } return is_even(n - 1); }
        """
    )


def test_arrays_by_reference_including_rows() -> None:
    checked = check_source(
        """
        fn fill(row: [float; 3], value: float) { for i in 0..3 { row[i] = value; } }
        fn main() { let m: [[float; 3]; 2]; fill(m[1], 2.0); print(m[1][0]); }
        """
    )
    assert checked.info.functions["fill"].param_types == (ArrayType(FLOAT, 3), FLOAT)


def test_symbol_kinds() -> None:
    checked = check_source(
        "fn f(p: int) { let l = p; for k in 0..p { print(k + l); } }\nfn main() {}"
    )
    kinds = {
        n.ident: n.symbol.kind for n in walk(checked.ast) if isinstance(n, ast.Name) and n.symbol
    }
    assert kinds == {"p": VariableKind.PARAM, "l": VariableKind.LOCAL, "k": VariableKind.LOOP_VAR}


def test_loop_variable_can_be_shadowed_inside_body() -> None:
    check_source("fn main() { for i in 0..3 { let i = 10; print(i); } }")


def test_params_are_mutable() -> None:
    check_source("fn f(n: int) -> int { n = n + 1; return n; }\nfn main() {}")


@pytest.mark.parametrize(
    "body",
    [
        "if x > 0 { return 1; } else { return 2; }",
        "if x > 0 { return 1; } else if x < 0 { return -1; } else { return 0; }",
        "while true { if x > 3 { return x; } x = x + 1; }",
        "while true { for i in 0..3 { break; } return 1; }",  # inner break belongs to `for`
        "{ return 1; }",
        "return 1; print(2);",  # unreachable code after return is allowed
    ],
)
def test_functions_that_always_return(body: str) -> None:
    check_source(f"fn f(x: int) -> int {{ {body} }}\nfn main() {{}}")


@pytest.mark.parametrize(
    "cast",
    [
        "1 as float",
        "1.9 as int",
        "true as int",
        "false as float",
        "0 as bool",
        "0.5 as bool",
        "1 as int",
    ],
)
def test_all_scalar_casts_allowed(cast: str) -> None:
    check_source(f"fn main() {{ print({cast}); }}")


def test_void_main_and_void_functions() -> None:
    checked = check_source("fn log(x: int) { print(x); return; }\nfn main() { log(3); }")
    assert checked.info.main.return_type == VOID
    assert checked.info.functions["log"].return_type == VOID


def test_nested_array_literal() -> None:
    checked = check_source("fn main() { let m = [[1, 2], [3, 4], [5, 6]]; print(m[2][1]); }")
    let = checked.ast.functions[0].body.statements[0]
    assert isinstance(let, ast.LetStmt) and let.symbol is not None
    assert let.symbol.type == ArrayType(ArrayType(INT, 2), 3)

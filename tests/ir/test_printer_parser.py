"""IR text format: print -> parse -> print is the identity; parse errors are located."""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecompile.driver import build_ir
from forgecompile.ir.interpreter import run_module
from forgecompile.ir.parser import IRParseError, parse_function, parse_module
from forgecompile.ir.printer import format_module
from forgecompile.ir.values import Constant, IRType, format_float_constant
from forgecompile.ir.verify import verify_module

EXAMPLES = sorted((Path(__file__).parents[2] / "examples").glob("*.mini"))


@pytest.mark.parametrize("ssa", [False, True], ids=["pre-ssa", "ssa"])
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_round_trip_examples(path: Path, ssa: bool) -> None:
    module = build_ir(path.read_text("utf-8"), ssa=ssa)
    text = format_module(module)
    reparsed = parse_module(text)
    assert format_module(reparsed) == text
    verify_module(reparsed, ssa=ssa)
    # The reparsed module is executable and behaves identically.
    assert run_module(reparsed).observable == run_module(module).observable


def test_parse_every_instruction_form() -> None:
    text = """
func @callee(%p: ptr, %n: i64) -> f64 {
entry:
    %x: f64 = load %p[%n]
    ret %x
}

func @main() -> i64 {
entry:
    %a: ptr = alloca f64, 4
    memzero %a, f64, 4
    boundscheck 3, 4
    store %a[3], 2.5
    %row: ptr = ptradd %a, 2, f64
    %v: f64 = call @callee(%row, 1)
    %w: f64 = fmul %v, -1.5e-3
    %c: i1 = fcmp lt %w, 0.0
    %n: i1 = not %c
    %z: i64 = zext %n
    br %c, yes, no
yes:
    jump done
no:
    jump done
done:
    %r: i64 = phi [1, yes], [%z, no]
    print %r
    ret %r
}
"""
    module = parse_module(text)
    verify_module(module, ssa=True)
    result = run_module(module)
    assert result.stdout == "1\n" and result.exit_code == 1
    assert format_module(parse_module(format_module(module))) == format_module(module)


@pytest.mark.parametrize(
    "value",
    [0.0, -0.0, 1.5, 1e20, 1e-7, 123456789.0, float("inf"), float("-inf"), 2.5e-308],
)
def test_float_constants_round_trip(value: float) -> None:
    text = format_float_constant(value)
    fn = parse_function(f"func @f() -> f64 {{\nentry:\n    ret {text}\n}}")
    returned = fn.entry.instructions[0].operands[0]
    assert returned == Constant(IRType.F64, value)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("func @f() -> i64 {\nentry:\n    ret %nope\n}", "undefined register %nope"),
        ("func @f() -> i64 {\nentry:\n    jump nowhere\n}", "unknown block 'nowhere'"),
        (
            "func @f() -> i64 {\nentry:\n    %x: i64 = frobnicate 1\n    ret %x\n}",
            "unknown opcode 'frobnicate'",
        ),
        ("func @f() -> i64 {\nentry:\n    %x: i65 = add 1, 2\n    ret %x\n}", "unknown type 'i65'"),
        ("func @f() -> i64 {\n    ret 1\n}", "instruction before the first label"),
        ("func @f() -> i64 {\nentry:\n    ret 1\n", "function body is not closed"),
        (
            "func @f() -> i64 {\nentry:\n    add 1, 2\n    ret 1\n}",
            "'add' needs a destination register",
        ),
    ],
)
def test_parse_errors(text: str, message: str) -> None:
    with pytest.raises(IRParseError, match=message):
        parse_module(text)

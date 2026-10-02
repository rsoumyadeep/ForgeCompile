"""IR interpreter: counting, phi semantics, and invariant checks that catch compiler bugs."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from forgecompile.ir.instructions import Opcode
from forgecompile.ir.interpreter import (
    DEFAULT_COST_MODEL,
    InterpreterError,
    IRExecutionResult,
    IRInterpreter,
    StepLimitExceeded,
    run_module,
)
from forgecompile.ir.parser import parse_module


def run_text(text: str) -> object:
    return run_module(parse_module(text))


def test_counts_and_cost() -> None:
    module = parse_module(
        """
func @main() -> i64 {
entry:
    %a: i64 = add 1, 2
    %b: i64 = mul %a, %a
    print %b
    ret 0
}
"""
    )
    result = run_module(module)
    assert result.stdout == "9\n"
    assert result.steps == 4
    assert result.opcode_counts == {"add": 1, "mul": 1, "print": 1, "ret": 1}
    expected_cost = sum(
        DEFAULT_COST_MODEL[op] for op in (Opcode.ADD, Opcode.MUL, Opcode.PRINT, Opcode.RET)
    )
    assert result.cost == expected_cost


def test_phis_are_parallel_copies() -> None:
    # Swapping through phis: a naive sequential implementation would print 2, 2.
    module = parse_module(
        """
func @main() -> i64 {
entry:
    jump loop
loop:
    %a: i64 = phi [1, entry], [%b, loop]
    %b: i64 = phi [2, entry], [%a, loop]
    %n: i64 = phi [0, entry], [%n1, loop]
    %n1: i64 = add %n, 1
    %c: i1 = icmp lt %n1, 2
    br %c, loop, done
done:
    print %a
    print %b
    ret 0
}
"""
    )
    assert run_module(module).stdout == "2\n1\n"


def test_reading_undef_is_an_internal_error() -> None:
    text = """
func @main() -> i64 {
entry:
    %x: i64 = add undef.i64, 1
    ret %x
}
"""
    with pytest.raises(InterpreterError, match="observable use of undef"):
        run_text(text)


def test_undef_may_flow_through_phis_unobserved() -> None:
    text = """
func @main() -> i64 {
entry:
    jump next
next:
    %dead: i64 = phi [undef.i64, entry]
    ret 0
}
"""
    assert run_module(parse_module(text)).exit_code == 0


def test_memory_access_outside_buffer_is_an_internal_error() -> None:
    text = """
func @main() -> i64 {
entry:
    %a: ptr = alloca i64, 2
    %x: i64 = load %a[-1]
    ret %x
}
"""
    with pytest.raises(InterpreterError, match="outside buffer"):
        run_text(text)


def test_reaching_unreachable_is_an_internal_error() -> None:
    with pytest.raises(InterpreterError, match="unreachable"):
        run_text("func @main() -> i64 {\nentry:\n    unreachable\n}")


def test_boundscheck_traps_as_runtime_error() -> None:
    result = run_module(
        parse_module("func @main() -> i64 {\nentry:\n    boundscheck 5, 5\n    ret 0\n}")
    )
    assert result.exit_code == 101
    assert result.trap == "index 5 out of bounds for array of length 5"


def test_step_limit() -> None:
    module = parse_module(
        "func @main() -> i64 {\nentry:\n    jump entry2\nentry2:\n    jump entry2\n}"
    )
    with pytest.raises(StepLimitExceeded):
        IRInterpreter(module, max_steps=100).run()


def test_deep_recursion_uses_explicit_stack(ir_run: Callable[[str], IRExecutionResult]) -> None:
    source = """
    fn depth(n: int) -> int { if n == 0 { return 0; } return 1 + depth(n - 1); }
    fn main() -> int { print(depth(5000)); return 0; }
    """
    assert ir_run(source).stdout == "5000\n"

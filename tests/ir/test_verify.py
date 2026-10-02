"""IR verifier: each class of malformed IR is rejected with a located message."""

from __future__ import annotations

import pytest

from forgecompile.ir.function import Module
from forgecompile.ir.instructions import BinaryInst, Opcode, ReturnInst
from forgecompile.ir.parser import parse_module
from forgecompile.ir.values import IRType, Register, const_int
from forgecompile.ir.verify import IRVerificationError, verify_module


def errors(text: str, ssa: bool = False) -> list[str]:
    try:
        verify_module(parse_module(text), ssa=ssa)
    except IRVerificationError as exc:
        return exc.errors
    return []


def fn(body: str, header: str = "func @f() -> i64 {") -> str:
    return f"{header}\n{body}\n}}"


CASES = [
    # structure
    (fn("entry:\n    %x: i64 = add 1, 2"), "block does not end in a terminator", False),
    (fn("entry:\n    ret 1\n    ret 2"), "terminator 'ret' in the middle of the block", False),
    (fn("entry:\n    jump b\nb:\n    %x: i64 = add 1, 1\n    %p: i64 = phi [1, entry]\n    ret %x"),
     "phi after a non-phi instruction", False),
    (fn("entry:\n    jump entry"), "entry block must not have predecessors", False),
    # phis
    (fn("entry:\n    br true, a, b\na:\n    jump m\nb:\n    jump m\nm:\n    %p: i64 = phi [1, a]\n    ret %p"),
     "incoming blocks ['a'] != predecessors ['a', 'b']", False),
    # types
    (fn("entry:\n    %x: i64 = add 1, 2.0\n    ret %x"), "right operand has type f64, expected i64", False),
    (fn("entry:\n    %x: f64 = fadd 1.0, 2.0\n    ret %x"), "return value has type f64, expected i64", False),
    (fn("entry:\n    %c: i1 = icmp lt true, false\n    ret 0"), "ordering comparison on i1", False),
    (fn("entry:\n    br 1, a, a\na:\n    ret 0"), "branch condition has type i64, expected i1", False),
    (fn("entry:\n    ret"), "'ret' without a value", False),
    (fn("entry:\n    %x: i64 = call @missing()\n    ret %x"), "call to undefined function @missing", False),
    (fn("entry:\n    %x: f64 = load 1[0]\n    ret 0"), "pointer has type i64, expected ptr", False),
    # SSA
    (fn("entry:\n    %x: i64 = add 1, 2\n    %x: i64 = add 3, 4\n    ret %x"),
     "register %x is defined more than once", True),
    (fn("entry:\n    br true, a, b\na:\n    %x: i64 = add 1, 2\n    jump m\nb:\n    jump m\nm:\n    ret %x"),
     "definition of %x does not dominate its use", True),
    (fn("entry:\n    %y: i64 = add %x, 1\n    %x: i64 = add 1, 2\n    ret %y"),
     "register %x used before its definition", True),
]  # fmt: skip


@pytest.mark.parametrize(("text", "message", "ssa"), CASES)
def test_verifier_errors(text: str, message: str, ssa: bool) -> None:
    found = errors(text, ssa=ssa)
    assert any(message in e for e in found), found


def test_multiple_definitions_are_fine_before_ssa() -> None:
    assert (
        errors(fn("entry:\n    %x: i64 = copy 1\n    %x: i64 = copy 2\n    ret %x"), ssa=False)
        == []
    )


def test_phi_input_must_dominate_end_of_incoming_block() -> None:
    text = fn(
        "entry:\n    br true, a, b\n"
        "a:\n    %x: i64 = add 1, 2\n    jump m\n"
        "b:\n    jump m\n"
        "m:\n    %p: i64 = phi [%x, a], [0, b]\n    ret %p"
    )
    assert errors(text, ssa=True) == []  # %x dominates the end of `a`
    bad = text.replace("[0, b]", "[%x, b]")
    assert any("does not dominate" in e for e in errors(bad, ssa=True))


def test_stale_block_pointer_detected() -> None:
    module = Module()
    from forgecompile.ir.function import Function

    f = Function("f", [], IRType.I64)
    block = f.new_block("entry")
    inst = BinaryInst(Opcode.ADD, Register("x", IRType.I64), const_int(1), const_int(2))
    block.instructions.append(inst)  # bypasses append(): block pointer stays None
    block.append(ReturnInst(const_int(0)))
    module.add(f)
    with pytest.raises(IRVerificationError, match="stale block pointer"):
        verify_module(module)

"""sccp and cse."""

from __future__ import annotations

from collections.abc import Callable

Opt = Callable[..., object]

LOOP_CONSTANT = """
func @main() -> i64 {
entry:
    jump h
h:
    %x: i64 = phi [1, entry], [%x2, latch]
    %i: i64 = phi [0, entry], [%i1, latch]
    %c: i1 = icmp lt %i, 5
    br %c, body, done
body:
    %ne: i1 = icmp ne %x, 1
    br %ne, change, latch
change:
    jump latch
latch:
    %x2: i64 = phi [%x, body], [2, change]
    %i1: i64 = add %i, 1
    jump h
done:
    print %x
    ret 0
}
"""


def test_sccp_proves_loop_carried_constant_and_removes_dead_branch(opt: Opt) -> None:
    result = opt(LOOP_CONSTANT, ["sccp"])
    assert "print 1" in result.text
    assert "change:" not in result.text  # the `x != 1` branch can never be taken
    assert result.stats("sccp")["branches"] >= 1


def test_constfold_alone_cannot_do_this(opt: Opt) -> None:
    """The same input under constfold+copyprop: x stays a phi (optimistic analysis needed)."""
    result = opt(LOOP_CONSTANT, ["constfold", "copyprop"])
    assert "print %x" in result.text


def test_sccp_keeps_traps_and_params(opt: Opt) -> None:
    result = opt("""
func @f(%p: i64) -> i64 {
entry:
    %a: i64 = sdiv %p, 0
    ret %a
}

func @main() -> i64 {
entry:
    %r: i64 = call @f(3)
    ret %r
}""", ["sccp"])  # fmt: skip
    assert "sdiv %p, 0" in result.text
    assert result.after.exit_code == 101


def test_cse_reuses_dominating_computation_and_commutes(opt: Opt) -> None:
    result = opt("""
func @f(%a: i64, %b: i64) -> i64 {
entry:
    %x: i64 = mul %a, %b
    %y: i64 = mul %b, %a
    %z: i64 = add %x, %y
    ret %z
}

func @main() -> i64 {
entry:
    %r: i64 = call @f(6, 7)
    print %r
    ret 0
}""", ["cse"])  # fmt: skip
    f_text = result.text.split("func @main")[0]
    assert f_text.count("mul") == 1 and "add %x, %x" in f_text


def test_cse_does_not_reuse_across_sibling_branches(opt: Opt) -> None:
    result = opt("""
func @f(%a: i64, %c: i1) -> i64 {
entry:
    br %c, l, r
l:
    %x: i64 = mul %a, 3
    jump m
r:
    %y: i64 = mul %a, 3
    jump m
m:
    %p: i64 = phi [%x, l], [%y, r]
    ret %p
}

func @main() -> i64 {
entry:
    %r: i64 = call @f(5, false)
    print %r
    ret 0
}""", ["cse"])  # fmt: skip
    assert result.text.count("mul %a, 3") == 2  # neither branch dominates the other


def test_cse_does_not_merge_loads(opt: Opt) -> None:
    result = opt("""
func @main() -> i64 {
entry:
    %p: ptr = alloca i64, 1
    %a: i64 = load %p[0]
    store %p[0], 5
    %b: i64 = load %p[0]
    print %b
    ret %a
}""", ["cse"])  # fmt: skip
    assert result.text.count("load") == 2
    assert result.after.stdout == "5\n"

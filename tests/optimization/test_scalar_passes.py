"""constfold, copyprop, dce, simplify, simplifycfg: positive and negative cases in IR text.

Every test goes through ``run_passes``, which verifies SSA after each pass and
asserts that observable behaviour is unchanged.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

Opt = Callable[..., object]


def main(body: str) -> str:
    return f"func @main() -> i64 {{\nentry:\n{body}\n}}"


# ----------------------------------------------------------------------------- constfold


def test_constfold_chain(opt: Opt) -> None:
    result = opt(main("""
    %a: i64 = add 2, 3
    %b: i64 = mul %a, 4
    %c: i1 = icmp gt %b, 10
    %d: i64 = zext %c
    print %d
    ret %b"""), ["constfold"])  # fmt: skip
    assert result.opcodes() == ["print", "ret"]
    assert "print 1" in result.text and "ret 20" in result.text
    assert result.stats("constfold")["folded"] == 4


def test_constfold_respects_wraparound_and_c_division(opt: Opt) -> None:
    result = opt(main("""
    %a: i64 = add 9223372036854775807, 1
    %b: i64 = sdiv -7, 2
    %c: i64 = srem -7, 2
    print %a
    print %b
    print %c
    ret 0"""), ["constfold"])  # fmt: skip
    assert "print -9223372036854775808" in result.text
    assert "print -3" in result.text and "print -1" in result.text


def test_constfold_never_folds_a_trap(opt: Opt) -> None:
    result = opt(main("""
    %a: i64 = sdiv 1, 0
    print %a
    ret 0"""), ["constfold"])  # fmt: skip
    assert "sdiv 1, 0" in result.text  # still traps at run time
    assert result.after.exit_code == 101


def test_constfold_branch_and_unreachable_block(opt: Opt) -> None:
    result = opt("""
func @main() -> i64 {
entry:
    %c: i1 = icmp lt 1, 2
    br %c, yes, no
yes:
    print 1
    jump done
no:
    print 2
    jump done
done:
    %v: i64 = phi [10, yes], [20, no]
    ret %v
}""", ["constfold"])  # fmt: skip
    assert "no:" not in result.text and "print 2" not in result.text
    assert "ret 10" in result.text  # the phi lost its dead input and became constant


def test_constfold_bounds_checks(opt: Opt) -> None:
    result = opt(main("""
    boundscheck 3, 4
    boundscheck 4, 4
    ret 0"""), ["constfold"])  # fmt: skip
    assert "boundscheck 3, 4" not in result.text
    assert "boundscheck 4, 4" in result.text  # out of range: must still trap


def test_constfold_float_semantics(opt: Opt) -> None:
    result = opt(main("""
    %a: f64 = fdiv 1.0, 0.0
    %b: f64 = fdiv 0.0, 0.0
    %c: i1 = fcmp eq %b, %b
    %d: i64 = fptosi %a
    print %a
    print %c
    print %d
    ret 0"""), ["constfold"])  # fmt: skip
    assert "print inf" in result.text
    assert "print false" in result.text  # NaN != NaN
    assert "print 9223372036854775807" in result.text  # saturating cast


# ----------------------------------------------------------------------------- copyprop


def test_copyprop_removes_copies_and_trivial_phis(opt: Opt) -> None:
    result = opt("""
func @main() -> i64 {
entry:
    %a: i64 = add 1, 2
    %b: i64 = copy %a
    %c: i64 = copy %b
    br true, l, r
l:
    jump m
r:
    jump m
m:
    %p: i64 = phi [%c, l], [%b, r]
    print %p
    ret 0
}""", ["copyprop"])  # fmt: skip
    assert "copy" not in result.text and "phi" not in result.text
    assert "print %a" in result.text


def test_copyprop_keeps_phi_with_undef_and_loop_value(opt: Opt) -> None:
    """Regression for F-009: `phi [undef, entry], [%v, latch]` must not become %v."""
    text = """
func @main() -> i64 {
entry:
    jump h
h:
    %x: i64 = phi [undef.i64, entry], [%v, h]
    %n: i64 = phi [0, entry], [%n1, h]
    %v: i64 = add %n, 1
    %n1: i64 = add %n, 1
    %c: i1 = icmp lt %n1, 3
    br %c, h, done
done:
    print %n1
    ret 0
}"""
    result = opt(text, ["copyprop"])
    assert "phi [undef.i64, entry], [%v, h]" in result.text


# ----------------------------------------------------------------------------- dce


def test_dce_removes_dead_pure_code_and_dead_phi_cycles(opt: Opt) -> None:
    result = opt("""
func @main() -> i64 {
entry:
    %dead: i64 = mul 3, 4
    jump h
h:
    %i: i64 = phi [0, entry], [%i1, h]
    %u: i64 = phi [0, entry], [%u1, h]
    %u1: i64 = add %u, 7
    %i1: i64 = add %i, 1
    %c: i1 = icmp lt %i1, 3
    br %c, h, done
done:
    ret %i1
}""", ["dce"])  # fmt: skip
    assert "%dead" not in result.text
    assert "%u" not in result.text  # the u/u1 cycle only feeds itself
    assert result.stats("dce") == {"instructions": 2, "phis": 1}


def test_dce_keeps_effects_and_possible_traps(opt: Opt) -> None:
    result = opt("""
func @f(%x: i64, %p: ptr) -> i64 {
entry:
    %q: i64 = sdiv 10, %x
    %r: i64 = sdiv 10, 2
    store %p[0], 1
    boundscheck %x, 3
    ret 0
}

func @main() -> i64 {
entry:
    %a: ptr = alloca i64, 1
    %v: i64 = call @f(5, %a)
    ret 0
}""", ["dce"])  # fmt: skip
    assert "sdiv 10, %x" in result.text  # might divide by zero: must stay
    assert "sdiv 10, 2" not in result.text  # provably safe and unused
    assert "store" in result.text and "boundscheck" in result.text and "call @f" in result.text


# ----------------------------------------------------------------------------- simplify


@pytest.mark.parametrize(
    ("inst", "expected"),
    [
        ("%r: i64 = add %x, 0", "ret %x"),
        ("%r: i64 = add 0, %x", "ret %x"),
        ("%r: i64 = sub %x, 0", "ret %x"),
        ("%r: i64 = mul %x, 1", "ret %x"),
        ("%r: i64 = sdiv %x, 1", "ret %x"),
        ("%r: i64 = mul %x, 0", "ret 0"),
        ("%r: i64 = sub %x, %x", "ret 0"),
        ("%r: i64 = srem %x, -1", "ret 0"),
        ("%r: i64 = mul %x, -1", "neg %x"),
        ("%r: i64 = sdiv %x, -1", "neg %x"),
        ("%r: i64 = sub 0, %x", "neg %x"),
    ],
)
def test_simplify_integer_identities(opt: Opt, inst: str, expected: str) -> None:
    text = f"func @f(%x: i64) -> i64 {{\nentry:\n    {inst}\n    ret %r\n}}\n\nfunc @main() -> i64 {{\nentry:\n    %v: i64 = call @f(-9223372036854775807)\n    print %v\n    ret 0\n}}"
    result = opt(text, ["simplify"])
    assert expected in result.text


@pytest.mark.parametrize(
    ("inst", "simplified"),
    [
        ("%r: f64 = fmul %x, 1.0", True),
        ("%r: f64 = fdiv %x, 1.0", True),
        ("%r: f64 = fsub %x, 0.0", True),
        ("%r: f64 = fadd %x, -0.0", True),
        # These look tempting, but are wrong for -0.0, NaN or inf:
        ("%r: f64 = fadd %x, 0.0", False),
        ("%r: f64 = fmul %x, 0.0", False),
        ("%r: f64 = fsub %x, %x", False),
        ("%r: f64 = fsub %x, -0.0", False),
    ],
)
def test_simplify_float_identities_are_ieee_exact(opt: Opt, inst: str, simplified: bool) -> None:
    text = f"func @f(%x: f64) -> f64 {{\nentry:\n    {inst}\n    ret %r\n}}\n\nfunc @main() -> i64 {{\nentry:\n    %v: f64 = call @f(-0.0)\n    print %v\n    ret 0\n}}"
    result = opt(text, ["simplify"])
    assert ("ret %x" in result.text) is simplified


def test_simplify_booleans_and_compares(opt: Opt) -> None:
    text = """
func @f(%b: i1, %x: i64) -> i64 {
entry:
    %n1: i1 = not %b
    %n2: i1 = not %n1
    %e: i1 = icmp eq %n2, true
    %z: i64 = zext %e
    %t: i1 = icmp ne %z, 0
    %s: i1 = icmp le %x, %x
    %c: i1 = icmp lt %x, 5
    %nc: i1 = not %c
    print %t
    print %s
    print %nc
    ret 0
}

func @main() -> i64 {
entry:
    %r: i64 = call @f(true, 7)
    ret %r
}"""
    result = opt(text, ["simplify", "dce"])
    f_text = result.text.split("func @main")[0]
    assert "print %b" in f_text  # not(not b) == b, and the compare chain collapses to b
    assert "print true" in f_text  # x <= x
    assert "icmp ge %x, 5" in f_text  # not (x < 5)


def test_simplify_canonicalizes_constants_to_the_right(opt: Opt) -> None:
    text = "func @f(%x: i64) -> i64 {\nentry:\n    %r: i64 = mul 3, %x\n    ret %r\n}\n\nfunc @main() -> i64 {\nentry:\n    ret 0\n}"
    assert "mul %x, 3" in opt(text, ["simplify"]).text


# ----------------------------------------------------------------------------- simplifycfg


def test_simplifycfg_merges_chains_and_forwards_empty_blocks(opt: Opt) -> None:
    result = opt("""
func @main() -> i64 {
entry:
    jump a
a:
    print 1
    jump b
b:
    jump c
c:
    print 2
    ret 0
}""", ["simplifycfg"])  # fmt: skip
    assert result.text.count(":\n") == 1  # one block left (only the entry label)
    assert result.opcodes() == ["print", "print", "ret"]


def test_simplifycfg_keeps_forwarding_that_would_break_phis(opt: Opt) -> None:
    text = """
func @main() -> i64 {
entry:
    br true, empty, m
empty:
    jump m
m:
    %p: i64 = phi [1, empty], [2, entry]
    print %p
    ret 0
}"""
    result = opt(text, ["simplifycfg"])
    # `empty` cannot simply be skipped (entry would need two phi inputs), but the
    # constant branch is folded, after which the blocks merge.
    assert result.after.stdout == "1\n"

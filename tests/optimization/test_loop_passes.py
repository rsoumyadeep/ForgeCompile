"""licm, strength, bce, inline, and loop analysis, on IR lowered from MiniLang."""

from __future__ import annotations

from forgecompile.analysis.loops import find_loops
from forgecompile.driver import build_ir
from forgecompile.ir.instructions import Opcode
from forgecompile.ir.interpreter import run_module
from forgecompile.ir.printer import format_function
from forgecompile.optimization.pass_manager import optimize


def compiled(source: str, passes: list[str]) -> tuple[str, object, object]:
    reference = run_module(build_ir(source))
    module = build_ir(source)
    optimize(module, passes)
    result = run_module(module)
    assert result.observable == reference.observable
    return format_function(module.functions["main"]), reference, result


def count(text: str, opcode: str) -> int:
    return sum(
        1
        for line in text.splitlines()
        if f"= {opcode} " in line or line.strip().startswith(opcode + " ")
    )


def test_find_loops_nesting() -> None:
    module = build_ir(
        "fn main() { for i in 0..3 { for j in 0..2 { print(i * j); } } while false { } }"
    )
    loops = find_loops(module.functions["main"])
    depths = sorted(loop.depth for loop in loops)
    assert depths == [1, 1, 2]
    inner = next(loop for loop in loops if loop.depth == 2)
    assert inner.parent is not None and inner in inner.parent.children


NESTED = """
fn main() {
    let n = 7;
    let total = 0;
    for i in 0..10 {
        for j in 0..10 {
            total = total + n * 3 + i * 5;
        }
    }
    print(total);
}
"""


def test_licm_hoists_invariants_out_of_both_loops() -> None:
    _, before, after = compiled(NESTED, ["copyprop", "licm"])
    # n*3 is invariant in both loops (hoisted to the outer preheader); i*5 only in the inner.
    assert after.opcode_counts["mul"] < before.opcode_counts["mul"]
    # n*3 runs once (outer preheader) + i*5 once per outer iteration (inner preheader).
    assert before.opcode_counts["mul"] == 200
    assert after.opcode_counts["mul"] == 1 + 10


def test_licm_does_not_hoist_possible_traps_or_loads() -> None:
    source = """
    fn main() {
        let a: [int; 4];
        let d = 0;
        for i in 0..0 { print(10 / d); print(a[1]); }
        print(1);
    }
    """
    text, _, after = compiled(source, ["copyprop", "licm"])
    assert after.trap is None  # hoisting `10 / d` would have trapped a loop that never runs
    assert "sdiv 10" in text.split("for.body:")[1]  # still inside the loop body


def test_strength_reduction_replaces_iv_multiply() -> None:
    source = "fn main() { let s = 0; for i in 0..100 { s = s + i * 12; } print(s); }"
    text, before, after = compiled(source, ["copyprop", "strength"])
    assert before.opcode_counts["mul"] == 100
    assert after.opcode_counts.get("mul", 0) == 0
    assert "phi [0, " in text and "add %i.2.x12" in text


def test_strength_reduction_skips_conditional_multiply() -> None:
    source = "fn main() { let s = 0; for i in 0..10 { if i == 3 { s = s + i * 12; } } print(s); }"
    _, before, after = compiled(source, ["copyprop", "strength"])
    assert after.opcode_counts["mul"] == before.opcode_counts["mul"] == 1


def test_bce_removes_provably_safe_checks() -> None:
    source = "fn main() { let a: [int; 8]; for i in 0..8 { a[i] = i; } print(a[7]); }"
    _, before, after = compiled(source, ["copyprop", "bce"])
    assert before.opcode_counts["boundscheck"] == 9  # 8 in the loop + a[7]
    assert after.opcode_counts["boundscheck"] == 1  # only a[7] (constfold's job)


def test_bce_keeps_checks_that_can_fail() -> None:
    for header in ("for i in 0..9", "for i in -1..8"):
        source = f"fn main() {{ let a: [int; 8]; {header} {{ a[i] = i; }} }}"
        _, before, after = compiled(source, ["copyprop", "bce"])
        assert after.trap is not None and before.trap is not None
        assert after.opcode_counts["boundscheck"] == before.opcode_counts["boundscheck"]


def test_inline_small_function_and_keep_recursive() -> None:
    source = """
    fn sq(x: int) -> int { return x * x; }
    fn fact(n: int) -> int { if n < 2 { return 1; } return n * fact(n - 1); }
    fn main() { print(sq(9) + fact(5)); }
    """
    text, before, after = compiled(source, ["inline", "sccp", "copyprop", "dce"])
    assert "call @sq" not in text
    assert "call @fact" in text  # recursive: never inlined
    assert after.opcode_counts["call"] < before.opcode_counts["call"]


def test_inline_multiple_returns_produce_phi() -> None:
    source = """
    fn sign(x: int) -> int { if x < 0 { return -1; } if x == 0 { return 0; } return 1; }
    fn main() { print(sign(-5)); print(sign(0)); print(sign(9)); }
    """
    text, _, after = compiled(source, ["inline"])
    assert "call" not in text and "phi" in text
    assert after.stdout == "-1\n0\n1\n"


def test_inline_array_callee_alloca_hoisted_to_caller_entry() -> None:
    source = """
    fn tmp(k: int) -> int { let a: [int; 3]; a[0] = k; return a[0] + a[1]; }
    fn main() { for i in 0..4 { print(tmp(i)); } }
    """
    module = build_ir(source)
    optimize(module, ["inline"])
    entry = module.functions["main"].entry
    assert any(inst.opcode is Opcode.ALLOCA for inst in entry.instructions)
    assert run_module(module).stdout == "0\n1\n2\n3\n"

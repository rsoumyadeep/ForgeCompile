"""SSA construction: phi placement, renaming, and preservation of behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecompile.driver import build_ir, lower_source
from forgecompile.ir.instructions import PhiInst
from forgecompile.ir.interpreter import run_module
from forgecompile.ir.printer import format_function
from forgecompile.ir.ssa import construct_ssa, construct_ssa_module
from forgecompile.ir.values import Undef
from forgecompile.ir.verify import verify_module

EXAMPLES = sorted((Path(__file__).parents[2] / "examples").glob("*.mini"))


def test_gcd_textbook_ssa() -> None:
    source = """
    fn gcd(a: int, b: int) -> int {
        while b != 0 { let t = b; b = a % b; a = t; }
        return a;
    }
    fn main() {}
    """
    fn = build_ir(source).functions["gcd"]
    text = format_function(fn)
    # Loop-carried variables get phis at the loop header, with the parameter as version 0.
    assert "%b.1: i64 = phi [%b, entry], [%b.2, while.body]" in text
    assert "%a.1: i64 = phi [%a, entry], [%a.2, while.body]" in text
    assert "ret %a.1" in text


def test_straight_line_code_needs_no_phis() -> None:
    module = lower_source("fn main() { let x = 1; x = x + 1; x = x * 3; print(x); }")
    assert construct_ssa_module(module) == 0
    verify_module(module, ssa=True)
    assert run_module(module).stdout == "6\n"


def test_if_else_join_gets_one_phi() -> None:
    module = lower_source(
        "fn main() { let x = 1; let c = true; if c { x = 2; } else { x = 3; } print(x); }"
    )
    assert construct_ssa_module(module) == 1
    verify_module(module, ssa=True)
    phis = [i for i in module.functions["main"].instructions() if isinstance(i, PhiInst)]
    assert len(phis) == 1 and len(phis[0].operands) == 2


def test_semi_pruning_skips_block_local_variables() -> None:
    # `t` is declared and used only inside one block per iteration: no phi for it.
    module = lower_source(
        "fn main() { let s = 0; for i in 0..3 { let t = i * 2; s = s + t; } print(s); }"
    )
    construct_ssa_module(module)
    names = {
        i.dest.name.split(".")[0]
        for i in module.functions["main"].instructions()
        if isinstance(i, PhiInst) and i.dest
    }
    assert "t" not in names
    assert {"s", "i"} <= names
    assert run_module(module).stdout == "6\n"


def test_loop_local_variable_gets_unobserved_undef_at_loop_header() -> None:
    # `v` has two definitions (the let, and the assignment in the `if`), so it is an
    # SSA variable. The iterated dominance frontier puts a phi for it at the loop
    # header, where no definition reaches from the entry edge: that input is undef.
    # The phi is dead (v is redefined before any use), so undef is never observed;
    # the IR interpreter would raise if it were.
    source = """
    fn main() {
        for i in 0..3 {
            let v = i;
            if i > 0 { v = v + 1; }
            print(v);
        }
    }
    """
    module = build_ir(source)
    undef_inputs = [
        op for inst in module.functions["main"].instructions() if isinstance(inst, PhiInst)
        for op in inst.operands if isinstance(op, Undef)
    ]  # fmt: skip
    assert undef_inputs  # the interesting case actually occurs
    assert run_module(module).stdout == "0\n2\n3\n"


def test_single_assignment_local_needs_no_phi() -> None:
    # A `let` with no later assignment has one static definition, which dominates all
    # its uses, so it needs no phi even when it is used in other blocks.
    module = lower_source("fn main() { for i in 0..3 { let v = i * 10; if i > 0 { print(v); } } }")
    construct_ssa_module(module)
    phi_names = {
        inst.dest.name for inst in module.functions["main"].instructions()
        if isinstance(inst, PhiInst) and inst.dest is not None
    }  # fmt: skip
    assert not any(name.startswith("v") for name in phi_names)
    verify_module(module, ssa=True)


def test_reassigned_parameter() -> None:
    module = build_ir(
        "fn f(n: int) -> int { while n > 10 { n = n - 7; } return n; }\nfn main() { print(f(40)); }"
    )
    assert run_module(module).stdout == "5\n"


def test_construct_ssa_is_idempotent() -> None:
    module = build_ir("fn main() { let x = 0; for i in 0..4 { x = x + i; } print(x); }")
    before = format_function(module.functions["main"])
    assert construct_ssa(module.functions["main"]) == 0  # already SSA: nothing to do
    assert format_function(module.functions["main"]) == before


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_are_valid_ssa_and_behave_identically(path: Path) -> None:
    source = path.read_text("utf-8")
    before = run_module(build_ir(source, ssa=False))
    module = build_ir(source, ssa=True)  # verifies the SSA dominance property
    after = run_module(module)
    assert after.observable == before.observable
    assert after.stdout == path.with_suffix(".expected").read_text("utf-8")

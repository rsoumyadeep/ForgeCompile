"""CFG utilities: predecessors, unreachable-block removal, critical edges."""

from __future__ import annotations

from forgecompile.analysis.cfg import (
    is_critical_edge,
    predecessors,
    remove_unreachable_blocks,
    split_edge,
)
from forgecompile.ir.interpreter import run_module
from forgecompile.ir.parser import parse_function, parse_module
from forgecompile.ir.verify import verify_module


def test_predecessors() -> None:
    fn = parse_function(
        "func @f() -> i64 {\nentry:\n    br true, a, b\na:\n    jump m\nb:\n    jump m\nm:\n    ret 0\n}"
    )
    preds = predecessors(fn)
    labels = {b.label: [p.label for p in ps] for b, ps in preds.items()}
    assert labels == {"entry": [], "a": ["entry"], "b": ["entry"], "m": ["a", "b"]}


def test_remove_unreachable_blocks_fixes_phis() -> None:
    fn = parse_function(
        """
func @f() -> i64 {
entry:
    jump m
dead:
    jump m
m:
    %p: i64 = phi [1, entry], [2, dead]
    ret %p
}
"""
    )
    assert remove_unreachable_blocks(fn) == 1
    assert [b.label for b in fn.blocks] == ["entry", "m"]
    (phi,) = fn.blocks[1].phis()
    assert [b.label for b in phi.blocks] == ["entry"]


def test_split_critical_edge_preserves_semantics() -> None:
    module = parse_module(
        """
func @main() -> i64 {
entry:
    br true, m, other
other:
    jump m
m:
    %p: i64 = phi [10, entry], [20, other]
    print %p
    ret 0
}
"""
    )
    fn = module.functions["main"]
    entry, _, m = fn.blocks
    preds = predecessors(fn)
    assert is_critical_edge(entry, m, preds)
    middle = split_edge(fn, entry, m)
    verify_module(module, ssa=True)
    (phi,) = m.phis()
    assert middle in phi.blocks and entry not in phi.blocks
    assert run_module(module).stdout == "10\n"

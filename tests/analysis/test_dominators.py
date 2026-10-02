"""Dominators and dominance frontiers: textbook CFGs plus a brute-force property test.

The property test checks the *definition* of dominance directly on random
CFGs: A dominates B iff B is unreachable from the entry once A is removed.
This is independent of the Cooper-Harvey-Kennedy algorithm under test.
"""

from __future__ import annotations

import random

import pytest

from forgecompile.analysis.cfg import predecessors, reachable_blocks, reverse_postorder
from forgecompile.analysis.dominators import DominatorTree
from forgecompile.ir.function import BasicBlock, Function
from forgecompile.ir.instructions import BranchInst, JumpInst, ReturnInst
from forgecompile.ir.parser import parse_function
from forgecompile.ir.values import IRType, const_bool, const_int


def cfg(edges: str, labels: str) -> Function:
    """Build a function from 'a->b a->c ...' (2 successors become a br, 0 become ret)."""
    fn = Function("f", [], IRType.I64)
    blocks = {label: fn.new_block(label) for label in labels.split()}
    succs: dict[str, list[str]] = {label: [] for label in blocks}
    for edge in edges.split():
        src, dst = edge.split("->")
        succs[src].append(dst)
    for label, targets in succs.items():
        block = blocks[label]
        if not targets:
            block.append(ReturnInst(const_int(0)))
        elif len(targets) == 1:
            block.append(JumpInst(blocks[targets[0]]))
        else:
            block.append(BranchInst(const_bool(True), blocks[targets[0]], blocks[targets[1]]))
    return fn


def idoms(fn: Function) -> dict[str, str | None]:
    tree = DominatorTree(fn)
    return {b.label: (d.label if d is not None else None) for b, d in tree.idom.items()}


def frontiers(fn: Function) -> dict[str, set[str]]:
    df = DominatorTree(fn).frontiers()
    return {b.label: {x.label for x in s} for b, s in df.items()}


def test_diamond() -> None:
    fn = cfg("entry->a entry->b a->m b->m", "entry a b m")
    assert idoms(fn) == {"entry": None, "a": "entry", "b": "entry", "m": "entry"}
    assert frontiers(fn) == {"entry": set(), "a": {"m"}, "b": {"m"}, "m": set()}


def test_while_loop() -> None:
    fn = cfg("entry->h h->body h->exit body->h", "entry h body exit")
    assert idoms(fn) == {"entry": None, "h": "entry", "body": "h", "exit": "h"}
    # The loop header is in its own frontier (via the back edge) and in the body's.
    assert frontiers(fn) == {"entry": set(), "h": {"h"}, "body": {"h"}, "exit": set()}


def test_nested_loops_with_if() -> None:
    edges = "e->h1 h1->h2 h1->x h2->b h2->l1 b->t b->f t->j f->j j->h2 l1->h1"
    fn = cfg(edges, "e h1 h2 b t f j l1 x")
    assert idoms(fn) == {
        "e": None, "h1": "e", "h2": "h1", "b": "h2", "t": "b", "f": "b",
        "j": "b", "l1": "h2", "x": "h1",
    }  # fmt: skip
    df = frontiers(fn)
    assert df["t"] == {"j"} and df["f"] == {"j"}
    assert df["j"] == {"h2"}
    assert df["l1"] == {"h1"}
    assert df["h2"] == {"h1", "h2"}


def test_irreducible_cfg() -> None:
    """MiniLang cannot produce this (no goto), but the algorithm must still be correct."""
    fn = cfg("e->a e->b a->b b->a a->x", "e a b x")
    assert idoms(fn) == {"e": None, "a": "e", "b": "e", "x": "a"}


def test_unreachable_blocks_are_ignored() -> None:
    fn = cfg("e->a dead->a", "e a dead")
    tree = DominatorTree(fn)
    assert {b.label for b in tree.rpo} == {"e", "a"}
    assert idoms(fn) == {"e": None, "a": "e"}


def test_dominates_query_and_preorder() -> None:
    fn = cfg("e->a e->b a->m b->m", "e a b m")
    tree = DominatorTree(fn)
    e, a, b, m = fn.blocks
    assert tree.dominates(e, m) and tree.dominates(m, m)
    assert not tree.dominates(a, m) and not tree.strictly_dominates(m, m)
    order = tree.preorder()
    assert order[0] is e and set(order) == {e, a, b, m}


def _brute_force_dominates(fn: Function, a: BasicBlock, b: BasicBlock) -> bool:
    if a is b:
        return True
    seen = {fn.entry}
    stack = [fn.entry]
    if fn.entry is a:
        return True
    while stack:
        block = stack.pop()
        for succ in block.successors:
            if succ is a or succ in seen:
                continue
            seen.add(succ)
            stack.append(succ)
    return b not in seen


def _random_cfg(rng: random.Random, n: int) -> Function:
    labels = [f"b{i}" for i in range(n)]
    edges = []
    for i, label in enumerate(labels):
        out = rng.choice([0, 1, 1, 2, 2]) if i else rng.choice([1, 2])
        for _ in range(out):
            target = rng.randrange(1, n)  # never jump back to the entry
            edges.append(f"{label}->b{target}")
    # Deduplicate per source but keep at most 2 successors.
    per_src: dict[str, list[str]] = {}
    for edge in edges:
        src, dst = edge.split("->")
        if dst not in per_src.setdefault(src, []) and len(per_src[src]) < 2:
            per_src[src].append(dst)
    flat = " ".join(f"{s}->{d}" for s, ds in per_src.items() for d in ds)
    return cfg(flat, " ".join(labels))


@pytest.mark.parametrize("seed", range(40))
def test_dominance_matches_definition_on_random_cfgs(seed: int) -> None:
    rng = random.Random(seed)
    fn = _random_cfg(rng, rng.randrange(2, 12))
    tree = DominatorTree(fn)
    reachable = reachable_blocks(fn)
    for a in reachable:
        for b in reachable:
            assert tree.dominates(a, b) == _brute_force_dominates(fn, a, b), (a, b)
    # Frontier definition: B in DF(A) iff A dominates some pred of B and not strictly B.
    preds = predecessors(fn)
    df = tree.frontiers()
    for a in reachable:
        expected = {
            b for b in reachable
            if any(p in reachable and tree.dominates(a, p) for p in preds[b])
            and not tree.strictly_dominates(a, b)
        }  # fmt: skip
        assert df[a] == expected


def test_reverse_postorder_puts_dominators_first() -> None:
    fn = parse_function(
        """
func @f() -> i64 {
entry:
    br true, a, b
a:
    jump m
b:
    jump m
m:
    ret 0
}
"""
    )
    order = [b.label for b in reverse_postorder(fn)]
    assert order[0] == "entry" and order[-1] == "m"

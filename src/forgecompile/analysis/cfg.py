"""Control-flow graph queries and simple CFG transformations.

The CFG of a function has a node per basic block and an edge ``A -> B`` when
A's terminator can transfer control to B. Successors are read directly from
terminators. Predecessors are *computed* (``predecessors``) rather than stored,
so there is no cached predecessor list for a transformation to forget to update.
The cost is an O(blocks + edges) recomputation, which is negligible at
MiniLang program sizes.
"""

from __future__ import annotations

from forgecompile.ir.function import BasicBlock, Function
from forgecompile.ir.instructions import JumpInst, PhiInst


def predecessors(fn: Function) -> dict[BasicBlock, list[BasicBlock]]:
    """Map each block to its predecessors, in a deterministic order (block order)."""
    preds: dict[BasicBlock, list[BasicBlock]] = {block: [] for block in fn.blocks}
    for block in fn.blocks:
        for succ in block.successors:
            if block not in preds[succ]:
                preds[succ].append(block)
    return preds


def reverse_postorder(fn: Function) -> list[BasicBlock]:
    """Reachable blocks in reverse postorder (RPO) of a DFS from the entry.

    In RPO every block appears before its successors, except along back edges.
    Forward data-flow analyses and the dominator algorithm converge fastest
    when they visit blocks in this order. Iterative, so deep CFGs cannot hit
    Python's recursion limit.
    """
    visited: set[BasicBlock] = set()
    postorder: list[BasicBlock] = []
    stack: list[tuple[BasicBlock, int]] = [(fn.entry, 0)]
    visited.add(fn.entry)
    while stack:
        block, child_index = stack.pop()
        successors = block.successors
        if child_index < len(successors):
            stack.append((block, child_index + 1))
            child = successors[child_index]
            if child not in visited:
                visited.add(child)
                stack.append((child, 0))
        else:
            postorder.append(block)
    postorder.reverse()
    return postorder


def reachable_blocks(fn: Function) -> set[BasicBlock]:
    return set(reverse_postorder(fn))


def remove_unreachable_blocks(fn: Function) -> int:
    """Delete blocks not reachable from the entry; fix up phis. Returns the count removed."""
    reachable = reachable_blocks(fn)
    dead = [block for block in fn.blocks if block not in reachable]
    if not dead:
        return 0
    dead_set = set(dead)
    for block in fn.blocks:
        if block in dead_set:
            continue
        for phi in block.phis():
            for pred in [p for p in phi.blocks if p in dead_set]:
                phi.remove_incoming(pred)
    fn.blocks = [block for block in fn.blocks if block not in dead_set]
    return len(dead)


def edges(fn: Function) -> list[tuple[BasicBlock, BasicBlock]]:
    return [(block, succ) for block in fn.blocks for succ in block.successors]


def is_critical_edge(
    source: BasicBlock, target: BasicBlock, preds: dict[BasicBlock, list[BasicBlock]]
) -> bool:
    """An edge is *critical* if its source has several successors and its target several
    predecessors. Code cannot be placed "on" such an edge without splitting it."""
    return len(source.successors) > 1 and len(preds[target]) > 1


def split_edge(fn: Function, source: BasicBlock, target: BasicBlock) -> BasicBlock:
    """Insert a new block on the edge ``source -> target`` and return it."""
    middle = fn.new_block(f"{source.label}.to.{target.label}")
    middle.append(JumpInst(target))
    terminator = source.terminator
    assert terminator is not None
    terminator.replace_target(target, middle)
    for inst in target.instructions:
        if not isinstance(inst, PhiInst):
            break
        inst.blocks = [middle if b is source else b for b in inst.blocks]
    # Place the new block just before its target for readable output.
    fn.blocks.remove(middle)
    fn.blocks.insert(fn.blocks.index(target), middle)
    return middle

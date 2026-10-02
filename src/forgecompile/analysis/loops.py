"""Natural loops, loop nesting, preheaders and basic induction variables.

**Natural loop.** A *back edge* is an edge ``t -> h`` where ``h`` dominates
``t``. Its natural loop is ``h`` plus every block that can reach ``t`` without
passing through ``h``. Back edges that share a header are merged into one loop
with several *latches*. MiniLang CFGs are always reducible (there is no goto),
so every cycle is a natural loop.

**Preheader.** A block outside the loop whose only successor is the header,
and which is the header's only predecessor from outside the loop. It is the
place where loop-invariant code is hoisted and where induction-variable start
values are computed. :func:`ensure_preheader` creates one if needed.

**Basic induction variable (IV).** A header phi ``%i = phi [init, preheader],
[%next, latch]`` where ``%next = add %i, step`` and ``step`` is a constant.
Lowering produces exactly this shape for ``for`` loops.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from forgecompile.analysis.cfg import predecessors
from forgecompile.analysis.dominators import DominatorTree
from forgecompile.ir.function import BasicBlock, Function
from forgecompile.ir.instructions import BinaryInst, JumpInst, Opcode, PhiInst
from forgecompile.ir.values import Constant, Value


@dataclass(eq=False)
class Loop:
    header: BasicBlock
    blocks: set[BasicBlock]
    latches: list[BasicBlock]
    parent: Loop | None = None
    children: list[Loop] = field(default_factory=list)

    @property
    def depth(self) -> int:
        depth, loop = 1, self.parent
        while loop is not None:
            depth, loop = depth + 1, loop.parent
        return depth

    def contains(self, block: BasicBlock | None) -> bool:
        return block in self.blocks

    def __repr__(self) -> str:
        return f"<Loop header={self.header.label} blocks={len(self.blocks)}>"


def find_loops(fn: Function, domtree: DominatorTree | None = None) -> list[Loop]:
    """All natural loops, innermost first (sorted by size, so children precede parents)."""
    domtree = domtree or DominatorTree(fn)
    preds = domtree.preds
    by_header: dict[BasicBlock, list[BasicBlock]] = {}
    for block in domtree.rpo:
        for succ in block.successors:
            if domtree.dominates(succ, block):  # back edge block -> succ
                by_header.setdefault(succ, []).append(block)
    loops: list[Loop] = []
    for header, latches in by_header.items():
        body = {header}
        work = [latch for latch in latches if latch is not header]
        body.update(work)
        while work:
            block = work.pop()
            for pred in preds[block]:
                if pred not in body and pred in domtree._rpo_index:  # reachable preds only
                    body.add(pred)
                    work.append(pred)
        loops.append(Loop(header, body, latches))
    loops.sort(key=lambda loop: (len(loop.blocks), loop.header.label))
    for i, loop in enumerate(loops):
        for outer in loops[i + 1 :]:
            if loop.header in outer.blocks and loop.blocks <= outer.blocks:
                loop.parent = outer
                outer.children.append(loop)
                break
    return loops


def preheader(loop: Loop, preds: dict[BasicBlock, list[BasicBlock]]) -> BasicBlock | None:
    """The existing preheader, or None if the loop does not have one."""
    outside = [p for p in preds[loop.header] if p not in loop.blocks]
    if len(outside) == 1 and outside[0].successors == [loop.header]:
        return outside[0]
    return None


def ensure_preheader(fn: Function, loop: Loop) -> tuple[BasicBlock, bool]:
    """Return ``(preheader, created)``, inserting a new preheader block if needed.

    Outside predecessors are redirected to the new block. A header phi with
    several outside inputs gets a new phi in the preheader that merges them.
    """
    preds = predecessors(fn)
    existing = preheader(loop, preds)
    if existing is not None:
        return existing, False
    header = loop.header
    outside = [p for p in preds[header] if p not in loop.blocks]
    new = fn.new_block(f"{header.label}.preheader")
    fn.blocks.remove(new)
    fn.blocks.insert(fn.blocks.index(header), new)
    for pred in outside:
        term = pred.terminator
        assert term is not None
        term.replace_target(header, new)
    for phi in header.phis():
        assert phi.dest is not None
        incoming = [(v, b) for v, b in phi.incoming if b not in loop.blocks]
        for _, b in incoming:
            phi.remove_incoming(b)
        if len(incoming) == 1:
            phi.add_incoming(incoming[0][0], new)
        else:
            merged = PhiInst(fn.new_register(f"{phi.dest.name}.ph", phi.dest.type), incoming)
            new.append(merged)
            assert merged.dest is not None
            phi.add_incoming(merged.dest, new)
    new.append(JumpInst(header))
    return new, True


@dataclass
class InductionVariable:
    phi: PhiInst
    init: Value  # value on entry (from the preheader)
    step: int
    update: BinaryInst  # %next = add %phi, step   (in the loop)
    latch: BasicBlock


def basic_induction_variables(loop: Loop, preheader_block: BasicBlock) -> list[InductionVariable]:
    """Header phis of the form ``phi [init, preheader], [phi + step, latch]`` (single latch)."""
    if len(loop.latches) != 1:
        return []
    latch = loop.latches[0]
    result: list[InductionVariable] = []
    for phi in loop.header.phis():
        if len(phi.blocks) != 2 or set(phi.blocks) != {preheader_block, latch}:
            continue
        update_value = phi.value_from(latch)
        update = _defining_add(update_value, loop)
        if update is None:
            continue
        a, b = update.operands
        if a is phi.dest and isinstance(b, Constant):
            step = b.value
        elif b is phi.dest and isinstance(a, Constant):
            step = a.value
        else:
            continue
        assert isinstance(step, int)
        result.append(InductionVariable(phi, phi.value_from(preheader_block), step, update, latch))
    return result


def _defining_add(value: Value, loop: Loop) -> BinaryInst | None:
    for block in loop.blocks:
        for inst in block.instructions:
            if inst.dest is value:
                if isinstance(inst, BinaryInst) and inst.opcode is Opcode.ADD:
                    return inst
                return None
    return None

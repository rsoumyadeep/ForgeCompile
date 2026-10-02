"""simplifycfg: control-flow graph cleanup.

**Motivation.** Lowering creates many small blocks (``for.latch``,
``if.end``, ``and.end``), and folding leaves straight-line chains of them
joined by unconditional jumps. Each block boundary costs a ``jump`` at run
time, and every pass that iterates over blocks pays for it too.

**Transformation** (repeated until nothing changes):
1. ``br c, X, X`` (both targets equal) becomes ``jump X``.
2. ``br true/false`` becomes ``jump`` (also done by constfold; repeated here
   so the pass works on its own).
3. **Merge** block S into its predecessor P when P ends in ``jump S``, S has
   no other predecessor, and S is not the entry. S's phis can only have one
   input, so they are replaced by that input. Phis in S's successors are
   retargeted from S to P.
4. **Forward** a block E that holds only ``jump T``: each predecessor of E
   jumps straight to T instead. This is skipped when T has phis and the
   predecessor already reaches T directly, since the phi would then need two
   different inputs for one edge.
5. Unreachable blocks are deleted.

**Correctness.** Every rewrite preserves the set of execution paths up to the
removal of jump-only blocks. Phi inputs are rewired to the new predecessor, so
each phi still gets the same value along the same path.

**Complexity.** O(k * (blocks + edges)).
"""

from __future__ import annotations

from forgecompile.analysis.cfg import predecessors, remove_unreachable_blocks
from forgecompile.ir.function import BasicBlock, Function, Module
from forgecompile.ir.instructions import BranchInst, JumpInst, PhiInst
from forgecompile.ir.values import Constant
from forgecompile.optimization.pass_manager import FunctionPass, PassResult, register_pass
from forgecompile.optimization.utils import Substitution, replace_terminator_with_jump


def _retarget_phis(block: BasicBlock, old: BasicBlock, new: BasicBlock) -> None:
    for phi in block.phis():
        phi.blocks = [new if b is old else b for b in phi.blocks]


@register_pass
class SimplifyCFG(FunctionPass):
    name = "simplifycfg"
    description = "merge straight-line blocks, skip jump-only blocks, fold trivial branches"

    def run_on_function(self, fn: Function, module: Module) -> PassResult:
        result = PassResult()
        while self._sweep(fn, result):
            result.changed = True
        return result

    def _sweep(self, fn: Function, result: PassResult) -> bool:
        for block in fn.blocks:
            term = block.terminator
            if isinstance(term, BranchInst):
                if term.true_target is term.false_target:
                    replace_terminator_with_jump(block, term.true_target)
                    result.stats["branches"] += 1
                    return True
                if isinstance(term.cond, Constant):
                    taken = term.true_target if term.cond.value else term.false_target
                    replace_terminator_with_jump(block, taken)
                    result.stats["branches"] += 1
                    remove_unreachable_blocks(fn)
                    return True
        preds = predecessors(fn)
        for block in fn.blocks:
            if self._try_merge(fn, block, preds, result) or self._try_forward(
                fn, block, preds, result
            ):
                return True
        removed = remove_unreachable_blocks(fn)
        result.stats["blocks_removed"] += removed
        return removed > 0

    def _try_merge(
        self,
        fn: Function,
        pred: BasicBlock,
        preds: dict[BasicBlock, list[BasicBlock]],
        result: PassResult,
    ) -> bool:
        term = pred.terminator
        if not isinstance(term, JumpInst):
            return False
        succ = term.target
        if succ is pred or succ is fn.entry or preds[succ] != [pred]:
            return False
        subst = Substitution()
        for phi in succ.phis():
            assert phi.dest is not None
            subst.add(phi.dest, phi.operands[0])  # single predecessor: single input
        pred.remove(term)
        for inst in succ.instructions:
            if isinstance(inst, PhiInst):
                continue
            pred.append(inst)
        for next_block in succ.successors:
            _retarget_phis(next_block, succ, pred)
        fn.remove_block(succ)
        subst.apply(fn)
        result.stats["merged"] += 1
        return True

    def _try_forward(
        self,
        fn: Function,
        block: BasicBlock,
        preds: dict[BasicBlock, list[BasicBlock]],
        result: PassResult,
    ) -> bool:
        if block is fn.entry or len(block.instructions) != 1:
            return False
        term = block.terminator
        if not isinstance(term, JumpInst) or term.target is block:
            return False
        target = term.target
        incoming = preds[block]
        if not incoming:
            return False
        if target.phis() and any(p in preds[target] or p is target for p in incoming):
            return False
        for pred in incoming:
            pred_term = pred.terminator
            assert pred_term is not None
            pred_term.replace_target(block, target)
        for phi in target.phis():
            value = phi.value_from(block)
            phi.remove_incoming(block)
            for pred in incoming:
                phi.add_incoming(value, pred)
        fn.remove_block(block)
        result.stats["forwarded"] += 1
        return True

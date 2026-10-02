"""bce: bounds-check elimination for counted loops.

**Motivation.** MiniLang checks every array index at run time (D-010). In the
most common loop, ``for i in 0..N { a[i] ... }`` with ``a: [T; N]``, every
check ``boundscheck %i, N`` is provably redundant: the loop condition already
guarantees ``0 <= i < N``.

**Transformation.** For a loop whose header ends in::

    %c = icmp lt %i, END        ; END a constant
    br %c, body, exit           ; body inside the loop, exit outside

where ``%i = phi [init, pre], [%i + step, latch]`` is a basic induction
variable with constant ``init >= 0`` and constant ``step > 0``, delete every
``boundscheck %i, N`` with ``END <= N`` in a block dominated by ``body``.

**Correctness proof sketch.** Inside ``body``, the most recent header test
took the true edge, so ``%i < END <= N``. ``%i`` only changes at the header
(it is the phi), so this holds everywhere ``body`` dominates. Lower bound:
``%i`` starts at ``init >= 0`` and only grows by ``step > 0``. It cannot wrap
around, because each update starts from ``%i < END`` and the pass requires
``END - 1 + step <= INT_MAX``. So ``0 <= %i < N`` and the check can never
fire. We also require ``body``'s only predecessor to be the header, so the
true edge is the only way in.

**Complexity.** O(n) per loop.

**Limitation.** Only checks on the IV itself (``a[i]``), not on expressions such
as ``a[i + 1]`` or ``a[2*i]``. That would need range analysis.
"""

from __future__ import annotations

from forgecompile.analysis.dominators import DominatorTree
from forgecompile.analysis.loops import basic_induction_variables, find_loops, preheader
from forgecompile.ir.function import Function, Module
from forgecompile.ir.instructions import BoundsCheckInst, BranchInst, CmpPred, CompareInst
from forgecompile.ir.values import Constant, Register
from forgecompile.optimization.pass_manager import FunctionPass, PassResult, register_pass
from forgecompile.optimization.utils import delete_instruction
from forgecompile.runtime.semantics import INT_MAX


@register_pass
class BoundsCheckElimination(FunctionPass):
    name = "bce"
    description = "remove bounds checks on loop induction variables proven in range"

    def run_on_function(self, fn: Function, module: Module) -> PassResult:
        result = PassResult()
        domtree = DominatorTree(fn)
        preds = domtree.preds
        defs = {inst.dest: inst for inst in fn.instructions() if inst.dest is not None}
        for loop in find_loops(fn, domtree):
            pre = preheader(loop, preds)
            term = loop.header.terminator
            if (
                pre is None
                or not isinstance(term, BranchInst)
                or not isinstance(term.cond, Register)
            ):
                continue
            body, exit_block = term.true_target, term.false_target
            if body not in loop.blocks or exit_block in loop.blocks or preds[body] != [loop.header]:
                continue
            cmp = defs.get(term.cond)
            if not (isinstance(cmp, CompareInst) and cmp.pred is CmpPred.LT):
                continue
            if not isinstance(cmp.rhs, Constant):
                continue
            end = int(cmp.rhs.value)
            for iv in basic_induction_variables(loop, pre):
                if cmp.lhs is not iv.phi.dest or not isinstance(iv.init, Constant):
                    continue
                if int(iv.init.value) < 0 or iv.step <= 0 or end - 1 + iv.step > INT_MAX:
                    continue
                for block in loop.blocks:
                    if not domtree.dominates(body, block):
                        continue
                    for inst in list(block.instructions):
                        if (
                            isinstance(inst, BoundsCheckInst)
                            and inst.index is iv.phi.dest
                            and end <= inst.length
                        ):
                            delete_instruction(inst)
                            result.stats["removed"] += 1
        result.changed = bool(result.stats)
        return result

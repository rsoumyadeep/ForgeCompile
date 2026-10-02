"""constfold: constant folding with SSA constant propagation.

**Motivation.** Lowering and the program itself leave computations whose
inputs are all compile-time constants, such as ``mul 0, 4`` from ``m[0]``,
``3 * 60``, or a ``while true`` condition. Computing them once at compile time
removes work from every execution.

**Transformation.** Repeat until nothing changes:

* an instruction whose operands are all constants is evaluated with the
  *same* code the interpreter uses (``ir/evaluate.py``). Its register is then
  replaced by the constant everywhere, which in SSA *is* constant propagation,
  since every use names this one definition;
* a phi whose inputs are all the same constant becomes that constant;
* ``br true/false`` becomes ``jump``, and the dead edge's phi inputs are
  removed;
* ``boundscheck c, n`` with a constant ``0 <= c < n`` is deleted;
* blocks that are no longer reachable are deleted.

**Correctness.**
- Folding uses the run-time semantics exactly.
- Operations that would trap, such as ``sdiv x, 0`` with both operands constant,
  are *not* folded, so the trap still happens at run time.
- Out-of-range constant bounds checks are kept for the same reason.

**Complexity.** O(k * n), where k (the number of sweeps until no change) is small
in practice.

**Limitation.** It is not *conditional*. A value that is constant only because
some branch can never execute (``x = 1; if false { x = 2; }`` before the
branch is folded) needs an extra sweep, and loop-carried constants
(``phi [1, entry], [%x, latch]`` where ``%x`` is the same phi) are found by
``sccp`` rather than here.
"""

from __future__ import annotations

from forgecompile.analysis.cfg import remove_unreachable_blocks
from forgecompile.ir.function import Function, Module
from forgecompile.ir.instructions import BoundsCheckInst, BranchInst, PhiInst
from forgecompile.ir.values import Constant
from forgecompile.optimization.pass_manager import FunctionPass, PassResult, register_pass
from forgecompile.optimization.utils import (
    Substitution,
    delete_instruction,
    fold,
    replace_terminator_with_jump,
    trivial_phi_value,
)


@register_pass
class ConstantFolding(FunctionPass):
    name = "constfold"
    description = "fold constant expressions, constant branches and in-range constant bounds checks"

    def run_on_function(self, fn: Function, module: Module) -> PassResult:
        result = PassResult()
        while self._sweep(fn, result):
            result.changed = True
        return result

    def _sweep(self, fn: Function, result: PassResult) -> bool:
        subst = Substitution()
        changed = False
        for block in list(fn.blocks):
            for inst in list(block.instructions):
                # Resolve operands through substitutions made earlier in this sweep.
                for i, op in enumerate(inst.operands):
                    inst.operands[i] = subst.resolve(op)
                if isinstance(inst, PhiInst):
                    value = trivial_phi_value(inst)
                    if isinstance(value, Constant) and inst.dest is not None:
                        subst.add(inst.dest, value)
                        delete_instruction(inst)
                        result.stats["phis"] += 1
                        changed = True
                elif isinstance(inst, BranchInst) and isinstance(inst.cond, Constant):
                    taken = inst.true_target if inst.cond.value else inst.false_target
                    replace_terminator_with_jump(block, taken)
                    result.stats["branches"] += 1
                    changed = True
                elif isinstance(inst, BoundsCheckInst) and isinstance(inst.index, Constant):
                    if 0 <= inst.index.value < inst.length:
                        delete_instruction(inst)
                        result.stats["boundschecks"] += 1
                        changed = True
                elif inst.dest is not None:
                    value = fold(inst)
                    if value is not None:
                        subst.add(inst.dest, value)
                        delete_instruction(inst)
                        result.stats["folded"] += 1
                        changed = True
        subst.apply(fn)
        removed = remove_unreachable_blocks(fn)
        if removed:
            result.stats["blocks_removed"] += removed
            changed = True
        return changed

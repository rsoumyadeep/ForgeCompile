"""licm: loop-invariant code motion.

**Motivation.** A computation inside a loop whose operands do not change from
one iteration to the next produces the same value every time. Typical examples
are ``n * 3`` in a loop over ``i``, or a row offset ``i * C`` in the inner
``j`` loop of a nested loop. Computing it once, before the loop, saves
(trip count - 1) evaluations.

**Transformation.** Loops are processed innermost first. For each loop:
1. Ensure a preheader exists.
2. Repeat until nothing changes: an instruction in the loop is *invariant* if
   it is speculatable (see below) and every operand is a constant, defined
   outside the loop, or already hoisted. Invariant instructions are moved to
   the end of the preheader, in their original order.

Hoisting from an inner loop puts code in that loop's preheader, which belongs
to the outer loop. The outer loop can then hoist it again.

**Correctness.**
- *Speculation safety.* A hoisted instruction runs even if the loop body would
  not, for example when a loop runs zero times. Only instructions with no side
  effects, no possible trap and no memory read may move: pure arithmetic,
  compares, conversions, ``ptradd``, and division by a non-zero constant. Loads
  stay, because a store in the loop could change memory. Divisions by values
  that might be zero stay, because hoisting would create a trap the original
  program might not have.
- *Dominance.* An operand defined outside the loop dominates its use inside
  the loop, so it also dominates the preheader. The original instruction
  order is kept, so hoisted values are defined before their hoisted users.

**Complexity.** O(k * n) per loop.

**Limitation.** No hoisting of loads (that needs alias analysis), and no
sinking of code into loop exits.
"""

from __future__ import annotations

from forgecompile.analysis.loops import ensure_preheader, find_loops
from forgecompile.ir.function import Function, Module
from forgecompile.ir.values import Register
from forgecompile.optimization.pass_manager import FunctionPass, PassResult, register_pass
from forgecompile.optimization.utils import is_speculatable


@register_pass
class LoopInvariantCodeMotion(FunctionPass):
    name = "licm"
    description = "hoist loop-invariant pure computations into loop preheaders"

    def run_on_function(self, fn: Function, module: Module) -> PassResult:
        result = PassResult()
        # Create all preheaders first (this changes the CFG), then recompute loops so
        # that block sets include the new preheaders of inner loops.
        for loop in find_loops(fn):
            _, created = ensure_preheader(fn, loop)
            if created:
                result.stats["preheaders"] += 1
        for loop in find_loops(fn):  # innermost first
            pre, _ = ensure_preheader(fn, loop)
            defined_inside: set[Register] = {
                inst.dest
                for block in loop.blocks
                for inst in block.instructions
                if inst.dest is not None
            }
            moved = True
            while moved:
                moved = False
                for block in [b for b in fn.blocks if b in loop.blocks]:
                    for inst in block.body():
                        if not is_speculatable(inst):
                            continue
                        if any(
                            isinstance(op, Register) and op in defined_inside
                            for op in inst.operands
                        ):
                            continue
                        block.remove(inst)
                        pre.insert_before_terminator(inst)
                        if inst.dest is not None:
                            defined_inside.discard(inst.dest)
                        result.stats["hoisted"] += 1
                        moved = True
        result.changed = bool(result.stats)
        return result

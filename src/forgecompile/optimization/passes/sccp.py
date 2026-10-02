"""sccp: sparse conditional constant propagation (Wegman & Zadeck, 1991).

**Motivation.** Plain folding (``constfold``) misses constants that flow around
loops, or that are constant only because some branch never executes::

    let x = 1;
    while c { if x != 1 { x = 2; } }      // x is always 1: the `if` body is dead
                                          // and x's loop phi is constant

To prove x constant you must know the ``if`` body never runs, and to know
that you must know x is constant. SCCP solves both problems *together* by
optimistic fixed-point iteration.

**Lattice** for each register::

          TOP          (no information yet: "might still be any single constant")
     ...  c1  c2  ...  (exactly this constant)
         BOTTOM        (overdefined: not a compile-time constant)

Values only move down, and the lattice has height 3, so each register changes
at most twice. That bounds the work.

**Algorithm.** Two worklists:
* *CFG worklist*: edges found executable. The first time a block becomes
  executable, all its instructions are evaluated.
* *SSA worklist*: registers whose lattice value dropped. Their uses in
  executable blocks are re-evaluated.

Phis meet the values of their *executable* incoming edges only, which is
where the "conditional" in the name comes from. A branch whose condition is
a known constant marks only one outgoing edge executable. Undef is treated as
TOP, since any value is a legal choice for it.

**Rewrite.**
- Registers with a constant value are replaced by that constant, and their
  instructions are deleted when that is safe.
- Branches on constants become jumps.
- Never-executed blocks become unreachable and are deleted.

**Correctness.** The analysis is a monotone fixed point over the lattice, so
the final values are sound: a register marked constant has that value on every
execution. Operations that would trap evaluate to BOTTOM, so they are kept.

**Complexity.** O(instructions + edges) lattice steps, times the cost of one
evaluation.
"""

from __future__ import annotations

from typing import Any

from forgecompile.analysis.cfg import remove_unreachable_blocks
from forgecompile.ir.function import BasicBlock, Function, Module
from forgecompile.ir.instructions import (
    BINARY_OPCODES,
    UNARY_OPCODES,
    BranchInst,
    CompareInst,
    Instruction,
    JumpInst,
    PhiInst,
)
from forgecompile.ir.values import Constant, Register, Undef, Value
from forgecompile.optimization.pass_manager import FunctionPass, PassResult, register_pass
from forgecompile.optimization.utils import (
    Substitution,
    compute_uses,
    delete_instruction,
    fold,
    is_removable_if_unused,
    replace_terminator_with_jump,
)


class _Top:
    def __repr__(self) -> str:
        return "TOP"


class _Bottom:
    def __repr__(self) -> str:
        return "BOTTOM"


TOP: Any = _Top()
BOTTOM: Any = _Bottom()
# A lattice value is TOP, BOTTOM or a Constant.


def _meet(a: Any, b: Any) -> Any:
    if a is TOP:
        return b
    if b is TOP:
        return a
    if a is BOTTOM or b is BOTTOM:
        return BOTTOM
    return a if a == b else BOTTOM


class _SCCPSolver:
    def __init__(self, fn: Function) -> None:
        self.fn = fn
        self.values: dict[Register, Any] = {}
        self.executable_edges: set[tuple[BasicBlock, BasicBlock]] = set()
        self.executable_blocks: set[BasicBlock] = set()
        self.uses = compute_uses(fn)
        for param in fn.params:
            self.values[param] = BOTTOM

    def value_of(self, operand: Value) -> Any:
        if isinstance(operand, Constant):
            return operand
        if isinstance(operand, Undef) or not isinstance(operand, Register):
            return TOP
        return self.values.get(operand, TOP)

    def solve(self) -> None:
        cfg_work: list[tuple[BasicBlock | None, BasicBlock]] = [(None, self.fn.entry)]
        ssa_work: list[Register] = []

        def set_value(reg: Register, new: Any) -> None:
            old = self.values.get(reg, TOP)
            if new is old or (isinstance(new, Constant) and new == old):
                return
            self.values[reg] = new
            ssa_work.append(reg)

        def visit(inst: Instruction) -> None:
            block = inst.block
            assert block is not None
            if isinstance(inst, PhiInst):
                assert inst.dest is not None
                merged: Any = TOP
                for value, pred in inst.incoming:
                    if (pred, block) in self.executable_edges:
                        merged = _meet(merged, self.value_of(value))
                set_value(inst.dest, merged)
            elif isinstance(inst, BranchInst):
                cond = self.value_of(inst.cond)
                if cond is TOP:
                    return
                if cond is BOTTOM:
                    targets = [inst.true_target, inst.false_target]
                else:
                    targets = [inst.true_target if cond.value else inst.false_target]
                for target in targets:
                    cfg_work.append((block, target))
            elif isinstance(inst, JumpInst):
                cfg_work.append((block, inst.target))
            elif inst.dest is not None:
                set_value(inst.dest, self.evaluate(inst))

        while cfg_work or ssa_work:
            while cfg_work:
                source, target = cfg_work.pop()
                if source is not None:
                    if (source, target) in self.executable_edges:
                        continue
                    self.executable_edges.add((source, target))
                first_visit = target not in self.executable_blocks
                self.executable_blocks.add(target)
                for inst in target.instructions:
                    if first_visit or isinstance(inst, PhiInst):
                        visit(inst)
            while ssa_work:
                reg = ssa_work.pop()
                for user in self.uses.get(reg, []):
                    if user.block in self.executable_blocks:
                        visit(user)

    def evaluate(self, inst: Instruction) -> Any:
        is_computable = (
            inst.opcode in BINARY_OPCODES
            or inst.opcode in UNARY_OPCODES
            or isinstance(inst, CompareInst)
        )
        if not is_computable:
            return BOTTOM  # loads, calls, allocas, ...
        operand_values = [self.value_of(op) for op in inst.operands]
        if any(v is BOTTOM for v in operand_values):
            return BOTTOM
        if any(v is TOP for v in operand_values):
            return TOP
        # All operands constant: fold a temporary copy (fold() must not mutate inst).
        saved = list(inst.operands)
        inst.operands[:] = operand_values
        try:
            folded = fold(inst)
        finally:
            inst.operands[:] = saved
        return folded if isinstance(folded, Constant) else BOTTOM  # None => would trap


@register_pass
class SparseConditionalConstantPropagation(FunctionPass):
    name = "sccp"
    description = "propagate constants through phis and prune never-executed branches"

    def run_on_function(self, fn: Function, module: Module) -> PassResult:
        solver = _SCCPSolver(fn)
        solver.solve()
        result = PassResult()
        subst = Substitution()
        for reg, value in solver.values.items():
            if isinstance(value, Constant) and reg not in fn.params:
                subst.add(reg, value)
        for block in fn.blocks:
            if block not in solver.executable_blocks:
                continue
            for inst in list(block.instructions):
                is_constant = inst.dest is not None and inst.dest in subst.mapping
                if is_constant and is_removable_if_unused(inst):
                    delete_instruction(inst)
                    result.stats["constants"] += 1
            term = block.terminator
            if isinstance(term, BranchInst):
                live = [t for t in term.targets if (block, t) in solver.executable_edges]
                if len(live) == 1 and len(term.targets) == 2:
                    replace_terminator_with_jump(block, live[0])
                    result.stats["branches"] += 1
        subst.apply(fn)
        removed = remove_unreachable_blocks(fn)
        result.stats["blocks_removed"] += removed
        result.changed = bool(result.stats)
        return result

"""strength: induction-variable strength reduction (multiplication -> addition).

**Motivation.** Flattened array indexing turns ``m[i][j]`` into
``i * C + j``. Inside a loop over ``i``, the product ``i * C`` takes the
values ``init*C, (init+step)*C, ...``, so it can be maintained by *adding*
``step*C`` each iteration instead of multiplying. This is the classic loop
strength reduction (Allen, Cocke & Kennedy).

**Transformation.** For a loop with a preheader and a single latch, and for
each basic induction variable ``%i = phi [init, pre], [%i + step, latch]``,
every ``%t = mul %i, k`` (``k`` constant) in the loop is replaced by a new
induction variable::

    preheader:  %s.init = mul init, k            (folded if init is constant)
    header:     %s = phi [%s.init, pre], [%s.next, latch]
    latch:      %s.next = add %s, step*k

Uses of ``%t`` become ``%s``. Several multiplies of the same IV by the same
``k`` share one new IV.

**Correctness.** By induction, ``%s == %i * k`` at the start of every
iteration. Initially ``s = init*k``, and each latch adds ``step*k`` while ``%i``
adds ``step``. All arithmetic wraps modulo 2^64, and the identity holds in
modular arithmetic, so overflow does not break it.

**Profitability guard.** One add per iteration replaces one multiply per
*execution of the multiply*. If the multiply sits in a conditional block that
rarely runs, the "optimization" adds work. The pass only rewrites multiplies
whose block dominates the latch, i.e. those that run on every iteration.

**Honest caveat.** On modern x86, ``imul`` costs about 3 cycles and LLVM's own
loop strength reduction runs on the generated code anyway. The native benefit
is expected to be small. The benefit under the interpreter cost model
(mul = 3, add = 1) is real but partly an artefact of those weights.
"""

from __future__ import annotations

from forgecompile.analysis.dominators import DominatorTree
from forgecompile.analysis.loops import basic_induction_variables, ensure_preheader, find_loops
from forgecompile.ir.function import BasicBlock, Function, Module
from forgecompile.ir.instructions import BinaryInst, Opcode, PhiInst
from forgecompile.ir.values import Constant, IRType, Register, Value, const_int
from forgecompile.optimization.pass_manager import FunctionPass, PassResult, register_pass
from forgecompile.optimization.utils import Substitution, delete_instruction
from forgecompile.runtime.semantics import wrap


@register_pass
class StrengthReduction(FunctionPass):
    name = "strength"
    description = "replace induction-variable multiplies (i*k) with incrementally updated phis"

    def run_on_function(self, fn: Function, module: Module) -> PassResult:
        result = PassResult()
        for loop in find_loops(fn):
            ensure_preheader(fn, loop)
        loops = find_loops(fn)
        domtree = DominatorTree(fn)
        subst = Substitution()
        for loop in loops:
            pre, _ = ensure_preheader(fn, loop)
            for iv in basic_induction_variables(loop, pre):
                assert iv.phi.dest is not None
                new_ivs: dict[int, Register] = {}
                for block in [b for b in fn.blocks if b in loop.blocks]:
                    if not domtree.dominates(block, iv.latch):
                        continue  # profitability guard: must run every iteration
                    for inst in list(block.body()):
                        k = _multiplier(inst, iv.phi.dest)
                        if k is None or inst.dest is None:
                            continue
                        reg = new_ivs.get(k)
                        if reg is None:
                            reg = self._make_iv(fn, iv.phi, iv.init, iv.step, k, pre, iv.latch)
                            new_ivs[k] = reg
                            result.stats["new_ivs"] += 1
                        subst.add(inst.dest, reg)
                        delete_instruction(inst)
                        result.stats["reduced"] += 1
        subst.apply(fn)
        result.changed = bool(result.stats)
        return result

    @staticmethod
    def _make_iv(
        fn: Function,
        phi: PhiInst,
        init: Value,
        step: int,
        k: int,
        pre: BasicBlock,
        latch: BasicBlock,
    ) -> Register:
        assert phi.dest is not None
        base = f"{phi.dest.name}.x{k}" if k >= 0 else f"{phi.dest.name}.xm{-k}"
        if isinstance(init, Constant):
            start: Value = const_int(wrap(int(init.value) * k))
        else:
            start = fn.new_register(f"{base}.init", IRType.I64)
            pre.insert_before_terminator(BinaryInst(Opcode.MUL, start, init, const_int(k)))
        new_phi_reg = fn.new_register(base, IRType.I64)
        next_reg = fn.new_register(f"{base}.next", IRType.I64)
        header = phi.block
        assert header is not None
        new_phi = PhiInst(new_phi_reg, [(start, pre), (next_reg, latch)])
        header.insert(0, new_phi)
        latch.insert_before_terminator(
            BinaryInst(Opcode.ADD, next_reg, new_phi_reg, const_int(wrap(step * k)))
        )
        return new_phi_reg


def _multiplier(inst: object, iv: Register) -> int | None:
    if not isinstance(inst, BinaryInst) or inst.opcode is not Opcode.MUL:
        return None
    a, b = inst.operands
    if a is iv and isinstance(b, Constant):
        return int(b.value)
    if b is iv and isinstance(a, Constant):
        return int(a.value)
    return None

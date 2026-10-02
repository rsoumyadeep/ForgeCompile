"""copyprop: copy propagation and trivial-phi elimination.

**Motivation.** Lowering assigns every variable through ``copy``, and SSA
construction keeps those copies (``%total.3 = copy %t3``). Each copy is pure
overhead: an instruction that only renames a value.

**Transformation.**
* ``%a = copy v``: replace every use of ``%a`` with ``v`` and delete the copy.
* A *trivial phi*, whose inputs are all the same value ``v`` (ignoring references
  to itself and ``undef``), is replaced by ``v`` and deleted. Removing one
  trivial phi can make another trivial, so this repeats until nothing changes.

**Correctness (SSA argument).**
- A copy's operand is defined before the copy and dominates it, so it
  dominates every use of ``%a``.
- If every incoming edge of a phi carries ``v``, then ``v``'s definition
  dominates the end of every predecessor, and hence dominates the phi's block.
- Either way, the replacement is the same value and dominates all uses, so the
  SSA dominance property is preserved. The verifier re-checks this after the pass.

**Complexity.** O(k * n), with k usually 1-2 sweeps.
"""

from __future__ import annotations

from forgecompile.ir.function import Function, Module
from forgecompile.ir.instructions import Opcode, PhiInst
from forgecompile.optimization.pass_manager import FunctionPass, PassResult, register_pass
from forgecompile.optimization.utils import Substitution, delete_instruction, trivial_phi_value


@register_pass
class CopyPropagation(FunctionPass):
    name = "copyprop"
    description = "replace uses of copies by their source; remove trivial phis"

    def run_on_function(self, fn: Function, module: Module) -> PassResult:
        result = PassResult()
        while True:
            subst = Substitution()
            for inst in list(fn.instructions()):
                if inst.dest is None:
                    continue
                if inst.opcode is Opcode.COPY:
                    subst.add(inst.dest, subst.resolve(inst.operands[0]))
                    delete_instruction(inst)
                    result.stats["copies"] += 1
                elif isinstance(inst, PhiInst):
                    resolved = [subst.resolve(v) for v in inst.operands]
                    inst.operands[:] = resolved
                    value = trivial_phi_value(inst)
                    if value is not None:
                        subst.add(inst.dest, value)
                        delete_instruction(inst)
                        result.stats["phis"] += 1
            if not subst:
                return result
            subst.apply(fn)
            result.changed = True

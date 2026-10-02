"""dce: dead code elimination (mark and sweep over SSA def-use edges).

**Motivation.** Other passes leave computations whose results are never used,
such as a folded value's inputs or dead phis left by semi-pruned SSA. Removing
them saves time, and fewer instructions also speed up the passes that follow.

**Transformation.** This is "aggressive" DCE in the sense that liveness is
proved, not assumed:
1. Roots: every instruction that must run regardless of its result. These are
   anything with side effects or a possible trap (stores, calls, prints,
   bounds checks, ``sdiv``/``srem`` by a possibly-zero value) and terminators.
2. Mark: an instruction is live if it is a root, or if it defines a register
   used by a live instruction (worklist over operands).
3. Sweep: delete every unmarked instruction that is safe to remove.

Mark-and-sweep removes dead *cycles* that a simple "delete if no uses" loop
misses, for example two loop phis that only feed each other.

**Correctness.** Only instructions with no observable effect are deleted:
- pure ones;
- ``load`` and ``alloca``: a load cannot trap, because bounds are checked by a
  separate instruction;
- ``sdiv``/``srem`` by a non-zero constant.

A division that might trap is a root, because removing it would remove the
trap. That is behaviour that is observable in MiniLang (DECISIONS D-010/D-018).

**Complexity.** O(n).

**Limitation.** No control dependence: a branch whose two sides both reach the
same point and compute nothing is not removed (simplifycfg handles some such
cases). No dead-store elimination.
"""

from __future__ import annotations

from forgecompile.ir.function import Function, Module
from forgecompile.ir.instructions import Instruction
from forgecompile.ir.values import Register
from forgecompile.optimization.pass_manager import FunctionPass, PassResult, register_pass
from forgecompile.optimization.utils import delete_instruction, is_removable_if_unused


@register_pass
class DeadCodeElimination(FunctionPass):
    name = "dce"
    description = "remove instructions whose results are never used and that have no effects"

    def run_on_function(self, fn: Function, module: Module) -> PassResult:
        definitions: dict[Register, Instruction] = {}
        live: set[Instruction] = set()
        worklist: list[Instruction] = []
        for inst in fn.instructions():
            if inst.dest is not None:
                definitions[inst.dest] = inst
            if not is_removable_if_unused(inst):
                live.add(inst)
                worklist.append(inst)
        while worklist:
            inst = worklist.pop()
            for op in inst.operands:
                if isinstance(op, Register):
                    definition = definitions.get(op)
                    if definition is not None and definition not in live:
                        live.add(definition)
                        worklist.append(definition)
        result = PassResult()
        for inst in list(fn.instructions()):
            if inst not in live:
                delete_instruction(inst)
                result.stats["phis" if inst.opcode.value == "phi" else "instructions"] += 1
                result.changed = True
        return result

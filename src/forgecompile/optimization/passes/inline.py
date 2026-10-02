"""inline: function inlining of small, non-recursive callees.

**Motivation.** A call costs argument passing, a frame and a return, and it
hides the callee's body from every other pass. After inlining, constants
flow from arguments into the callee body, CSE sees across the old call
boundary, and a callee loop becomes optimizable in its calling context.

**Transformation.** For ``%r = call @f(a1, ..., an)`` where ``f`` is small
(at most :data:`INLINE_THRESHOLD` instructions) and not recursive:
1. Split the caller's block after the call. Everything after the call moves
   to a new continuation block ``<block>.cont``.
2. Clone ``f``'s blocks into the caller with fresh register names
   (``%f.x``), mapping ``f``'s parameters to the arguments.
3. Replace each ``ret v`` in the clone with ``jump <block>.cont``. If ``f``
   returns a value, ``%r`` becomes a phi of the returned values in the
   continuation block, or simply the value if there is a single return.
4. Move cloned ``alloca``s to the caller's entry block, so inlining into a
   loop does not grow the stack. The callee's ``memzero`` stays at its original
   position, so each inlined "call" still gets zeroed arrays, as a real call
   would.

**Correctness.**
- The cloned body runs exactly the instructions the call would have run, with
  the same arguments: arrays by reference (the same pointer), scalars by value.
  SSA registers are never reassigned, so parameter values cannot be clobbered.
- The continuation block is dominated by the cloned returns, so the uses of
  ``%r`` stay dominated by its new definition.

**Heuristic.** Size threshold only: there is no call-site profiling. Recursive
functions (any function on a call-graph cycle) are never inlined, which
guarantees the pass terminates. The threshold is a magic number by nature; it
is a named constant here so that ML/RL experiments can study it.

**Limitation.** Code growth is not bounded globally. Each callee is small, but
a function with many call sites grows proportionally.
"""

from __future__ import annotations

import copy

from forgecompile.ir.function import BasicBlock, Function, Module
from forgecompile.ir.instructions import (
    AllocaInst,
    BranchInst,
    CallInst,
    Instruction,
    JumpInst,
    PhiInst,
    ReturnInst,
)
from forgecompile.ir.values import Register, Undef, Value
from forgecompile.optimization.pass_manager import Pass, PassResult, register_pass
from forgecompile.optimization.utils import Substitution, instruction_count

INLINE_THRESHOLD = 40  # static instruction count of the callee


def recursive_functions(module: Module) -> set[str]:
    """Names of functions that can (transitively) call themselves."""
    calls: dict[str, set[str]] = {
        name: {
            inst.callee
            for inst in fn.instructions()
            if isinstance(inst, CallInst) and inst.callee in module.functions
        }
        for name, fn in module.functions.items()
    }
    recursive: set[str] = set()
    for start in calls:
        stack = list(calls[start])
        seen: set[str] = set()
        while stack:
            name = stack.pop()
            if name == start:
                recursive.add(start)
                break
            if name not in seen:
                seen.add(name)
                stack.extend(calls[name])
    return recursive


def _clone(
    inst: Instruction, values: dict[Value, Value], blocks: dict[BasicBlock, BasicBlock]
) -> Instruction:
    new = copy.copy(inst)
    new.block = None
    new.operands = [values.get(op, op) for op in inst.operands]
    if inst.dest is not None:
        mapped = values[inst.dest]
        assert isinstance(mapped, Register)
        new.dest = mapped
    if isinstance(inst, PhiInst):
        assert isinstance(new, PhiInst)
        new.blocks = [blocks[b] for b in inst.blocks]
    elif isinstance(inst, JumpInst):
        assert isinstance(new, JumpInst)
        new.target = blocks[inst.target]
    elif isinstance(inst, BranchInst):
        assert isinstance(new, BranchInst)
        new.true_target = blocks[inst.true_target]
        new.false_target = blocks[inst.false_target]
    return new


def inline_call(caller: Function, call: CallInst, callee: Function) -> None:
    block = call.block
    assert block is not None
    index = block.instructions.index(call)

    # 1. Split: everything after the call moves to a continuation block.
    cont = caller.new_block(f"{block.label}.cont")
    caller.blocks.remove(cont)
    caller.blocks.insert(caller.blocks.index(block) + 1, cont)
    for inst in block.instructions[index + 1 :]:
        cont.insert(len(cont.instructions), inst)
    del block.instructions[index:]
    call.block = None
    for succ in cont.successors:
        for phi in succ.phis():
            phi.blocks = [cont if b is block else b for b in phi.blocks]

    # 2. Clone the callee.
    values: dict[Value, Value] = dict(zip(callee.params, call.operands, strict=True))
    blocks: dict[BasicBlock, BasicBlock] = {}
    insert_at = caller.blocks.index(cont)
    for cb in callee.blocks:
        nb = caller.new_block(f"{callee.name}.{cb.label}")
        caller.blocks.remove(nb)
        caller.blocks.insert(insert_at, nb)
        insert_at += 1
        blocks[cb] = nb
        for inst in cb.instructions:
            if inst.dest is not None:
                values[inst.dest] = caller.new_register(
                    f"{callee.name}.{inst.dest.name}", inst.dest.type
                )
    returns: list[tuple[Value, BasicBlock]] = []
    entry = caller.entry
    alloca_slot = 0
    for cb in callee.blocks:
        nb = blocks[cb]
        for inst in cb.instructions:
            if isinstance(inst, ReturnInst):
                if inst.value is not None:
                    returns.append((values.get(inst.value, inst.value), nb))
                else:
                    returns.append((Undef(callee.return_type), nb))
                nb.append(JumpInst(cont))
                continue
            new = _clone(inst, values, blocks)
            if isinstance(new, AllocaInst):
                entry.insert(alloca_slot, new)  # hoist to the caller's entry
                alloca_slot += 1
            else:
                nb.insert(len(nb.instructions), new)

    # 3. Enter the clone, and connect the return value.
    block.append(JumpInst(blocks[callee.entry]))
    if call.dest is not None:
        subst = Substitution()
        if len(returns) == 1:
            subst.add(call.dest, returns[0][0])
        elif returns:
            cont.insert(0, PhiInst(call.dest, returns))
        else:  # the callee never returns: the continuation is unreachable
            subst.add(call.dest, Undef(call.dest.type))
        subst.apply(caller)


@register_pass
class Inlining(Pass):
    name = "inline"
    description = (
        f"inline calls to non-recursive functions of at most {INLINE_THRESHOLD} instructions"
    )

    def run(self, module: Module) -> PassResult:
        result = PassResult()
        recursive = recursive_functions(module)
        for caller in module.functions.values():
            progress = True
            while progress:
                progress = False
                for inst in list(caller.instructions()):
                    if not isinstance(inst, CallInst):
                        continue
                    callee = module.functions.get(inst.callee)
                    if (
                        callee is None
                        or callee is caller
                        or callee.name in recursive
                        or instruction_count(callee) > INLINE_THRESHOLD
                    ):
                        continue
                    inline_call(caller, inst, callee)
                    result.stats["inlined"] += 1
                    progress = True
                    break  # the instruction list changed; rescan
        result.changed = bool(result.stats)
        return result

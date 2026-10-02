"""Shared helpers for optimization passes: def-use info, substitution, folding, CFG edits.

All passes operate on SSA IR. In SSA, replacing every use of register ``%r``
by a value ``v`` that is always equal to ``%r`` is valid whenever ``v`` is a
constant, or a register whose definition dominates every use of ``%r``. Every
substitution performed by these passes meets that condition, and the verifier
re-checks the dominance property after each pass.
"""

from __future__ import annotations

from collections import defaultdict

from forgecompile.ir.evaluate import eval_binary, eval_compare, eval_unary
from forgecompile.ir.function import BasicBlock, Function, Module
from forgecompile.ir.instructions import (
    BINARY_OPCODES,
    UNARY_OPCODES,
    CompareInst,
    Instruction,
    JumpInst,
    Opcode,
    PhiInst,
)
from forgecompile.ir.values import Constant, IRType, Register, Undef, Value
from forgecompile.runtime.semantics import RuntimeTrap

# ------------------------------------------------------------------ def-use


def compute_uses(fn: Function) -> dict[Register, list[Instruction]]:
    """Map each register to the instructions that use it (one entry per using instruction)."""
    uses: dict[Register, list[Instruction]] = defaultdict(list)
    for inst in fn.instructions():
        seen: set[int] = set()
        for op in inst.operands:
            if isinstance(op, Register) and id(op) not in seen:
                seen.add(id(op))
                uses[op].append(inst)
    return uses


def instruction_count(fn: Function) -> int:
    return sum(len(block.instructions) for block in fn.blocks)


def module_instruction_count(module: Module) -> int:
    return sum(instruction_count(fn) for fn in module.functions.values())


class Substitution:
    """A batch of "replace all uses of register R with value V" requests.

    Requests may chain (a -> b, then b -> 5). ``resolve`` follows chains, and
    ``apply`` rewrites every operand in one O(instructions) sweep. Batching
    avoids an O(n) scan per replacement, which would make passes quadratic.
    """

    def __init__(self) -> None:
        self.mapping: dict[Register, Value] = {}

    def __bool__(self) -> bool:
        return bool(self.mapping)

    def add(self, old: Register, new: Value) -> None:
        resolved = self.resolve(new)
        if resolved is old:
            return  # a self-substitution would be a no-op cycle
        self.mapping[old] = resolved

    def resolve(self, value: Value) -> Value:
        seen = 0
        while isinstance(value, Register) and value in self.mapping:
            value = self.mapping[value]
            seen += 1
            if seen > len(self.mapping):
                raise RuntimeError("cyclic substitution")
        return value

    def apply(self, fn: Function) -> int:
        """Rewrite all operands in ``fn``; returns the number of operands changed."""
        if not self.mapping:
            return 0
        changed = 0
        for inst in fn.instructions():
            for i, op in enumerate(inst.operands):
                if isinstance(op, Register) and op in self.mapping:
                    inst.operands[i] = self.resolve(op)
                    changed += 1
        return changed


# ------------------------------------------------------------------ constant folding


def fold(inst: Instruction) -> Value | None:
    """Return the compile-time value of ``inst`` if all of its inputs are constants.

    Returns ``None`` when the instruction cannot be folded: a non-constant
    operand, an operation with side effects, or an operation that would *trap*
    at run time (integer division by zero). A trapping operation must stay in
    the program, so that the trap still happens.
    """
    ops = inst.operands
    op = inst.opcode
    # Only constants are produced here: forwarding `copy %r` to `%r` is copy
    # propagation's job, which keeps the two passes disjoint for ablations.
    if not ops or not all(isinstance(v, Constant) for v in ops):
        return None
    values = [v.value for v in ops if isinstance(v, Constant)]
    try:
        if op in BINARY_OPCODES:
            assert inst.dest is not None
            return Constant(inst.dest.type, eval_binary(op, values[0], values[1]))
        if op in UNARY_OPCODES:
            assert inst.dest is not None
            return Constant(inst.dest.type, eval_unary(op, values[0]))
        if isinstance(inst, CompareInst):
            return Constant(IRType.I1, eval_compare(inst.pred, values[0], values[1]))
    except RuntimeTrap:
        return None
    return None


def trivial_phi_value(phi: PhiInst) -> Value | None:
    """If every incoming value is the same (ignoring references to the phi itself), return it.

    ``%x = phi [%v, a], [%v, b]`` is just ``%v``, and so is
    ``%x = phi [%v, entry], [%x, latch]`` (the loop never changes x).

    ``undef`` inputs may be ignored only when the unique value is a *constant*.
    Choosing any value for undef is a legal refinement, but a *register* ``%v``
    from a phi like ``phi [undef, entry], [%v, latch]`` is defined inside the
    loop and does not dominate the phi. Substituting it would break SSA's
    dominance property (docs/FAILURES.md, F-009).
    """
    unique: Value | None = None
    saw_undef = False
    for value in phi.operands:
        if value is phi.dest:
            continue
        if isinstance(value, Undef):
            saw_undef = True
            continue
        if unique is None:
            unique = value
        elif not _same_value(unique, value):
            return None
    if unique is None:  # only undef / self references
        return None
    if saw_undef and isinstance(unique, Register):
        return None
    return unique


def _same_value(a: Value, b: Value) -> bool:
    if isinstance(a, Register) or isinstance(b, Register):
        return a is b
    return a == b


def is_removable_if_unused(inst: Instruction) -> bool:
    """True if deleting ``inst`` cannot change behaviour when its result is unused."""
    op = inst.opcode
    if op.is_pure or op in (Opcode.LOAD, Opcode.ALLOCA):
        return True
    if op in (Opcode.SDIV, Opcode.SREM):
        divisor = inst.operands[1]
        return isinstance(divisor, Constant) and divisor.value != 0
    return False


def is_speculatable(inst: Instruction) -> bool:
    """True if ``inst`` may be executed even on paths where the original did not run.

    This requires no side effects, no traps and no memory reads, because a hoisted
    load could observe a different value. It is used by LICM.
    """
    op = inst.opcode
    if op is Opcode.PHI:
        return False
    if op.is_pure:
        return True
    if op in (Opcode.SDIV, Opcode.SREM):
        divisor = inst.operands[1]
        return isinstance(divisor, Constant) and divisor.value != 0
    return False


# ------------------------------------------------------------------ CFG edits


def remove_phi_incoming(target: BasicBlock, source: BasicBlock) -> None:
    for phi in target.phis():
        if source in phi.blocks:
            phi.remove_incoming(source)


def replace_terminator_with_jump(block: BasicBlock, target: BasicBlock) -> None:
    """Make ``block`` jump unconditionally to ``target``, fixing phis of dropped successors."""
    old = block.terminator
    assert old is not None
    for succ in old.targets:
        if succ is not target:
            remove_phi_incoming(succ, block)
    block.remove(old)
    block.append(JumpInst(target))


def delete_instruction(inst: Instruction) -> None:
    assert inst.block is not None
    inst.block.remove(inst)


def replace_instruction(old: Instruction, new: Instruction) -> None:
    """Put ``new`` where ``old`` was, keeping ``old``'s destination register."""
    block = old.block
    assert block is not None
    new.dest = old.dest
    index = block.instructions.index(old)
    block.instructions[index] = new
    new.block = block
    old.block = None

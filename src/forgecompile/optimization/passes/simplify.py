"""simplify: algebraic simplification (peephole identities) and canonicalization.

**Motivation.** Many instructions compute something trivially known even when
their operands are not constants: ``x + 0``, ``x * 1``, ``x - x``,
``not (not b)``, ``icmp eq b, true``. Removing them shortens dependence
chains and exposes further folding and CSE.

**Transformation.** For each instruction, try the identities below. A rewrite
either replaces the result with an existing value, or replaces the
instruction with a cheaper one (``mul x, -1`` becomes ``neg x``). The pass
repeats until nothing changes.

Integers (exact, since arithmetic wraps modulo 2^64)::

    x + 0, 0 + x, x - 0, x * 1, x / 1                 -> x
    x * 0, x - x, x % 1, x % -1                       -> 0
    x * -1, x / -1, 0 - x                             -> neg x      (INT_MIN / -1 == neg INT_MIN)
    neg (neg x)                                       -> x
    icmp eq/le/ge x, x -> true;   icmp ne/lt/gt x, x -> false
    not (icmp p a b)                                  -> icmp (inverse p) a b

Floats. Only identities that hold for *every* IEEE value, including -0.0, NaN
and inf, are allowed::

    x * 1.0, x / 1.0, x - (+0.0), x + (-0.0)          -> x
    fneg (fneg x)                                     -> x
    NOT allowed: x + 0.0 (-0.0 + 0.0 = +0.0), x * 0.0 (NaN, inf, -0.0),
                 x - x (NaN, inf), fcmp eq x, x (NaN), not(fcmp) (NaN)

Booleans::

    not (not b) -> b;   icmp eq b, true -> b;   icmp ne b, false -> b
    icmp eq b, false -> not b;   icmp ne b, true -> not b
    icmp ne (zext b), 0 -> b;    icmp eq (zext b), 0 -> not b

Canonicalization: for commutative operations, a constant left operand is moved
to the right (``add 1, %x`` becomes ``add %x, 1``). Later rules then only need
to check one side, and CSE sees ``1 + x`` and ``x + 1`` as the same expression.

**Complexity.** O(k * n).
"""

from __future__ import annotations

import math

from forgecompile.ir.function import Function, Module
from forgecompile.ir.instructions import (
    COMMUTATIVE,
    CmpPred,
    CompareInst,
    Instruction,
    Opcode,
    UnaryInst,
)
from forgecompile.ir.values import Constant, IRType, Register, Value, const_bool, const_int
from forgecompile.optimization.pass_manager import FunctionPass, PassResult, register_pass
from forgecompile.optimization.utils import Substitution, delete_instruction, replace_instruction


def _is_int(value: Value, k: int) -> bool:
    return isinstance(value, Constant) and value.type is IRType.I64 and value.value == k


def _is_float(value: Value, x: float) -> bool:
    """Exact float match, *including the sign of zero*."""
    return (
        isinstance(value, Constant)
        and value.type is IRType.F64
        and value.value == x
        and math.copysign(1.0, float(value.value)) == math.copysign(1.0, x)
    )


def _is_bool(value: Value, b: bool) -> bool:
    return isinstance(value, Constant) and value.type is IRType.I1 and value.value is b


class _Simplifier:
    def __init__(self, fn: Function, result: PassResult) -> None:
        self.fn = fn
        self.result = result
        self.defs: dict[Register, Instruction] = {
            inst.dest: inst for inst in fn.instructions() if inst.dest is not None
        }

    def defining(self, value: Value, opcode: Opcode) -> Instruction | None:
        if isinstance(value, Register):
            inst = self.defs.get(value)
            if inst is not None and inst.opcode is opcode and inst.block is not None:
                return inst
        return None

    def new_unary(self, opcode: Opcode, operand: Value, old: Instruction) -> UnaryInst:
        assert old.dest is not None
        return UnaryInst(opcode, old.dest, operand)

    # Each rule returns a replacement value, a replacement instruction, or None.
    def simplify(self, inst: Instruction) -> Value | Instruction | None:
        op = inst.opcode
        ops = inst.operands
        if op in COMMUTATIVE and isinstance(ops[0], Constant) and not isinstance(ops[1], Constant):
            ops[0], ops[1] = ops[1], ops[0]
            self.result.stats["canonicalized"] += 1
            self.result.changed = True
        if op is Opcode.ADD:
            return ops[0] if _is_int(ops[1], 0) else None
        if op is Opcode.SUB:
            if _is_int(ops[1], 0):
                return ops[0]
            if ops[0] is ops[1] and isinstance(ops[0], Register):
                return const_int(0)
            if _is_int(ops[0], 0):
                return self.new_unary(Opcode.NEG, ops[1], inst)
            return None
        if op is Opcode.MUL:
            if _is_int(ops[1], 1):
                return ops[0]
            if _is_int(ops[1], 0):
                return const_int(0)
            if _is_int(ops[1], -1):
                return self.new_unary(Opcode.NEG, ops[0], inst)
            return None
        if op is Opcode.SDIV:
            if _is_int(ops[1], 1):
                return ops[0]
            if _is_int(ops[1], -1):
                return self.new_unary(Opcode.NEG, ops[0], inst)
            return None
        if op is Opcode.SREM:
            return const_int(0) if _is_int(ops[1], 1) or _is_int(ops[1], -1) else None
        if op in (Opcode.NEG, Opcode.FNEG, Opcode.NOT):
            inner = self.defining(ops[0], op)
            return inner.operands[0] if inner is not None else self._not_of_compare(inst)
        if op is Opcode.FMUL or op is Opcode.FDIV:
            return ops[0] if _is_float(ops[1], 1.0) else None
        if op is Opcode.FSUB:
            return ops[0] if _is_float(ops[1], 0.0) else None
        if op is Opcode.FADD:
            return ops[0] if _is_float(ops[1], -0.0) else None
        if isinstance(inst, CompareInst) and op is Opcode.ICMP:
            return self._icmp(inst)
        return None

    def _not_of_compare(self, inst: Instruction) -> Instruction | None:
        if inst.opcode is not Opcode.NOT:
            return None
        cmp = self.defining(inst.operands[0], Opcode.ICMP)
        if cmp is None:
            return None
        assert isinstance(cmp, CompareInst) and inst.dest is not None
        return CompareInst(Opcode.ICMP, cmp.pred.inverse, inst.dest, cmp.lhs, cmp.rhs)

    def _icmp(self, inst: CompareInst) -> Value | Instruction | None:
        a, b = inst.lhs, inst.rhs
        pred = inst.pred
        if a is b and isinstance(a, Register):
            return const_bool(pred in (CmpPred.EQ, CmpPred.LE, CmpPred.GE))
        if a.type is IRType.I1:
            if (pred is CmpPred.EQ and _is_bool(b, True)) or (
                pred is CmpPred.NE and _is_bool(b, False)
            ):
                return a
            if (pred is CmpPred.EQ and _is_bool(b, False)) or (
                pred is CmpPred.NE and _is_bool(b, True)
            ):
                return self.new_unary(Opcode.NOT, a, inst)
            return None
        zext = self.defining(a, Opcode.ZEXT)
        if zext is not None and _is_int(b, 0) and pred in (CmpPred.NE, CmpPred.EQ):
            source = zext.operands[0]
            return source if pred is CmpPred.NE else self.new_unary(Opcode.NOT, source, inst)
        return None


@register_pass
class AlgebraicSimplification(FunctionPass):
    name = "simplify"
    description = "apply algebraic identities (x+0, x*1, x-x, not not b, ...) and canonicalize"

    def run_on_function(self, fn: Function, module: Module) -> PassResult:
        result = PassResult()
        while True:
            simplifier = _Simplifier(fn, result)
            subst = Substitution()
            rewrites = 0
            for inst in list(fn.instructions()):
                for i, op in enumerate(inst.operands):
                    inst.operands[i] = subst.resolve(op)
                outcome = simplifier.simplify(inst)
                if outcome is None:
                    continue
                rewrites += 1
                if isinstance(outcome, Instruction):
                    replace_instruction(inst, outcome)
                    if outcome.dest is not None:
                        simplifier.defs[outcome.dest] = outcome
                    result.stats["rewritten"] += 1
                else:
                    assert inst.dest is not None
                    subst.add(inst.dest, outcome)
                    delete_instruction(inst)
                    result.stats["eliminated"] += 1
            subst.apply(fn)
            if rewrites == 0:
                return result
            result.changed = True

"""Single source of truth for the result of IR operations on concrete values.

Used by the IR interpreter (run time) and by constant folding (compile time).
Sharing one implementation guarantees that folding ``add 2, 3`` at compile time
gives exactly what the interpreter would compute at run time: same wrap-around,
same C division, same NaN behaviour. The independent AST interpreter still
checks both against the language specification.
"""

from __future__ import annotations

from typing import Any

from forgecompile.ir.instructions import CmpPred, Opcode
from forgecompile.runtime import semantics as sem


def eval_binary(op: Opcode, a: Any, b: Any) -> Any:
    """Raises ``RuntimeTrap`` for integer division or remainder by zero."""
    if op is Opcode.ADD:
        return sem.wrap(a + b)
    if op is Opcode.SUB:
        return sem.wrap(a - b)
    if op is Opcode.MUL:
        return sem.wrap(a * b)
    if op is Opcode.SDIV:
        return sem.int_div(a, b)
    if op is Opcode.SREM:
        return sem.int_rem(a, b)
    if op is Opcode.FADD:
        return a + b
    if op is Opcode.FSUB:
        return a - b
    if op is Opcode.FMUL:
        return a * b
    if op is Opcode.FDIV:
        return sem.float_div(a, b)
    if op is Opcode.FREM:
        return sem.float_rem(a, b)
    raise ValueError(f"not a binary opcode: {op}")


def eval_unary(op: Opcode, a: Any) -> Any:
    if op is Opcode.NEG:
        return sem.wrap(-a)
    if op is Opcode.FNEG:
        return -a
    if op is Opcode.NOT:
        return not a
    if op is Opcode.SITOFP:
        return float(a)
    if op is Opcode.FPTOSI:
        return sem.float_to_int(a)
    if op is Opcode.ZEXT:
        return int(a)
    if op is Opcode.COPY:
        return a
    raise ValueError(f"not a unary opcode: {op}")


def eval_compare(pred: CmpPred, a: Any, b: Any) -> bool:
    """Python comparisons already have IEEE semantics: NaN compares false except with !=."""
    if pred is CmpPred.EQ:
        return bool(a == b)
    if pred is CmpPred.NE:
        return bool(a != b)
    if pred is CmpPred.LT:
        return bool(a < b)
    if pred is CmpPred.LE:
        return bool(a <= b)
    if pred is CmpPred.GT:
        return bool(a > b)
    return bool(a >= b)

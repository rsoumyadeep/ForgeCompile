"""Textual IR format (parsed back by ``forgecompile.ir.parser``).

Example::

    func @gcd(%a: i64, %b: i64) -> i64 {
    entry:
        jump while.cond
    while.cond:
        %t1: i1 = icmp ne %b, 0
        br %t1, while.body, while.end
    while.body:
        %t2: i64 = srem %a, %b
        %a: i64 = copy %b
        %b: i64 = copy %t2
        jump while.cond
    while.end:
        ret %a
    }

Conventions:

* every defined register is annotated with its type (``%t1: i1 = ...``);
* constants are typed by spelling: ``42`` is i64; ``1.5``, ``1.0e+20``,
  ``nan`` and ``inf`` are f64; ``true``/``false`` are i1; ``undef.i64``;
* memory: ``load %p[%i]``, ``store %p[%i], %v``, ``alloca f64, 9``,
  ``memzero %p, f64, 9``, ``boundscheck %i, 9``, ``ptradd %p, %off, f64``.
"""

from __future__ import annotations

from forgecompile.ir.function import BasicBlock, Function, Module
from forgecompile.ir.instructions import (
    AllocaInst,
    BoundsCheckInst,
    BranchInst,
    CallInst,
    CompareInst,
    Instruction,
    JumpInst,
    LoadInst,
    MemZeroInst,
    Opcode,
    PhiInst,
    PtrAddInst,
    StoreInst,
)
from forgecompile.ir.values import Value

INDENT = "    "


def _v(value: Value) -> str:
    return str(value)


def _rhs(inst: Instruction) -> str:
    ops = inst.operands
    match inst:
        case CompareInst():
            return f"{inst.opcode.value} {inst.pred.value} {_v(ops[0])}, {_v(ops[1])}"
        case AllocaInst():
            return f"alloca {inst.elem_type}, {inst.count}"
        case LoadInst():
            return f"load {_v(ops[0])}[{_v(ops[1])}]"
        case StoreInst():
            return f"store {_v(ops[0])}[{_v(ops[1])}], {_v(ops[2])}"
        case PtrAddInst():
            return f"ptradd {_v(ops[0])}, {_v(ops[1])}, {inst.elem_type}"
        case MemZeroInst():
            return f"memzero {_v(ops[0])}, {inst.elem_type}, {inst.count}"
        case BoundsCheckInst():
            return f"boundscheck {_v(ops[0])}, {inst.length}"
        case CallInst():
            return f"call @{inst.callee}(" + ", ".join(_v(a) for a in ops) + ")"
        case PhiInst():
            pairs = ", ".join(f"[{_v(v)}, {b.label}]" for v, b in inst.incoming)
            return f"phi {pairs}"
        case JumpInst():
            return f"jump {inst.target.label}"
        case BranchInst():
            return f"br {_v(ops[0])}, {inst.true_target.label}, {inst.false_target.label}"
    if inst.opcode is Opcode.UNREACHABLE:
        return "unreachable"
    if inst.opcode is Opcode.RET and not ops:
        return "ret"
    return inst.opcode.value + (" " + ", ".join(_v(op) for op in ops) if ops else "")


def format_instruction(inst: Instruction) -> str:
    rhs = _rhs(inst)
    if inst.dest is not None:
        return f"{inst.dest}: {inst.dest.type} = {rhs}"
    return rhs


def format_block(block: BasicBlock) -> str:
    lines = [f"{block.label}:"]
    lines.extend(INDENT + format_instruction(inst) for inst in block.instructions)
    return "\n".join(lines)


def format_function(function: Function) -> str:
    params = ", ".join(f"{p}: {p.type}" for p in function.params)
    header = f"func @{function.name}({params}) -> {function.return_type} {{"
    blocks = [format_block(block) for block in function.blocks]
    return "\n".join([header, *blocks, "}"])


def format_module(module: Module) -> str:
    return "\n\n".join(format_function(f) for f in module.functions.values()) + "\n"

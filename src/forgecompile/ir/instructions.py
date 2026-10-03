"""IR instructions.

Every instruction has an ``opcode``, an optional ``dest`` register (the value
it defines) and a list of ``operands`` (the values it uses). Opcode-specific
data that is *not* a runtime value lives in named attributes: comparison
predicate, callee name, branch targets, element type, buffer length. Keeping
all runtime inputs in the one ``operands`` list lets passes such as copy
propagation and CSE rewrite uses generically, without knowing every opcode.

Effect classification (used by DCE, CSE and LICM in Phase 4):

* **may_trap**: ``sdiv``, ``srem`` and ``boundscheck`` can raise a runtime
  error. Deleting an unused ``x / y`` is therefore *not* safe unless ``y`` is
  known to be non-zero, because it would remove a trap (an observable effect).
* **writes_memory**: ``store``, ``memzero``, ``call``.
* **reads_memory**: ``load``, ``call``.
* **pure**: no side effects and no memory access. The result depends only on
  the operands, so it can be deleted if unused, CSE'd and hoisted freely.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from forgecompile.ir.values import IRType, Register, Value

if TYPE_CHECKING:
    from forgecompile.ir.function import BasicBlock


class Opcode(Enum):
    # Identity hash (C-level) instead of Enum's Python-level hash(name): enum equality is
    # identity, so this is equivalent, and opcode-keyed dicts/sets are on the interpreter's
    # hot path (profiling: Enum.__hash__ was 11% of dataset-generation time).
    __hash__ = object.__hash__

    # integer arithmetic (wrap-around)
    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    SDIV = "sdiv"  # truncating; traps on zero
    SREM = "srem"  # sign of dividend; traps on zero
    NEG = "neg"
    # float arithmetic (IEEE-754)
    FADD = "fadd"
    FSUB = "fsub"
    FMUL = "fmul"
    FDIV = "fdiv"
    FREM = "frem"
    FNEG = "fneg"
    # comparisons and booleans
    ICMP = "icmp"
    FCMP = "fcmp"
    NOT = "not"
    # conversions
    SITOFP = "sitofp"  # i64 -> f64
    FPTOSI = "fptosi"  # f64 -> i64, saturating, NaN -> 0
    ZEXT = "zext"  # i1 -> i64
    COPY = "copy"
    # memory
    ALLOCA = "alloca"
    LOAD = "load"
    STORE = "store"
    PTRADD = "ptradd"
    MEMZERO = "memzero"
    BOUNDSCHECK = "boundscheck"
    # calls and output
    CALL = "call"
    PRINT = "print"
    # SSA
    PHI = "phi"
    # terminators
    JUMP = "jump"
    BRANCH = "br"
    RET = "ret"
    UNREACHABLE = "unreachable"

    @property
    def is_terminator(self) -> bool:
        return self in _TERMINATORS

    @property
    def may_trap(self) -> bool:
        return self in (Opcode.SDIV, Opcode.SREM, Opcode.BOUNDSCHECK, Opcode.CALL)

    @property
    def writes_memory(self) -> bool:
        return self in (Opcode.STORE, Opcode.MEMZERO, Opcode.CALL)

    @property
    def reads_memory(self) -> bool:
        return self in (Opcode.LOAD, Opcode.CALL)

    @property
    def has_side_effects(self) -> bool:
        """True if the instruction must be kept even when its result is unused."""
        return self.may_trap or self.writes_memory or self is Opcode.PRINT or self.is_terminator

    @property
    def is_pure(self) -> bool:
        """Result depends only on operands; no effects; no memory access."""
        return self in _PURE


_TERMINATORS = frozenset({Opcode.JUMP, Opcode.BRANCH, Opcode.RET, Opcode.UNREACHABLE})

INT_BINARY = frozenset({Opcode.ADD, Opcode.SUB, Opcode.MUL, Opcode.SDIV, Opcode.SREM})
FLOAT_BINARY = frozenset({Opcode.FADD, Opcode.FSUB, Opcode.FMUL, Opcode.FDIV, Opcode.FREM})
BINARY_OPCODES = INT_BINARY | FLOAT_BINARY
UNARY_OPCODES = frozenset(
    {Opcode.NEG, Opcode.FNEG, Opcode.NOT, Opcode.SITOFP, Opcode.FPTOSI, Opcode.ZEXT, Opcode.COPY}
)
COMMUTATIVE = frozenset({Opcode.ADD, Opcode.MUL, Opcode.FADD, Opcode.FMUL})

_PURE = frozenset(
    (BINARY_OPCODES - {Opcode.SDIV, Opcode.SREM})
    | UNARY_OPCODES
    | {Opcode.ICMP, Opcode.FCMP, Opcode.PTRADD, Opcode.PHI}
)

# (operand type, result type) for unary opcodes
UNARY_SIGNATURES: dict[Opcode, tuple[IRType | None, IRType | None]] = {
    Opcode.NEG: (IRType.I64, IRType.I64),
    Opcode.FNEG: (IRType.F64, IRType.F64),
    Opcode.NOT: (IRType.I1, IRType.I1),
    Opcode.SITOFP: (IRType.I64, IRType.F64),
    Opcode.FPTOSI: (IRType.F64, IRType.I64),
    Opcode.ZEXT: (IRType.I1, IRType.I64),
    Opcode.COPY: (None, None),  # any type, result = operand type
}


class CmpPred(Enum):
    """Comparison predicates. Integers compare signed.

    Float comparisons are *ordered*, so any comparison involving NaN is false,
    except ``ne``, which is *unordered* (true for NaN). This matches IEEE-754,
    Python, and LLVM's ``oeq/olt/.../une``.
    """

    # Identity hash (C-level) instead of Enum's Python-level hash(name): enum equality is
    # identity, so this is equivalent, and opcode-keyed dicts/sets are on the interpreter's
    # hot path (profiling: Enum.__hash__ was 11% of dataset-generation time).
    __hash__ = object.__hash__

    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"

    @property
    def swapped(self) -> CmpPred:
        """Predicate p' such that (a p b) == (b p' a)."""
        return _SWAPPED[self]

    @property
    def inverse(self) -> CmpPred:
        """Predicate p' such that (a p' b) == not (a p b). Valid for integers only (NaN)."""
        return _INVERSE[self]


_SWAPPED = {
    CmpPred.EQ: CmpPred.EQ,
    CmpPred.NE: CmpPred.NE,
    CmpPred.LT: CmpPred.GT,
    CmpPred.LE: CmpPred.GE,
    CmpPred.GT: CmpPred.LT,
    CmpPred.GE: CmpPred.LE,
}
_INVERSE = {
    CmpPred.EQ: CmpPred.NE,
    CmpPred.NE: CmpPred.EQ,
    CmpPred.LT: CmpPred.GE,
    CmpPred.LE: CmpPred.GT,
    CmpPred.GT: CmpPred.LE,
    CmpPred.GE: CmpPred.LT,
}


class Instruction:
    """Base class. ``block`` is set when the instruction is placed in a block."""

    def __init__(self, opcode: Opcode, dest: Register | None, operands: list[Value]) -> None:
        self.opcode = opcode
        self.dest = dest
        self.operands = operands
        self.block: BasicBlock | None = None

    @property
    def is_terminator(self) -> bool:
        return self.opcode.is_terminator

    def replace_uses(self, old: Value, new: Value) -> int:
        """Replace every operand that *is* ``old`` with ``new``; return the count."""
        count = 0
        for i, operand in enumerate(self.operands):
            if operand is old:
                self.operands[i] = new
                count += 1
        return count

    def registers_used(self) -> list[Register]:
        return [op for op in self.operands if isinstance(op, Register)]

    def __repr__(self) -> str:
        from forgecompile.ir.printer import format_instruction

        return f"<{format_instruction(self)}>"


class BinaryInst(Instruction):
    def __init__(self, opcode: Opcode, dest: Register, lhs: Value, rhs: Value) -> None:
        assert opcode in BINARY_OPCODES, opcode
        super().__init__(opcode, dest, [lhs, rhs])

    @property
    def lhs(self) -> Value:
        return self.operands[0]

    @property
    def rhs(self) -> Value:
        return self.operands[1]


class UnaryInst(Instruction):
    def __init__(self, opcode: Opcode, dest: Register, operand: Value) -> None:
        assert opcode in UNARY_OPCODES, opcode
        super().__init__(opcode, dest, [operand])

    @property
    def operand(self) -> Value:
        return self.operands[0]


class CompareInst(Instruction):
    def __init__(
        self, opcode: Opcode, pred: CmpPred, dest: Register, lhs: Value, rhs: Value
    ) -> None:
        assert opcode in (Opcode.ICMP, Opcode.FCMP), opcode
        super().__init__(opcode, dest, [lhs, rhs])
        self.pred = pred

    @property
    def lhs(self) -> Value:
        return self.operands[0]

    @property
    def rhs(self) -> Value:
        return self.operands[1]


class AllocaInst(Instruction):
    """Allocate a zero-filled stack buffer of ``count`` elements; ``dest`` is a ptr."""

    def __init__(self, dest: Register, elem_type: IRType, count: int) -> None:
        super().__init__(Opcode.ALLOCA, dest, [])
        self.elem_type = elem_type
        self.count = count


class LoadInst(Instruction):
    """``dest = ptr[index]``."""

    def __init__(self, dest: Register, ptr: Value, index: Value) -> None:
        super().__init__(Opcode.LOAD, dest, [ptr, index])

    @property
    def ptr(self) -> Value:
        return self.operands[0]

    @property
    def index(self) -> Value:
        return self.operands[1]


class StoreInst(Instruction):
    """``ptr[index] = value``."""

    def __init__(self, ptr: Value, index: Value, value: Value) -> None:
        super().__init__(Opcode.STORE, None, [ptr, index, value])

    @property
    def ptr(self) -> Value:
        return self.operands[0]

    @property
    def index(self) -> Value:
        return self.operands[1]

    @property
    def value(self) -> Value:
        return self.operands[2]


class PtrAddInst(Instruction):
    """``dest = &ptr[offset]`` (used to pass a row of a 2-D array by reference).

    ``offset`` counts elements of ``elem_type``. The element type is recorded
    because a derived pointer forgets which array it came from, and the LLVM
    backend needs it to compute the byte stride (``getelementptr``).
    """

    def __init__(self, dest: Register, ptr: Value, offset: Value, elem_type: IRType) -> None:
        super().__init__(Opcode.PTRADD, dest, [ptr, offset])
        self.elem_type = elem_type


class MemZeroInst(Instruction):
    """Zero ``count`` elements of type ``elem_type`` starting at ``ptr``."""

    def __init__(self, ptr: Value, elem_type: IRType, count: int) -> None:
        super().__init__(Opcode.MEMZERO, None, [ptr])
        self.elem_type = elem_type
        self.count = count


class BoundsCheckInst(Instruction):
    """Trap unless ``0 <= index < length`` (``length`` is a compile-time constant)."""

    def __init__(self, index: Value, length: int) -> None:
        super().__init__(Opcode.BOUNDSCHECK, None, [index])
        self.length = length

    @property
    def index(self) -> Value:
        return self.operands[0]


class CallInst(Instruction):
    def __init__(self, dest: Register | None, callee: str, args: list[Value]) -> None:
        super().__init__(Opcode.CALL, dest, list(args))
        self.callee = callee


class PrintInst(Instruction):
    def __init__(self, value: Value) -> None:
        super().__init__(Opcode.PRINT, None, [value])


class PhiInst(Instruction):
    """``dest = phi [v1, b1], [v2, b2], ...``: the value from the predecessor control came from.

    ``operands[i]`` is the incoming value from ``blocks[i]``.
    """

    def __init__(self, dest: Register, incoming: list[tuple[Value, BasicBlock]]) -> None:
        super().__init__(Opcode.PHI, dest, [value for value, _ in incoming])
        self.blocks: list[BasicBlock] = [block for _, block in incoming]

    @property
    def incoming(self) -> list[tuple[Value, BasicBlock]]:
        return list(zip(self.operands, self.blocks, strict=True))

    def value_from(self, block: BasicBlock) -> Value:
        for value, pred in zip(self.operands, self.blocks, strict=True):
            if pred is block:
                return value
        raise KeyError(f"phi {self.dest} has no incoming value from {block.label}")

    def add_incoming(self, value: Value, block: BasicBlock) -> None:
        self.operands.append(value)
        self.blocks.append(block)

    def remove_incoming(self, block: BasicBlock) -> None:
        for i, pred in enumerate(self.blocks):
            if pred is block:
                del self.operands[i]
                del self.blocks[i]
                return
        raise KeyError(block.label)


class Terminator(Instruction):
    @property
    def targets(self) -> list[BasicBlock]:
        return []

    def replace_target(self, old: BasicBlock, new: BasicBlock) -> None:
        raise ValueError(f"{self.opcode.value} has no targets")


class JumpInst(Terminator):
    def __init__(self, target: BasicBlock) -> None:
        super().__init__(Opcode.JUMP, None, [])
        self.target = target

    @property
    def targets(self) -> list[BasicBlock]:
        return [self.target]

    def replace_target(self, old: BasicBlock, new: BasicBlock) -> None:
        if self.target is old:
            self.target = new


class BranchInst(Terminator):
    def __init__(self, cond: Value, true_target: BasicBlock, false_target: BasicBlock) -> None:
        super().__init__(Opcode.BRANCH, None, [cond])
        self.true_target = true_target
        self.false_target = false_target

    @property
    def cond(self) -> Value:
        return self.operands[0]

    @property
    def targets(self) -> list[BasicBlock]:
        if self.true_target is self.false_target:
            return [self.true_target]
        return [self.true_target, self.false_target]

    def replace_target(self, old: BasicBlock, new: BasicBlock) -> None:
        if self.true_target is old:
            self.true_target = new
        if self.false_target is old:
            self.false_target = new


class ReturnInst(Terminator):
    def __init__(self, value: Value | None) -> None:
        super().__init__(Opcode.RET, None, [] if value is None else [value])

    @property
    def value(self) -> Value | None:
        return self.operands[0] if self.operands else None


class UnreachableInst(Terminator):
    """Marks a point control can never reach (e.g. after an infinite loop)."""

    def __init__(self) -> None:
        super().__init__(Opcode.UNREACHABLE, None, [])

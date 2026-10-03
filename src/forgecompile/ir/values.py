"""IR types and values: registers, constants, undef.

IR types are machine-level, not MiniLang-level. Arrays disappear during lowering:
an array becomes a ``ptr`` to a flat, zero-initialized buffer of scalars, and
``m[i][j]`` becomes one load at the offset ``i * cols + j``.

=========  =======================================
IR type    meaning
=========  =======================================
``i64``    64-bit integer (MiniLang ``int``)
``f64``    IEEE double (MiniLang ``float``)
``i1``     boolean
``ptr``    address of an array element
``void``   no value (calls to void functions)
=========  =======================================
"""

from __future__ import annotations

import math
from enum import Enum


class IRType(Enum):
    # Identity hash (C-level) instead of Enum's Python-level hash(name): enum equality is
    # identity, so this is equivalent, and opcode-keyed dicts/sets are on the interpreter's
    # hot path (profiling: Enum.__hash__ was 11% of dataset-generation time).
    __hash__ = object.__hash__

    I64 = "i64"
    F64 = "f64"
    I1 = "i1"
    PTR = "ptr"
    VOID = "void"

    def __str__(self) -> str:
        return self.value


class Value:
    """Anything an instruction can use as an operand."""

    type: IRType


class Register(Value):
    """A virtual register.

    Before SSA construction, a register that stands for a source variable may
    be assigned by several instructions. After SSA construction every register
    has exactly one definition. Registers are compared by identity; ``name`` is
    only for printing and is unique within a function.
    """

    __slots__ = ("name", "type")

    def __init__(self, name: str, type: IRType) -> None:
        self.name = name
        self.type = type

    def __str__(self) -> str:
        return f"%{self.name}"

    def __repr__(self) -> str:
        return f"Register(%{self.name}: {self.type})"


class Constant(Value):
    """An immediate value. Compared by (type, value), so constants can be dict keys."""

    __slots__ = ("type", "value")

    def __init__(self, type: IRType, value: int | float | bool) -> None:
        if type is IRType.I1:
            value = bool(value)
        elif type is IRType.I64:
            value = int(value)
        elif type is IRType.F64:
            value = float(value)
        else:
            raise ValueError(f"no constants of type {type}")
        self.type = type
        self.value = value

    def _key(self) -> tuple[IRType, object]:
        # 0.0 and -0.0 are different constants (1/x differs), and NaN must equal itself.
        if isinstance(self.value, float):
            return (self.type, ("f", math.copysign(1.0, self.value), repr(self.value)))
        return (self.type, self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Constant) and self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def __str__(self) -> str:
        if self.type is IRType.I1:
            return "true" if self.value else "false"
        if self.type is IRType.F64:
            return format_float_constant(float(self.value))
        return str(self.value)

    def __repr__(self) -> str:
        return f"Constant({self.type}, {self.value!r})"


class Undef(Value):
    """An unspecified value of a given type.

    SSA construction uses ``undef`` as a phi input on paths where a variable
    has no definition yet (e.g. a loop-local variable at the loop header).
    Well-formed MiniLang never *observes* such a value. The IR interpreter
    raises an internal error if one reaches an observable operation, which
    turns a latent compiler bug into a loud failure.
    """

    __slots__ = ("type",)

    def __init__(self, type: IRType) -> None:
        self.type = type

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Undef) and other.type is self.type

    def __hash__(self) -> int:
        return hash(("undef", self.type))

    def __str__(self) -> str:
        return f"undef.{self.type}"

    def __repr__(self) -> str:
        return f"Undef({self.type})"


def format_float_constant(x: float) -> str:
    """Round-trippable float spelling that is never confused with an int (always has '.')."""
    if math.isnan(x):
        return "nan"
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    text = repr(x)
    if "e" in text and "." not in text.split("e")[0]:
        mantissa, exponent = text.split("e")
        text = f"{mantissa}.0e{exponent}"
    return text


def const_int(value: int) -> Constant:
    return Constant(IRType.I64, value)


def const_float(value: float) -> Constant:
    return Constant(IRType.F64, value)


def const_bool(value: bool) -> Constant:
    return Constant(IRType.I1, value)

"""Exact MiniLang runtime semantics (docs/LANGUAGE.md §7) as small pure functions.

Python's own operators differ from MiniLang's in several ways that are easy
to miss:

* Python ints are unbounded. MiniLang ints wrap around modulo 2**64.
* Python ``//`` floors (``-7 // 2 == -4``). MiniLang ``/`` truncates toward
  zero (``-7 / 2 == -3``), like C and LLVM ``sdiv``.
* Python ``%`` takes the sign of the divisor. MiniLang ``%`` takes the sign of
  the dividend (C ``srem`` / ``fmod``).
* Python ``int(float)`` raises on NaN/inf. MiniLang casts saturate.

Both interpreters (AST and IR) use these helpers, and the constant folder in
Phase 4 will too. Because the helpers are shared, a bug here would affect
every oracle equally, so ``tests/runtime/test_semantics.py`` checks each one
against hand-computed C/LLVM results.
"""

from __future__ import annotations

import math

INT_BITS = 64
INT_MIN = -(2 ** (INT_BITS - 1))
INT_MAX = 2 ** (INT_BITS - 1) - 1
_MODULUS = 2**INT_BITS

RUNTIME_ERROR_EXIT_CODE = 101


class RuntimeTrap(Exception):
    """A MiniLang runtime error (division by zero, out-of-bounds index, ...)."""


def wrap(value: int) -> int:
    """Reduce an unbounded integer to a signed 64-bit two's-complement value."""
    value &= _MODULUS - 1
    return value - _MODULUS if value > INT_MAX else value


def int_div(a: int, b: int) -> int:
    """C ``a / b``: truncate toward zero; traps on zero; INT_MIN / -1 wraps to INT_MIN."""
    if b == 0:
        raise RuntimeTrap("division by zero")
    quotient = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        quotient = -quotient
    return wrap(quotient)


def int_rem(a: int, b: int) -> int:
    """C ``a % b``: result has the sign of the dividend; traps on zero."""
    if b == 0:
        raise RuntimeTrap("remainder by zero")
    remainder = abs(a) % abs(b)
    return -remainder if a < 0 else remainder


def float_rem(a: float, b: float) -> float:
    """C ``fmod``: NaN for a zero divisor, never a trap."""
    if b == 0.0 or math.isinf(a) or math.isnan(a) or math.isnan(b):
        return math.nan
    return math.fmod(a, b)


def float_div(a: float, b: float) -> float:
    """IEEE-754 division: x/0 is ±inf, 0/0 is NaN (Python would raise ZeroDivisionError)."""
    if b == 0.0:
        if a == 0.0 or math.isnan(a):
            return math.nan
        # Sign of the result: sign(a) XOR sign(b), where b may be -0.0.
        negative = (a < 0) != (math.copysign(1.0, b) < 0)
        return -math.inf if negative else math.inf
    return a / b


def float_to_int(x: float) -> int:
    """Saturating truncation (Rust ``as`` / LLVM ``fptosi.sat``): NaN -> 0."""
    if math.isnan(x):
        return 0
    if x >= 2.0**63:
        return INT_MAX
    if x < -(2.0**63):
        return INT_MIN
    return int(x)  # int() truncates toward zero


def format_float(x: float) -> str:
    """``print`` format for floats: ``%.6f``, with NaN always spelled ``nan``."""
    if math.isnan(x):
        return "nan"  # C may print "-nan" for negative NaNs; MiniLang does not
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    return f"{x:.6f}"


def format_value(value: int | float | bool) -> str:
    """Text written by ``print`` (without the trailing newline)."""
    if isinstance(value, bool):  # check bool first: bool is a subclass of int
        return "true" if value else "false"
    if isinstance(value, float):
        return format_float(value)
    return str(value)


def exit_status(main_result: int | None) -> int:
    """Process exit status: main's int result modulo 256 (0 for void main)."""
    return 0 if main_result is None else main_result % 256

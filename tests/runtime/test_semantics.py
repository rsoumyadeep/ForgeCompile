"""The arithmetic helpers against hand-computed C / LLVM / IEEE-754 results.

Both interpreters share these helpers, so they get their own careful tests:
a bug here could not be caught by comparing the interpreters.
"""

from __future__ import annotations

import math

import pytest

from forgecompile.runtime import semantics as sem
from forgecompile.runtime.semantics import INT_MAX, INT_MIN, RuntimeTrap


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 0),
        (INT_MAX, INT_MAX),
        (INT_MAX + 1, INT_MIN),
        (INT_MIN - 1, INT_MAX),
        (2**64, 0),
        (2**64 + 5, 5),
        (-(2**64) - 5, -5),
        (INT_MAX * INT_MAX, 1),  # (2^63-1)^2 = 2^126 - 2^64 + 1 ≡ 1 (mod 2^64)
    ],
)
def test_wrap(value: int, expected: int) -> None:
    assert sem.wrap(value) == expected


@pytest.mark.parametrize(
    ("a", "b", "quotient", "remainder"),
    [
        (7, 2, 3, 1),
        (-7, 2, -3, -1),  # C truncates; Python's -7 // 2 == -4 and -7 % 2 == 1
        (7, -2, -3, 1),
        (-7, -2, 3, -1),
        (0, 5, 0, 0),
        (INT_MIN, -1, INT_MIN, 0),  # overflow wraps; no trap
        (INT_MIN, 1, INT_MIN, 0),
        (INT_MAX, INT_MIN, 0, INT_MAX),
    ],
)
def test_int_div_and_rem_follow_c(a: int, b: int, quotient: int, remainder: int) -> None:
    assert sem.int_div(a, b) == quotient
    assert sem.int_rem(a, b) == remainder
    # C identity: a == (a / b) * b + a % b  (modulo 2^64)
    assert sem.wrap(quotient * b + remainder) == a


def test_division_by_zero_traps() -> None:
    with pytest.raises(RuntimeTrap, match="division by zero"):
        sem.int_div(1, 0)
    with pytest.raises(RuntimeTrap, match="remainder by zero"):
        sem.int_rem(1, 0)


def test_float_division_never_traps() -> None:
    assert sem.float_div(1.0, 0.0) == math.inf
    assert sem.float_div(-1.0, 0.0) == -math.inf
    assert sem.float_div(1.0, -0.0) == -math.inf
    assert math.isnan(sem.float_div(0.0, 0.0))
    assert math.isnan(sem.float_div(math.nan, 0.0))
    assert sem.float_div(3.0, 2.0) == 1.5


def test_float_rem_is_fmod() -> None:
    assert sem.float_rem(7.5, 2.0) == 1.5
    assert sem.float_rem(-7.5, 2.0) == -1.5  # sign of the dividend (Python % gives 0.5)
    assert sem.float_rem(5.0, math.inf) == 5.0
    assert math.isnan(sem.float_rem(1.0, 0.0))
    assert math.isnan(sem.float_rem(math.inf, 2.0))
    assert math.isnan(sem.float_rem(math.nan, 2.0))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.9, 1),
        (-1.9, -1),  # toward zero
        (0.0, 0),
        (-0.0, 0),
        (math.nan, 0),
        (math.inf, INT_MAX),
        (-math.inf, INT_MIN),
        (1e30, INT_MAX),
        (-1e30, INT_MIN),
        (9.223372036854775e18, 9223372036854774784),  # largest double below 2^63
        (2.0**63, INT_MAX),
        (-(2.0**63), INT_MIN),
    ],
)
def test_float_to_int_saturates(value: float, expected: int) -> None:
    assert sem.float_to_int(value) == expected


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1.0, "1.000000"),
        (2.0 / 3.0, "0.666667"),
        (-0.0, "-0.000000"),
        (1e20, "100000000000000000000.000000"),
        (0.0000004, "0.000000"),
        # %.6f rounds the *exact binary* value: 5e-7 is stored as 4.99999...e-7 (below the
        # halfway point) and rounds down, while 1.5e-6 is stored as 1.500...038e-6 and rounds up.
        (5e-7, "0.000000"),
        (1.5e-6, "0.000002"),
        (math.inf, "inf"),
        (-math.inf, "-inf"),
        (math.nan, "nan"),
        (-math.nan, "nan"),
    ],
)
def test_format_float(value: float, text: str) -> None:
    assert sem.format_float(value) == text


def test_format_value_distinguishes_bool_from_int() -> None:
    assert sem.format_value(True) == "true"
    assert sem.format_value(False) == "false"
    assert sem.format_value(1) == "1"
    assert sem.format_value(1.0) == "1.000000"


@pytest.mark.parametrize(
    ("result", "status"), [(None, 0), (0, 0), (42, 42), (256, 0), (-1, 255), (300, 44)]
)
def test_exit_status(result: int | None, status: int) -> None:
    assert sem.exit_status(result) == status

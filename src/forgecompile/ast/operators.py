"""Operators and their precedence.

This table is the single source of truth for operator precedence. The parser
uses it to build trees, and the source formatter uses it to decide where
parentheses are required. If the two ever disagreed, the round-trip tests
(parse -> format -> parse) would catch it.

Precedence, from loosest to tightest binding::

    1  ||                     left-assoc
    2  &&                     left-assoc
    3  ==  !=                 non-associative   (a == b == c is a syntax error)
    4  <  <=  >  >=           non-associative
    5  +  -                   left-assoc
    6  *  /  %                left-assoc
    7  as                     left-assoc (postfix-like:  x as float as int)
    8  unary  -  !            prefix
    9  call f(..), index a[i] postfix
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class Precedence(IntEnum):
    LOWEST = 0
    OR = 1
    AND = 2
    EQUALITY = 3
    COMPARISON = 4
    ADDITIVE = 5
    MULTIPLICATIVE = 6
    CAST = 7
    UNARY = 8
    POSTFIX = 9


class BinaryOp(StrEnum):
    OR = "||"
    AND = "&&"
    EQ = "=="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "/"
    MOD = "%"

    @property
    def precedence(self) -> Precedence:
        return BINARY_PRECEDENCE[self]

    @property
    def is_comparison(self) -> bool:
        return self.precedence in (Precedence.EQUALITY, Precedence.COMPARISON)

    @property
    def is_logical(self) -> bool:
        return self in (BinaryOp.AND, BinaryOp.OR)

    @property
    def is_arithmetic(self) -> bool:
        return self.precedence in (Precedence.ADDITIVE, Precedence.MULTIPLICATIVE)


class UnaryOp(StrEnum):
    NEG = "-"
    NOT = "!"


BINARY_PRECEDENCE: dict[BinaryOp, Precedence] = {
    BinaryOp.OR: Precedence.OR,
    BinaryOp.AND: Precedence.AND,
    BinaryOp.EQ: Precedence.EQUALITY,
    BinaryOp.NE: Precedence.EQUALITY,
    BinaryOp.LT: Precedence.COMPARISON,
    BinaryOp.LE: Precedence.COMPARISON,
    BinaryOp.GT: Precedence.COMPARISON,
    BinaryOp.GE: Precedence.COMPARISON,
    BinaryOp.ADD: Precedence.ADDITIVE,
    BinaryOp.SUB: Precedence.ADDITIVE,
    BinaryOp.MUL: Precedence.MULTIPLICATIVE,
    BinaryOp.DIV: Precedence.MULTIPLICATIVE,
    BinaryOp.MOD: Precedence.MULTIPLICATIVE,
}

NON_ASSOCIATIVE: frozenset[Precedence] = frozenset({Precedence.EQUALITY, Precedence.COMPARISON})

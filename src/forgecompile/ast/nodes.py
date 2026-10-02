"""AST node classes.

The AST keeps the program's *structure* and drops its *spelling*: there are no
parenthesis nodes, no comments and no whitespace. ``(1 + 2) * 3`` and
``(((1 + 2))) * 3`` produce the same tree, because precedence is encoded in the
nesting.

Equality ignores source spans and semantic annotations (``compare=False``), so
two trees parsed from differently formatted sources compare equal. The
round-trip tests depend on this.

Semantic analysis (Phase 2) annotates nodes in place: ``Expr.ty``, plus the
resolved symbol on ``Name``, ``LetStmt``, ``ForStmt``, ``Param`` and ``Call``.

``else if`` chains are desugared at parse time: ``if a {..} else if b {..}``
becomes ``IfStmt(a, .., else_body=Block([IfStmt(b, ..)]))``. Later phases then
deal with a single form of ``if``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from forgecompile.ast.operators import BinaryOp, UnaryOp
from forgecompile.ast.types import Type
from forgecompile.diagnostics import Span

if TYPE_CHECKING:  # annotation-only import: semantic depends on ast, not vice versa
    from forgecompile.semantic.symbols import FunctionSymbol, VariableSymbol


@dataclass
class Node:
    span: Span = field(compare=False, repr=False, kw_only=True)


# --------------------------------------------------------------------------- expressions


@dataclass
class Expr(Node):
    # Filled in by semantic analysis (Phase 2); None straight after parsing.
    ty: Type | None = field(default=None, compare=False, repr=False, kw_only=True)


@dataclass
class IntLiteral(Expr):
    value: int


@dataclass
class FloatLiteral(Expr):
    value: float


@dataclass
class BoolLiteral(Expr):
    value: bool


@dataclass
class ArrayLiteral(Expr):
    elements: list[Expr]


@dataclass
class Name(Expr):
    ident: str
    symbol: VariableSymbol | None = field(default=None, compare=False, repr=False, kw_only=True)


@dataclass
class Unary(Expr):
    op: UnaryOp
    operand: Expr


@dataclass
class Binary(Expr):
    op: BinaryOp
    left: Expr
    right: Expr


@dataclass
class Call(Expr):
    callee: str
    args: list[Expr]
    function: FunctionSymbol | None = field(default=None, compare=False, repr=False, kw_only=True)


@dataclass
class Index(Expr):
    base: Expr
    index: Expr


@dataclass
class Cast(Expr):
    expr: Expr
    target: Type


# --------------------------------------------------------------------------- statements


@dataclass
class Stmt(Node):
    pass


@dataclass
class Block(Stmt):
    statements: list[Stmt]


@dataclass
class LetStmt(Stmt):
    name: str
    declared_type: Type | None
    init: Expr | None
    symbol: VariableSymbol | None = field(default=None, compare=False, repr=False, kw_only=True)


@dataclass
class AssignStmt(Stmt):
    target: Expr  # Name or Index (checked by the parser)
    value: Expr


@dataclass
class IfStmt(Stmt):
    condition: Expr
    then_body: Block
    else_body: Block | None


@dataclass
class WhileStmt(Stmt):
    condition: Expr
    body: Block


@dataclass
class ForStmt(Stmt):
    """``for var in start..end { body }`` iterates var = start, start+1, ..., end-1."""

    var: str
    start: Expr
    end: Expr
    body: Block
    symbol: VariableSymbol | None = field(default=None, compare=False, repr=False, kw_only=True)


@dataclass
class ReturnStmt(Stmt):
    value: Expr | None


@dataclass
class BreakStmt(Stmt):
    pass


@dataclass
class ContinueStmt(Stmt):
    pass


@dataclass
class ExprStmt(Stmt):
    expr: Expr


# --------------------------------------------------------------------------- declarations


@dataclass
class Param(Node):
    name: str
    type: Type
    symbol: VariableSymbol | None = field(default=None, compare=False, repr=False, kw_only=True)


@dataclass
class FunctionDecl(Node):
    name: str
    params: list[Param]
    return_type: Type
    body: Block
    symbol: FunctionSymbol | None = field(default=None, compare=False, repr=False, kw_only=True)


@dataclass
class Program(Node):
    functions: list[FunctionDecl]

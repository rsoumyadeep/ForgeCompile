"""Symbols and scopes.

A *symbol* is the compiler's record of a declared entity: a variable or a
function. Name resolution maps each *use* of a name to the symbol of its
declaration, and stores that symbol on the AST node (``Name.symbol``).

Resolving to a symbol, rather than keeping the name string, matters because
names are not unique::

    let x = 1;
    { let x = 2.5; print(x); }   // this `x` is a different variable (a float)
    print(x);

Both declarations are called ``x``, but they get distinct ``VariableSymbol``
objects with distinct ``uid`` values. IR lowering (Phase 3) keys storage on
the symbol, so the two never collide.

Scopes form a chain (a "spaghetti stack"). Lookup walks outward from the
innermost scope, so an inner declaration shadows an outer one. Each scope is
a dict, so lookup costs O(depth).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from forgecompile.ast.types import Type
from forgecompile.diagnostics import Span


class VariableKind(Enum):
    LOCAL = "local variable"
    PARAM = "parameter"
    LOOP_VAR = "loop variable"


@dataclass(eq=False)  # identity semantics: two symbols are equal only if they are the same object
class VariableSymbol:
    name: str
    type: Type
    kind: VariableKind
    span: Span
    uid: int  # unique within a program; used by IR lowering

    @property
    def mutable(self) -> bool:
        return self.kind is not VariableKind.LOOP_VAR

    def __repr__(self) -> str:
        return f"VariableSymbol({self.name!r}#{self.uid}: {self.type})"


@dataclass(eq=False)
class FunctionSymbol:
    name: str
    param_types: tuple[Type, ...]
    return_type: Type
    span: Span | None  # None for built-ins
    builtin: bool = False
    params: list[VariableSymbol] = field(default_factory=list)

    def signature(self) -> str:
        params = ", ".join(str(t) for t in self.param_types)
        return f"fn {self.name}({params}) -> {self.return_type}"

    def __repr__(self) -> str:
        return f"FunctionSymbol({self.signature()})"


class Scope:
    """One lexical scope: a block, a function's top level, or a loop body."""

    def __init__(self, parent: Scope | None = None) -> None:
        self.parent = parent
        self.symbols: dict[str, VariableSymbol] = {}

    def declare(self, symbol: VariableSymbol) -> VariableSymbol | None:
        """Add ``symbol``. Return the existing symbol if the name is already declared *here*."""
        existing = self.symbols.get(symbol.name)
        if existing is None:
            self.symbols[symbol.name] = symbol
        return existing

    def lookup(self, name: str) -> VariableSymbol | None:
        scope: Scope | None = self
        while scope is not None:
            symbol = scope.symbols.get(name)
            if symbol is not None:
                return symbol
            scope = scope.parent
        return None

    def visible_names(self) -> set[str]:
        names: set[str] = set()
        scope: Scope | None = self
        while scope is not None:
            names.update(scope.symbols)
            scope = scope.parent
        return names

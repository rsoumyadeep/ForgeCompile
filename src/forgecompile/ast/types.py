"""MiniLang's types.

The type system is deliberately small (see docs/LANGUAGE.md §Types):

* ``int``   - 64-bit signed integer, two's-complement wrap-around arithmetic
* ``float`` - IEEE-754 double precision
* ``bool``  - ``true`` / ``false``
* ``[T; N]`` - fixed-size array of ``N`` elements of type ``T`` (T may itself be an array)
* ``void``  - the "return type" of functions that return nothing; not a value type

Types are immutable values compared structurally, so ``ArrayType(INT, 3) ==
ArrayType(INT, 3)``. The parser produces them directly from type annotations.
"""

from __future__ import annotations

from dataclasses import dataclass


class Type:
    """Base class of all MiniLang types."""

    @property
    def is_numeric(self) -> bool:
        return self in (INT, FLOAT)

    @property
    def is_scalar(self) -> bool:
        return self in (INT, FLOAT, BOOL)


@dataclass(frozen=True)
class PrimitiveType(Type):
    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class ArrayType(Type):
    element: Type
    size: int

    def __str__(self) -> str:
        return f"[{self.element}; {self.size}]"

    @property
    def scalar_element(self) -> Type:
        """Innermost element type, e.g. ``int`` for ``[[int; 3]; 4]``."""
        element = self.element
        while isinstance(element, ArrayType):
            element = element.element
        return element

    @property
    def total_elements(self) -> int:
        """Number of scalars in the flattened array, e.g. 12 for ``[[int; 3]; 4]``."""
        inner = self.element.total_elements if isinstance(self.element, ArrayType) else 1
        return self.size * inner


INT = PrimitiveType("int")
FLOAT = PrimitiveType("float")
BOOL = PrimitiveType("bool")
VOID = PrimitiveType("void")

PRIMITIVES_BY_NAME: dict[str, PrimitiveType] = {"int": INT, "float": FLOAT, "bool": BOOL}

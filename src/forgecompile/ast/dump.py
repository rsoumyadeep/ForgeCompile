"""Debug views of the AST: an indented tree and compact S-expressions.

``dump`` walks any dataclass node generically, so new node types appear in the
output without changes here::

    FunctionDecl name='main' return_type=int
      params: []
      body: Block
        LetStmt name='x' declared_type=None
          init: Binary op=+
            ...

``sexpr`` renders expressions with explicit structure. It is ideal for
precedence tests: ``1 + 2 * 3`` -> ``(+ 1 (* 2 3))``.
"""

from __future__ import annotations

import dataclasses
from enum import Enum

from forgecompile.ast import nodes as ast
from forgecompile.ast.types import Type


def _is_child(value: object) -> bool:
    return isinstance(value, ast.Node) or (
        isinstance(value, list) and any(isinstance(item, ast.Node) for item in value)
    )


def _scalar(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, Type):
        return str(value)
    return repr(value)


def dump(node: ast.Node, show_types: bool = False) -> str:
    """Indented multi-line tree. ``show_types`` adds semantic types once they are known."""
    lines: list[str] = []

    def visit(n: ast.Node, indent: str, label: str) -> None:
        attrs: list[str] = []
        children: list[tuple[str, object]] = []
        for f in dataclasses.fields(n):
            if not f.compare:  # span / type annotations
                continue
            value = getattr(n, f.name)
            if _is_child(value) or (isinstance(value, list) and not value):
                children.append((f.name, value))
            else:
                attrs.append(f"{f.name}={_scalar(value)}")
        if show_types and isinstance(n, ast.Expr) and n.ty is not None:
            attrs.append(f": {n.ty}")
        head = " ".join([type(n).__name__, *attrs])
        lines.append(f"{indent}{label}{head}")
        for name, value in children:
            if isinstance(value, ast.Node):
                visit(value, indent + "  ", f"{name}: ")
            else:
                assert isinstance(value, list)
                if not value:
                    lines.append(f"{indent}  {name}: []")
                    continue
                lines.append(f"{indent}  {name}:")
                for item in value:
                    visit(item, indent + "    ", "- ")

    visit(node, "", "")
    return "\n".join(lines)


def sexpr(expr: ast.Expr) -> str:
    """Compact S-expression for an expression tree."""
    match expr:
        case ast.IntLiteral(value=v):
            return str(v)
        case ast.FloatLiteral(value=v):
            return repr(v)
        case ast.BoolLiteral(value=v):
            return "true" if v else "false"
        case ast.Name(ident=name):
            return name
        case ast.Unary(op=op, operand=operand):
            return f"({op.value} {sexpr(operand)})"
        case ast.Binary(op=op, left=left, right=right):
            return f"({op.value} {sexpr(left)} {sexpr(right)})"
        case ast.Cast(expr=inner, target=target):
            return f"(as {sexpr(inner)} {target})"
        case ast.Index(base=base, index=index):
            return f"(index {sexpr(base)} {sexpr(index)})"
        case ast.Call(callee=callee, args=args):
            return f"(call {' '.join([callee, *(sexpr(a) for a in args)])})"
        case ast.ArrayLiteral(elements=elements):
            return f"[{' '.join(sexpr(e) for e in elements)}]"
    raise TypeError(f"not an expression node: {type(expr).__name__}")

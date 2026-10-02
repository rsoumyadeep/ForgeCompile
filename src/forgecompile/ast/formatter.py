"""Pretty-print an AST back to canonical MiniLang source.

Parentheses are emitted only where the precedence table requires them. Given
a parent operator of precedence ``p``:

* a left operand needs parentheses if its precedence is ``< p``, or ``<= p``
  when the operator is non-associative: ``(a < b) == c`` is fine unparenthesized
  only because ``==`` and ``<`` are different levels, while ``(a != b) != c``
  must keep its parentheses (docs/FAILURES.md, F-003);
* a right operand needs parentheses if its precedence is ``<= p``, because all
  binary operators are left-associative or non-associative, so ``a - (b - c)``
  must keep its parentheses.

The formatter is tested by the round-trip property
``parse(format(parse(src))) == parse(src)``. If formatter and parser disagree
on precedence, that test fails.
"""

from __future__ import annotations

from forgecompile.ast import nodes as ast
from forgecompile.ast.operators import NON_ASSOCIATIVE, Precedence
from forgecompile.ast.types import VOID

INDENT = "    "


def _float_literal(value: float) -> str:
    text = repr(value)
    # repr may produce "1e+20" or "inf"; MiniLang float literals need digits '.' digits.
    if "inf" in text or "nan" in text:
        raise ValueError(f"float value {text} has no MiniLang literal syntax")
    if "e" in text or "E" in text:
        mantissa, exponent = text.lower().split("e")
        if "." not in mantissa:
            mantissa += ".0"
        return f"{mantissa}e{exponent}"
    return text


def expr_precedence(expr: ast.Expr) -> Precedence:
    if isinstance(expr, ast.Binary):
        return expr.op.precedence
    if isinstance(expr, ast.Cast):
        return Precedence.CAST
    if isinstance(expr, ast.Unary):
        return Precedence.UNARY
    return Precedence.POSTFIX  # literals, names, calls, indexing: atomic


def format_expr(expr: ast.Expr) -> str:
    def wrap(child: ast.Expr, needs_parens: bool) -> str:
        text = format_expr(child)
        return f"({text})" if needs_parens else text

    match expr:
        case ast.IntLiteral(value=v):
            return str(v)
        case ast.FloatLiteral(value=v):
            return _float_literal(v)
        case ast.BoolLiteral(value=v):
            return "true" if v else "false"
        case ast.Name(ident=name):
            return name
        case ast.ArrayLiteral(elements=elements):
            return "[" + ", ".join(format_expr(e) for e in elements) + "]"
        case ast.Call(callee=callee, args=args):
            return f"{callee}(" + ", ".join(format_expr(a) for a in args) + ")"
        case ast.Index(base=base, index=index):
            return f"{wrap(base, expr_precedence(base) < Precedence.POSTFIX)}[{format_expr(index)}]"
        case ast.Unary(op=op, operand=operand):
            inner = wrap(operand, expr_precedence(operand) < Precedence.UNARY)
            # Avoid gluing "- -x" into "--x" (still lexes fine, but reads badly).
            separator = " " if inner.startswith(op.value) else ""
            return f"{op.value}{separator}{inner}"
        case ast.Cast(expr=inner, target=target):
            return f"{wrap(inner, expr_precedence(inner) < Precedence.CAST)} as {target}"
        case ast.Binary(op=op, left=left, right=right):
            p = op.precedence
            left_needs = (
                expr_precedence(left) <= p if p in NON_ASSOCIATIVE else expr_precedence(left) < p
            )
            left_text = wrap(left, left_needs)
            right_text = wrap(right, expr_precedence(right) <= p)
            return f"{left_text} {op.value} {right_text}"
    raise TypeError(f"not an expression node: {type(expr).__name__}")


def _format_block(block: ast.Block, depth: int) -> list[str]:
    lines = ["{"]
    for stmt in block.statements:
        lines.extend(_format_stmt(stmt, depth + 1))
    lines.append(INDENT * depth + "}")
    return lines


def _attach(header: str, block_lines: list[str]) -> list[str]:
    """Join a header like 'while x ' with a block's lines ('{', ..., '}')."""
    return [header + block_lines[0], *block_lines[1:]]


def _format_stmt(stmt: ast.Stmt, depth: int) -> list[str]:
    pad = INDENT * depth
    match stmt:
        case ast.LetStmt(name=name, declared_type=declared, init=init):
            text = f"let {name}"
            if declared is not None:
                text += f": {declared}"
            if init is not None:
                text += f" = {format_expr(init)}"
            return [f"{pad}{text};"]
        case ast.AssignStmt(target=target, value=value):
            return [f"{pad}{format_expr(target)} = {format_expr(value)};"]
        case ast.ExprStmt(expr=expr):
            return [f"{pad}{format_expr(expr)};"]
        case ast.ReturnStmt(value=None):
            return [f"{pad}return;"]
        case ast.ReturnStmt(value=value):
            assert value is not None
            return [f"{pad}return {format_expr(value)};"]
        case ast.BreakStmt():
            return [f"{pad}break;"]
        case ast.ContinueStmt():
            return [f"{pad}continue;"]
        case ast.Block():
            return [
                pad + line if i == 0 else line for i, line in enumerate(_format_block(stmt, depth))
            ]
        case ast.WhileStmt(condition=cond, body=body):
            return _attach(f"{pad}while {format_expr(cond)} ", _format_block(body, depth))
        case ast.ForStmt(var=var, start=start, end=end, body=body):
            header = f"{pad}for {var} in {format_expr(start)}..{format_expr(end)} "
            return _attach(header, _format_block(body, depth))
        case ast.IfStmt():
            return _format_if(stmt, depth, pad)
    raise TypeError(f"not a statement node: {type(stmt).__name__}")


def _format_if(stmt: ast.IfStmt, depth: int, prefix: str) -> list[str]:
    lines = _attach(
        f"{prefix}if {format_expr(stmt.condition)} ", _format_block(stmt.then_body, depth)
    )
    else_body = stmt.else_body
    if else_body is None:
        return lines
    closing = lines.pop()  # "    }" - the else clause continues on this line
    if len(else_body.statements) == 1 and isinstance(else_body.statements[0], ast.IfStmt):
        lines.extend(_format_if(else_body.statements[0], depth, f"{closing} else "))
    else:
        lines.extend(_attach(f"{closing} else ", _format_block(else_body, depth)))
    return lines


def format_function(fn: ast.FunctionDecl) -> str:
    params = ", ".join(f"{p.name}: {p.type}" for p in fn.params)
    ret = "" if fn.return_type == VOID else f" -> {fn.return_type}"
    return "\n".join(_attach(f"fn {fn.name}({params}){ret} ", _format_block(fn.body, 0)))


def format_program(program: ast.Program) -> str:
    return "\n\n".join(format_function(fn) for fn in program.functions) + "\n"

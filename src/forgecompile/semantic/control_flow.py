"""AST-level control-flow facts: can a statement *complete normally*?

Used for the "missing return" check (LANGUAGE.md §6). A statement completes
normally if control can flow past its end to the next statement. This mirrors
Java's definite-completion rules (JLS §14.22), simplified for MiniLang:

* ``return``, ``break``, ``continue``  -> never complete normally
* block                                -> completes iff its statements, run in
                                          order, can reach the end
* ``if c {A} else {B}``                -> completes iff A or B completes
* ``if c {A}`` (no else)               -> always completes (c may be false)
* ``while true {B}``                   -> completes iff B contains a ``break``
                                          that targets this loop
* other ``while`` / ``for``            -> always complete (may run 0 times)

The analysis is conservative. It never claims "always returns" when some path
falls through, but it may reject a program that would in fact always return
(e.g. ``while 1 < 2 { return 1; }``). This is the standard trade-off: deciding
the question exactly is undecidable in general.
"""

from __future__ import annotations

from forgecompile.ast import nodes as ast


def completes_normally(stmt: ast.Stmt) -> bool:
    match stmt:
        case ast.ReturnStmt() | ast.BreakStmt() | ast.ContinueStmt():
            return False
        case ast.Block(statements=statements):
            return all(completes_normally(s) for s in statements)
        case ast.IfStmt(then_body=then_body, else_body=else_body):
            if else_body is None:
                return True
            return completes_normally(then_body) or completes_normally(else_body)
        case ast.WhileStmt(condition=ast.BoolLiteral(value=True), body=body):
            return _contains_break(body)
        case _:
            return True


def _contains_break(stmt: ast.Stmt) -> bool:
    """True if ``stmt`` contains a ``break`` that exits the *enclosing* loop.

    Breaks inside nested loops belong to those loops and are not counted.
    """
    match stmt:
        case ast.BreakStmt():
            return True
        case ast.Block(statements=statements):
            return any(_contains_break(s) for s in statements)
        case ast.IfStmt(then_body=then_body, else_body=else_body):
            return _contains_break(then_body) or (
                else_body is not None and _contains_break(else_body)
            )
        case _:  # nested while/for own their breaks; other statements have none
            return False

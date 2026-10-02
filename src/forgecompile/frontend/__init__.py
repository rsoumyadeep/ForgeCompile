"""MiniLang frontend: lexer and parser.

Typical use::

    from forgecompile.frontend import parse_source
    program = parse_source(text, "prog.mini")   # raises CompileError on syntax errors
"""

from __future__ import annotations

from forgecompile.ast.nodes import Program
from forgecompile.diagnostics import CompileError, SourceFile
from forgecompile.frontend.lexer import tokenize
from forgecompile.frontend.parser import Parser


def parse_source(text: str, filename: str = "<input>") -> Program:
    """Lex and parse ``text``. Raises :class:`CompileError` listing every syntax error found."""
    source = SourceFile(filename, text)
    tokens, lex_errors = tokenize(source)
    parser = Parser(tokens)
    program = parser.parse_program()
    errors = lex_errors + parser.diagnostics
    if errors:
        errors.sort(key=lambda d: d.span.start if d.span else -1)
        raise CompileError(errors)
    return program


__all__ = ["parse_source"]

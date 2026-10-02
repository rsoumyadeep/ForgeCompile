"""Compiler driver: runs the pipeline stages in order.

Each function runs the pipeline up to one stage and returns that stage's
output. Every stage raises :class:`~forgecompile.diagnostics.CompileError` on
failure. Later phases extend this module with lowering, optimization and code
generation.
"""

from __future__ import annotations

from dataclasses import dataclass

from forgecompile.ast.nodes import Program
from forgecompile.frontend import parse_source
from forgecompile.semantic import ProgramInfo, analyze


@dataclass
class CheckedProgram:
    """A parsed and type-checked program: AST annotated in place, plus symbol info."""

    ast: Program
    info: ProgramInfo


def check_source(text: str, filename: str = "<input>") -> CheckedProgram:
    """Parse and type-check MiniLang source."""
    program = parse_source(text, filename)
    info = analyze(program)
    return CheckedProgram(program, info)

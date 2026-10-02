"""Source locations and compiler diagnostics, shared by every compiler phase.

A :class:`Span` identifies a range of source text. Every token, AST node and
diagnostic carries one, so an error found in any phase (lexer, parser, type
checker, ...) can point at the exact source characters responsible.

Diagnostics are *collected* rather than raised one at a time: a phase records
as many problems as it can and then raises a single :class:`CompileError`.
Reporting several errors per run is much friendlier than a fix-one-rerun loop.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True)
class Span:
    """Half-open character range ``[start, end)`` plus the 1-based line/column of ``start``."""

    start: int
    end: int
    line: int
    column: int

    def cover(self, other: Span) -> Span:
        """Smallest span containing both ``self`` and ``other`` (``self`` must start first)."""
        return Span(self.start, max(self.end, other.end), self.line, self.column)

    def __str__(self) -> str:
        return f"{self.line}:{self.column}"


@dataclass(frozen=True)
class SourceFile:
    """Source text plus a precomputed index of line start offsets."""

    name: str
    text: str
    _line_starts: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        starts = [0]
        starts.extend(i + 1 for i, ch in enumerate(self.text) if ch == "\n")
        object.__setattr__(self, "_line_starts", tuple(starts))

    def location(self, offset: int) -> tuple[int, int]:
        """Return the 1-based ``(line, column)`` of a character offset."""
        line_index = bisect.bisect_right(self._line_starts, offset) - 1
        return line_index + 1, offset - self._line_starts[line_index] + 1

    def span(self, start: int, end: int) -> Span:
        line, column = self.location(start)
        return Span(start, end, line, column)

    def line_text(self, line: int) -> str:
        """Text of a 1-based line, without its trailing newline."""
        start = self._line_starts[line - 1]
        end = self._line_starts[line] - 1 if line < len(self._line_starts) else len(self.text)
        return self.text[start:end].rstrip("\r")


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"


@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    message: str
    span: Span | None
    notes: tuple[str, ...] = ()

    @classmethod
    def error(cls, message: str, span: Span | None, *notes: str) -> Diagnostic:
        return cls(Severity.ERROR, message, span, tuple(notes))


class CompileError(Exception):
    """Raised by a compiler phase that found one or more errors."""

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        if not diagnostics:
            raise ValueError("CompileError requires at least one diagnostic")
        self.diagnostics = diagnostics
        super().__init__(diagnostics[0].message)


def render(diagnostic: Diagnostic, source: SourceFile | None = None) -> str:
    """Render a diagnostic in the familiar rustc/clang style::

    error: expected ';' after expression
      --> prog.mini:3:14
       |
     3 |     let x = 5
       |              ^
       = note: ...
    """
    lines = [f"{diagnostic.severity}: {diagnostic.message}"]
    span = diagnostic.span
    if span is not None:
        name = source.name if source is not None else "<input>"
        lines.append(f"  --> {name}:{span.line}:{span.column}")
        if source is not None:
            gutter = len(str(span.line))
            text = source.line_text(span.line)
            # Underline to the end of the span, but never past this line.
            width = max(1, min(span.end - span.start, len(text) - span.column + 1))
            pad = " " * gutter
            lines.append(f"{pad} |")
            lines.append(f"{span.line} | {text}")
            lines.append(f"{pad} | {' ' * (span.column - 1)}{'^' * width}")
    lines.extend(f"  = note: {note}" for note in diagnostic.notes)
    return "\n".join(lines)


def render_all(diagnostics: list[Diagnostic], source: SourceFile | None = None) -> str:
    return "\n\n".join(render(d, source) for d in diagnostics)

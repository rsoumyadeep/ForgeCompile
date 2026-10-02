"""Helpers shared by CLI subcommands: exit codes, source loading, error reporting."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from forgecompile.diagnostics import CompileError, SourceFile, render_all

EXIT_OK = 0
EXIT_COMPILE_ERROR = 1
EXIT_USAGE = 2


class CliError(Exception):
    """A user-facing error that is not a compile error (e.g. a missing file)."""


def read_source(path: str) -> SourceFile:
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise CliError(f"no such file: {path}") from None
    except UnicodeDecodeError:
        raise CliError(f"{path} is not valid UTF-8 text") from None
    except OSError as exc:
        raise CliError(f"cannot read {path}: {exc.strerror}") from None
    return SourceFile(str(file), text)


def run_compile_step(source: SourceFile, step: Callable[[], int]) -> int:
    """Run ``step``; render any CompileError against ``source`` to stderr."""
    try:
        return step()
    except CompileError as error:
        print(render_all(error.diagnostics, source), file=sys.stderr)
        count = len(error.diagnostics)
        print(f"\n{count} error{'s' if count != 1 else ''} found", file=sys.stderr)
        return EXIT_COMPILE_ERROR

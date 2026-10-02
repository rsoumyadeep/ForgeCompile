"""Shared test helpers (importable from any test module as fixtures)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from forgecompile.driver import build_ir, check_source
from forgecompile.ir.interpreter import IRExecutionResult, run_module
from forgecompile.runtime.ast_interpreter import ExecutionResult, run_program

REPO_ROOT = Path(__file__).parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"
PROGRAMS_DIR = Path(__file__).parent / "programs"


def run_ast(source: str) -> ExecutionResult:
    return run_program(check_source(source).ast)


def run_ir(source: str, ssa: bool = True) -> IRExecutionResult:
    return run_module(build_ir(source, ssa=ssa))


@pytest.fixture
def ast_run() -> Callable[[str], ExecutionResult]:
    return run_ast


@pytest.fixture
def ir_run() -> Callable[..., IRExecutionResult]:
    return run_ir

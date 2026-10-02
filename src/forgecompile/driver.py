"""Compiler driver: runs the pipeline stages in order.

    check_source  : source -> parsed + type-checked AST
    lower_source  : source -> pre-SSA IR
    build_ir      : source -> verified IR (SSA by default)
    compile_to_llvm: source -> optimized IR -> verified LLVM IR text

Frontend stages raise :class:`~forgecompile.diagnostics.CompileError` on bad
input. IR verification failures raise ``IRVerificationError``: those are
compiler bugs, not user errors. Later phases add optimization and codegen.
"""

from __future__ import annotations

from dataclasses import dataclass

from forgecompile.ast.nodes import Program
from forgecompile.backend.llvm_emitter import emit_module, verify_llvm
from forgecompile.frontend import parse_source
from forgecompile.ir.function import Module
from forgecompile.ir.ssa import construct_ssa_module
from forgecompile.ir.verify import verify_module
from forgecompile.lowering import lower_program
from forgecompile.optimization.pass_manager import PipelineReport, optimize
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


def lower_source(text: str, filename: str = "<input>") -> Module:
    """Parse, type-check and lower MiniLang source to pre-SSA IR."""
    return lower_program(check_source(text, filename))


def build_ir(text: str, filename: str = "<input>", ssa: bool = True) -> Module:
    """Source -> IR, verified after lowering and (if ``ssa``) after SSA construction."""
    module = lower_source(text, filename)
    verify_module(module)
    if ssa:
        construct_ssa_module(module)
        verify_module(module, ssa=True)
    return module


def compile_to_llvm(
    text: str, filename: str = "<input>", pipeline: list[str] | None = None
) -> tuple[str, PipelineReport]:
    """Source -> SSA IR -> ForgeCompile passes -> LLVM IR text (verified by llvmlite)."""
    module = build_ir(text, filename)
    report = optimize(module, pipeline or [])
    llvm_ir = emit_module(module, filename)
    verify_llvm(llvm_ir)
    return llvm_ir, report

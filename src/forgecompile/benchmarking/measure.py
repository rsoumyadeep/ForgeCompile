"""Measurements for one (benchmark, configuration) pair.

A *configuration* is a ForgeCompile pass pipeline plus an LLVM optimization
level. Measurements, and how noisy each one is:

=====================  =========================================  ==============
metric                 how                                        determinism
=====================  =========================================  ==============
interp_steps / cost    IR interpreter on the *small* instance     exact
static IR size         instructions after ForgeCompile passes     exact
text_bytes             ``.text`` size of the LLVM object file      exact
pass_ms                ForgeCompile pipeline time                 noisy
native_compile_s       ``zig cc`` time                            noisy
native times           wall-clock runs of the *large* instance    noisy
=====================  =========================================  ==============
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

from forgecompile.backend.llvm_emitter import emit_module, verify_llvm
from forgecompile.backend.native import EXE_SUFFIX, compile_llvm, run_executable
from forgecompile.driver import build_ir
from forgecompile.ir.interpreter import IRInterpreter
from forgecompile.optimization.pass_manager import optimize
from forgecompile.optimization.utils import module_instruction_count


@dataclass(frozen=True)
class BenchConfig:
    name: str
    passes: tuple[str, ...]
    llvm_opt: int


@dataclass
class StaticMetrics:
    ir_instructions: int
    llvm_ir_lines: int
    text_bytes: int
    pass_ms: float


@dataclass
class InterpMetrics:
    steps: int
    cost: float
    seconds: float
    opcode_counts: dict[str, int]
    stdout_sha1: str


@dataclass
class NativeMetrics:
    executable: Path
    compile_seconds: float
    times: list[float] = field(default_factory=list)
    stdout_sha1: str = ""


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def compile_config(source: str, config: BenchConfig) -> tuple[str, StaticMetrics]:
    """Optimize with ForgeCompile and emit verified LLVM IR; return it with static metrics."""
    module = build_ir(source)
    start = time.perf_counter()
    optimize(module, list(config.passes), verify=False)
    pass_ms = (time.perf_counter() - start) * 1000
    ir_size = module_instruction_count(module)
    llvm_ir = emit_module(module)
    verify_llvm(llvm_ir)
    return llvm_ir, StaticMetrics(
        ir_size, llvm_ir.count("\n"), text_bytes(llvm_ir, config.llvm_opt), pass_ms
    )


def text_bytes(llvm_ir: str, llvm_opt: int) -> int:
    """Machine-code size: total size of executable-code sections when LLVM compiles the module.

    The C runtime and libc are excluded, since they are identical for every
    configuration, so differences reflect only the generated code.
    """
    import llvmlite.binding as llvm

    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    machine = llvm.Target.from_default_triple().create_target_machine(opt=llvm_opt)
    obj = llvm.ObjectFileRef.from_data(machine.emit_object(llvm.parse_assembly(llvm_ir)))
    # is_text() rather than name matching: names vary by object format and code model
    # (e.g. ".text" vs ".ltext"), and some sections have no name at all.
    return sum(section.size() for section in obj.sections() if section.is_text())


def interpret(source: str, config: BenchConfig) -> InterpMetrics:
    module = build_ir(source)
    optimize(module, list(config.passes), verify=False)
    start = time.perf_counter()
    result = IRInterpreter(module).run()
    elapsed = time.perf_counter() - start
    return InterpMetrics(
        result.steps, result.cost, elapsed, dict(result.opcode_counts), sha1(result.stdout)
    )


def build_native(llvm_ir: str, config: BenchConfig, out_dir: Path, stem: str) -> NativeMetrics:
    exe = out_dir / f"{stem}__{config.name}{EXE_SUFFIX}"
    build = compile_llvm(llvm_ir, exe, config.llvm_opt)
    build.llvm_file.unlink(missing_ok=True)
    return NativeMetrics(exe, build.compile_seconds)


def time_native(metrics: NativeMetrics, timeout: float = 120.0) -> tuple[float, str]:
    """Run once; return (wall seconds, stdout hash). Raises on a non-zero exit status."""
    result = run_executable(metrics.executable, timeout=timeout)
    if result.exit_code != 0:
        raise RuntimeError(
            f"{metrics.executable.name} exited with {result.exit_code}: {result.stderr}"
        )
    return result.seconds, sha1(result.stdout)

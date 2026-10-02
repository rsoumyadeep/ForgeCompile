"""Build and run native executables: LLVM IR + C runtime -> ``zig cc`` -> executable.

``zig cc`` is clang plus lld plus a bundled libc, distributed as the ``ziglang``
pip wheel, so no system compiler is needed (DECISIONS D-002). ``clang`` on PATH
is used instead if it is present and preferred.

``llvm_opt_level`` selects how much optimization *LLVM* applies when compiling
our IR (``-O0`` ... ``-O3``). Experiments use ``-O0`` to isolate ForgeCompile's
own optimizations: LLVM then only selects instructions and allocates registers.
Higher levels give the "what would LLVM do" comparison baselines.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from forgecompile.backend.llvm_emitter import BackendError

RUNTIME_SOURCE = Path(__file__).parent / "runtime" / "fc_runtime.c"
EXE_SUFFIX = ".exe" if os.name == "nt" else ""
DEFAULT_RUN_TIMEOUT_S = 60


def compiler_command() -> list[str]:
    """Command prefix for the C/LLVM compiler driver (``zig cc`` or ``clang``)."""
    if os.environ.get("FORGECOMPILE_CC") == "clang" and shutil.which("clang"):
        return ["clang"]
    try:
        import ziglang  # noqa: F401
    except ImportError:
        if shutil.which("clang"):
            return ["clang"]
        raise BackendError("no native toolchain: install the 'ziglang' package or clang") from None
    return [sys.executable, "-m", "ziglang", "cc"]


@dataclass
class NativeBuild:
    executable: Path
    llvm_file: Path
    compile_seconds: float


@dataclass
class NativeResult:
    stdout: str
    stderr: str
    exit_code: int
    seconds: float

    @property
    def observable(self) -> tuple[str, int]:
        return self.stdout, self.exit_code


def compile_llvm(
    llvm_ir: str,
    output: Path,
    llvm_opt_level: int = 0,
    keep_ll: Path | None = None,
) -> NativeBuild:
    """Compile LLVM IR text plus the runtime into ``output``. Raises BackendError on failure."""
    if llvm_opt_level not in (0, 1, 2, 3):
        raise ValueError(f"LLVM optimization level must be 0-3, got {llvm_opt_level}")
    output.parent.mkdir(parents=True, exist_ok=True)
    ll_path = keep_ll if keep_ll is not None else output.with_suffix(".ll")
    ll_path.write_text(llvm_ir, encoding="utf-8", newline="\n")
    command = [
        *compiler_command(),
        f"-O{llvm_opt_level}",
        "-Wno-override-module",
        str(ll_path),
        str(RUNTIME_SOURCE),
        "-o",
        str(output),
    ]
    start = time.perf_counter()
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        raise BackendError(f"native compilation failed:\n{proc.stderr.strip()}")
    return NativeBuild(output, ll_path, elapsed)


def run_executable(executable: Path, timeout: float = DEFAULT_RUN_TIMEOUT_S) -> NativeResult:
    """Run a built program, capturing raw output bytes (no newline translation)."""
    start = time.perf_counter()
    try:
        proc = subprocess.run([str(executable)], capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise BackendError(f"{executable.name} did not finish within {timeout}s") from exc
    elapsed = time.perf_counter() - start
    # Windows reports exit codes as unsigned 32-bit; MiniLang statuses are 0..255.
    return NativeResult(
        proc.stdout.decode("utf-8"),
        proc.stderr.decode("utf-8", errors="replace"),
        proc.returncode & 0xFFFFFFFF,
        elapsed,
    )


def build_and_run(llvm_ir: str, llvm_opt_level: int = 0) -> tuple[NativeBuild, NativeResult]:
    """Compile into a temporary directory and run once. Used by tests and the CLI."""
    with tempfile.TemporaryDirectory(prefix="forgecompile-") as tmp:
        exe = Path(tmp) / f"program{EXE_SUFFIX}"
        build = compile_llvm(llvm_ir, exe, llvm_opt_level)
        result = run_executable(exe)
        return build, result

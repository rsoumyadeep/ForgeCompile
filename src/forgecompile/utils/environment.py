"""Capture the software/hardware environment and detect backend tools.

Every experiment stores the output of :func:`collect_environment` next to its
results. Without it, a timing number is not reproducible: the same benchmark
can differ by 2x between a laptop and a server CPU.

Toolchain detection matters because ForgeCompile's backend is assembled from
pip-installable pieces (see docs/DECISIONS.md, D-002):

* ``llvmlite`` - Python bindings to LLVM (IR parsing/verification, LLVM's own
  optimizer as a comparison baseline, JIT, object-file emission).
* ``zig``      - the ``ziglang`` wheel bundles clang + lld; ``zig cc`` links
  LLVM IR / object files into native executables without a system compiler.
* ``clang``    - used instead of zig when present on PATH.
"""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from forgecompile import __version__

_SUBPROCESS_TIMEOUT_S = 30


@dataclass(frozen=True)
class ToolStatus:
    """Availability of one external tool or optional library."""

    name: str
    available: bool
    version: str | None = None
    detail: str | None = None


def _run(cmd: list[str], cwd: Path | None = None) -> str | None:
    """Run a command and return stripped stdout, or None if it fails."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def detect_llvmlite() -> ToolStatus:
    try:
        llvmlite = importlib.import_module("llvmlite")
        binding = importlib.import_module("llvmlite.binding")
    except ImportError:
        return ToolStatus("llvmlite", False, detail="not installed (needed from Phase 5)")
    llvm_version = ".".join(str(part) for part in binding.llvm_version_info)
    return ToolStatus("llvmlite", True, llvmlite.__version__, f"LLVM {llvm_version}")


def detect_zig() -> ToolStatus:
    """Prefer the ``ziglang`` wheel (pinned via pip), fall back to ``zig`` on PATH."""
    version = _run([sys.executable, "-m", "ziglang", "version"])
    if version:
        return ToolStatus("zig", True, version, "python -m ziglang")
    zig = shutil.which("zig")
    if zig:
        version = _run([zig, "version"])
        if version:
            return ToolStatus("zig", True, version, zig)
    return ToolStatus("zig", False, detail="not found (pip install ziglang; needed from Phase 5)")


def detect_clang() -> ToolStatus:
    clang = shutil.which("clang")
    if not clang:
        return ToolStatus("clang", False, detail="not on PATH (optional; zig cc is used instead)")
    output = _run([clang, "--version"])
    first_line = output.splitlines()[0] if output else None
    return ToolStatus("clang", True, first_line, clang)


def detect_tools() -> list[ToolStatus]:
    return [detect_llvmlite(), detect_zig(), detect_clang()]


def git_revision(repo_dir: Path | None = None) -> dict[str, object] | None:
    """Return ``{"commit": sha, "dirty": bool}`` or None outside a git checkout."""
    commit = _run(["git", "rev-parse", "HEAD"], cwd=repo_dir)
    if commit is None:
        return None
    status = _run(["git", "status", "--porcelain"], cwd=repo_dir)
    return {"commit": commit, "dirty": bool(status)}


def source_tree_revision(repo_dir: Path, subdir: str = "src/forgecompile") -> str | None:
    """Git tree hash of ``subdir`` at HEAD, or None if it has uncommitted changes (or no git).

    Unlike the commit hash, it changes only when the compiler's own code changes, so a
    documentation-only commit does not invalidate caches derived from compiler behaviour.
    """
    if _run(["git", "status", "--porcelain", "--", subdir], cwd=repo_dir):
        return None
    return _run(["git", "rev-parse", f"HEAD:{subdir}"], cwd=repo_dir)


def collect_environment(repo_dir: Path | None = None) -> dict[str, object]:
    """Return a JSON-serialisable description of the current environment."""
    return {
        "forgecompile_version": __version__,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "cpu_count": os.cpu_count(),
        "git": git_revision(repo_dir),
        "tools": [asdict(tool) for tool in detect_tools()],
    }

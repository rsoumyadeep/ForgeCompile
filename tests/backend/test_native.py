"""Native executables: differential testing against the interpreters.

Marked ``native``: they build real executables with ``zig cc`` (about 0.3 s each
once zig's cache is warm; the very first build compiles zig's libc and can take
a minute). Deselect with ``-m "not native"``.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from forgecompile.backend.native import build_and_run, compiler_command
from forgecompile.cli.main import main as cli_main
from forgecompile.driver import build_ir, check_source, compile_to_llvm
from forgecompile.ir.interpreter import run_module
from forgecompile.optimization.pass_manager import PRESETS, available_passes
from forgecompile.runtime.ast_interpreter import run_program
from forgecompile.testing.program_generator import generate_program

ROOT = Path(__file__).parents[2]
EXAMPLES = sorted((ROOT / "examples").glob("*.mini"))
EDGE = ROOT / "tests/programs/semantics_edge.mini"

pytestmark = pytest.mark.native


@pytest.fixture(scope="module", autouse=True)
def _toolchain() -> None:
    try:
        compiler_command()
    except Exception as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"no native toolchain: {exc}")


def native(source: str, passes: list[str], llvm_opt: int) -> tuple[str, int]:
    llvm_ir, _ = compile_to_llvm(source, "t.mini", passes)
    _, result = build_and_run(llvm_ir, llvm_opt)
    return result.observable


@pytest.mark.parametrize(("preset", "llvm_opt"), [("O0", 0), ("O2", 2)])
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_native_match_golden(path: Path, preset: str, llvm_opt: int) -> None:
    expected = (path.with_suffix(".expected").read_text("utf-8"), 0)
    assert native(path.read_text("utf-8"), PRESETS[preset], llvm_opt) == expected


@pytest.mark.parametrize(("preset", "llvm_opt"), [("O0", 0), ("O0", 3), ("O2", 3)])
def test_semantic_corner_cases(preset: str, llvm_opt: int) -> None:
    """INT_MIN / -1, saturating casts, NaN spelling, libc name clashes, deep recursion, exit 44.

    LLVM -O3 matters here: it is where LLVM would exploit undefined behaviour
    if the emitter leaked any.
    """
    expected = (EDGE.with_suffix(".expected").read_text("utf-8"), 44)
    assert native(EDGE.read_text("utf-8"), PRESETS[preset], llvm_opt) == expected


@pytest.mark.parametrize(
    ("body", "stdout", "message"),
    [
        ("print(1); let z = 0; print(5 / z);", "1\n", "division by zero"),
        ("print(2); let z = 0; print(5 % z);", "2\n", "remainder by zero"),
        ("let a: [int; 3]; let i = 3; print(7); a[i] = 1;", "7\n", "index 3 out of bounds for array of length 3"),
    ],
)  # fmt: skip
def test_runtime_errors(body: str, stdout: str, message: str) -> None:
    source = f"fn main() {{ {body} }}"
    llvm_ir, _ = compile_to_llvm(source, "t.mini")
    _, result = build_and_run(llvm_ir, 2)
    assert result.observable == (stdout, 101)
    assert result.stderr.strip() == f"runtime error: {message}"
    assert run_program(check_source(source).ast).observable == (stdout, 101)


def test_generated_programs_native_match_interpreter() -> None:
    names = sorted(available_passes())
    rng = random.Random(11)
    for seed in range(12):
        source = generate_program(seed)
        reference = run_module(build_ir(source)).observable
        passes = [rng.choice(names) for _ in range(rng.randrange(0, 8))]
        assert native(source, passes, rng.choice([0, 2])) == reference, (seed, passes)


@pytest.mark.slow
def test_generated_programs_native_extended() -> None:
    names = sorted(available_passes())
    rng = random.Random(12)
    failures = []
    for seed in range(100, 220):
        source = generate_program(seed)
        reference = run_module(build_ir(source)).observable
        passes = [rng.choice(names) for _ in range(rng.randrange(0, 10))]
        llvm_opt = rng.choice([0, 1, 2, 3])
        if native(source, passes, llvm_opt) != reference:
            failures.append((seed, passes, llvm_opt))
    assert failures == []


def test_cli_build_and_native_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exe = tmp_path / "gcd.exe"
    assert (
        cli_main(
            ["build", "-O", "2", "--emit-llvm", "-o", str(exe), str(ROOT / "examples/gcd.mini")]
        )
        == 0
    )
    assert exe.exists() and exe.with_suffix(".ll").exists()
    assert cli_main(["run", "--engine", "native", str(ROOT / "examples/gcd.mini")]) == 0
    assert capsys.readouterr().out == "21\n21\n42\ntrue\n"

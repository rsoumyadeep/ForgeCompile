"""LLVM IR emission: mapping rules and llvmlite verification (no native toolchain needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecompile.backend.llvm_emitter import (
    BackendError,
    emit_module,
    llvm_float,
    optimize_llvm,
    verify_llvm,
)
from forgecompile.driver import build_ir, compile_to_llvm
from forgecompile.optimization.pass_manager import PRESETS, optimize
from forgecompile.testing.program_generator import generate_program

ROOT = Path(__file__).parents[2]
PROGRAMS = [
    *sorted((ROOT / "examples").glob("*.mini")),
    ROOT / "tests/programs/semantics_edge.mini",
]


def llvm_of(source: str, passes: list[str] | None = None) -> str:
    text, _ = compile_to_llvm(source, "t.mini", passes or [])
    return text


def function_body(llvm_ir: str, name: str) -> str:
    start = llvm_ir.index(f"@mini_{name}(")
    return llvm_ir[start : llvm_ir.index("\n}", start)]


@pytest.mark.parametrize("preset", ["O0", "O2"])
@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: p.name)
def test_programs_emit_verified_llvm(path: Path, preset: str) -> None:
    llvm_of(path.read_text("utf-8"), PRESETS[preset])  # verify_llvm runs inside


def test_generated_programs_emit_verified_llvm() -> None:
    for seed in range(60):
        module = build_ir(generate_program(seed))
        optimize(module, PRESETS["O2"] if seed % 2 else [])
        verify_llvm(emit_module(module))


def test_division_lowering_depends_on_divisor() -> None:
    body = function_body(
        llvm_of(
            "fn f(a: int, b: int) -> int { return a / 7 + a % 7 + a / b + a / -1; }\nfn main() {}"
        ),
        "f",
    )
    assert "sdiv i64 %v.a, 7" in body and "srem i64 %v.a, 7" in body  # safe constant divisor
    assert body.count("@__fc_sdiv(") == 2  # variable divisor and -1 need the checked helper


def test_float_compare_ne_is_unordered_and_constants_are_exact() -> None:
    body = function_body(llvm_of("fn f(x: float) -> bool { return x != 0.1; }\nfn main() {}"), "f")
    assert f"fcmp une double %v.x, {llvm_float(0.1)}" in body
    assert llvm_float(0.1) == "0x3FB999999999999A"


def test_saturating_cast_bool_print_and_copy_forwarding() -> None:
    llvm_ir = llvm_of("fn main() { let x = 2.5; let y = x as int; print(y); print(y > 1); }")
    body = function_body(llvm_ir, "main")
    assert "@llvm.fptosi.sat.i64.f64" in body
    assert "zext i1" in body and "@fc_print_bool(i32" in body
    assert "copy" not in body  # copies are forwarded, never emitted


def test_names_are_prefixed_to_avoid_libc_and_label_clashes() -> None:
    llvm_ir = llvm_of(
        "fn abs(entry: int) -> int { let b = entry; return b; }\nfn main() { print(abs(1)); }"
    )
    assert "define i64 @mini_abs(i64 %v.entry)" in llvm_ir
    assert "b.entry:" in llvm_ir  # block label namespace differs from %v.entry


def test_main_wrapper_reduces_exit_status_modulo_256() -> None:
    llvm_ir = llvm_of("fn main() -> int { return 300; }")
    wrapper = llvm_ir[llvm_ir.index("define i32 @main()") :]
    assert "call void @fc_runtime_init()" in wrapper
    assert "and i64 %r, 255" in wrapper


def test_void_main_returns_zero() -> None:
    llvm_ir = llvm_of("fn main() { print(1); }")
    assert "call void @mini_main()\n  ret i32 0" in llvm_ir


def test_llvm_float_special_values() -> None:
    assert llvm_float(float("inf")) == "0x7FF0000000000000"
    assert llvm_float(-0.0) == "0x8000000000000000"
    assert llvm_float(float("nan")).startswith("0x7FF8")


def test_verify_llvm_reports_errors() -> None:
    with pytest.raises(BackendError, match="invalid LLVM IR"):
        verify_llvm("define i64 @f() {\nentry:\n  ret i32 0\n}\n")


def test_optimize_llvm_runs_llvm_pipeline() -> None:
    optimized = optimize_llvm(llvm_of("fn f(x: int) -> int { return x + 0; }\nfn main() {}"), 2)
    assert "@mini_f" in optimized
    assert "add i64" not in function_body(optimized, "f")

"""Lowering: structural properties of the generated IR."""

from __future__ import annotations

from forgecompile.driver import build_ir, lower_source
from forgecompile.ir.instructions import (
    AllocaInst,
    BoundsCheckInst,
    LoadInst,
    MemZeroInst,
    Opcode,
    PtrAddInst,
    StoreInst,
)
from forgecompile.ir.printer import format_function
from forgecompile.ir.values import Constant, IRType
from forgecompile.ir.verify import verify_module


def ops(text: str, fn: str = "main") -> list[Opcode]:
    module = lower_source(text)
    verify_module(module)
    return [inst.opcode for inst in module.functions[fn].instructions()]


def test_straight_line_function_text() -> None:
    module = lower_source(
        "fn add(a: int, b: int) -> int { let c = a + b; return c * 2; }\nfn main() {}"
    )
    assert format_function(module.functions["add"]) == "\n".join(
        [
            "func @add(%a: i64, %b: i64) -> i64 {",
            "entry:",
            "    %t1: i64 = add %a, %b",
            "    %c: i64 = copy %t1",
            "    %t2: i64 = mul %c, 2",
            "    ret %t2",
            "}",
        ]
    )


def test_types_map_to_ir_types() -> None:
    module = lower_source(
        "fn f(x: float, b: bool, a: [int; 3]) -> float { return x; }\nfn main() {}"
    )
    assert [p.type for p in module.functions["f"].params] == [IRType.F64, IRType.I1, IRType.PTR]
    assert module.functions["main"].return_type is IRType.VOID


def test_arrays_are_hoisted_allocas_zeroed_at_declaration() -> None:
    module = lower_source("fn main() { for i in 0..3 { let a: [float; 4]; a[i] = 1.0; } }")
    fn = module.functions["main"]
    entry_allocas = [inst for inst in fn.entry.instructions if isinstance(inst, AllocaInst)]
    assert len(entry_allocas) == 1 and entry_allocas[0].count == 4
    memzeros = [inst for inst in fn.instructions() if isinstance(inst, MemZeroInst)]
    assert len(memzeros) == 1 and memzeros[0].block is not fn.entry  # inside the loop body


def test_array_literal_stores_every_element_without_memzero() -> None:
    opcodes = ops("fn main() { let a = [[1, 2], [3, 4]]; print(a[1][0]); }")
    assert opcodes.count(Opcode.STORE) == 4
    assert Opcode.MEMZERO not in opcodes


def test_multidimensional_indexing_is_flattened_and_bounds_checked() -> None:
    module = lower_source(
        "fn main() { let m: [[int; 5]; 3]; let i = 1; let j = 2; print(m[i][j]); }"
    )
    fn = module.functions["main"]
    checks = [inst for inst in fn.instructions() if isinstance(inst, BoundsCheckInst)]
    assert [c.length for c in checks] == [3, 5]  # outer dimension first
    (load,) = [inst for inst in fn.instructions() if isinstance(inst, LoadInst)]
    muls = [inst for inst in fn.instructions() if inst.opcode is Opcode.MUL]
    assert len(muls) == 1 and muls[0].operands[1] == Constant(IRType.I64, 5)  # i * 5
    assert load.operands[1].type is IRType.I64


def test_row_argument_uses_ptradd() -> None:
    module = lower_source(
        "fn f(r: [int; 4]) {}\nfn main() { let m: [[int; 4]; 2]; let i = 1; f(m[i]); f(m[0]); }"
    )
    insts = list(module.functions["main"].instructions())
    ptradds = [inst for inst in insts if isinstance(inst, PtrAddInst)]
    # Lowering is deliberately naive: even m[0] computes `mul 0, 4` and a ptradd.
    # Constant folding (Phase 4) is responsible for cleaning this up.
    assert len(ptradds) == 2
    assert any(
        inst.opcode is Opcode.MUL and inst.operands[0] == Constant(IRType.I64, 0) for inst in insts
    )


def test_short_circuit_becomes_control_flow() -> None:
    module = lower_source("fn main() { let a = true; let b = false; print(a && b); }")
    labels = [b.label for b in module.functions["main"].blocks]
    assert "and.rhs" in labels and "and.end" in labels


def test_dead_code_after_return_is_removed() -> None:
    module = lower_source("fn f() -> int { return 1; print(2); return 3; }\nfn main() {}")
    fn = module.functions["f"]
    assert len(fn.blocks) == 1
    assert [inst.opcode for inst in fn.blocks[0].instructions] == [Opcode.RET]


def test_infinite_loop_function_ends_without_fallthrough() -> None:
    module = build_ir("fn f() -> int { while true { return 1; } }\nfn main() {}")
    fn = module.functions["f"]
    # The block after the loop is unreachable and gets removed; every block still terminates.
    assert all(block.terminator is not None for block in fn.blocks)


def test_shadowed_variables_get_distinct_registers() -> None:
    module = lower_source("fn main() { let x = 1; { let x = 2.5; print(x); } print(x); }")
    copies = [
        inst for inst in module.functions["main"].instructions() if inst.opcode is Opcode.COPY
    ]
    dests = [inst.dest for inst in copies]
    assert dests[0] is not dests[1]
    assert {d.type for d in dests if d is not None} == {IRType.I64, IRType.F64}


def test_store_value_evaluated_after_target_index() -> None:
    module = lower_source(
        "fn f(x: int) -> int { return x; }\nfn main() { let a: [int; 3]; a[f(1)] = f(2); }"
    )
    order = [
        inst.opcode
        for inst in module.functions["main"].instructions()
        if inst.opcode in (Opcode.CALL, Opcode.BOUNDSCHECK, Opcode.STORE)
    ]
    assert order == [Opcode.CALL, Opcode.BOUNDSCHECK, Opcode.CALL, Opcode.STORE]
    assert any(isinstance(i, StoreInst) for i in module.functions["main"].instructions())

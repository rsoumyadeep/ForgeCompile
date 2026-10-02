"""Emit LLVM IR (textual) from ForgeCompile SSA IR.

The translation is nearly one-to-one, which is deliberate: every optimization
decision is made by ForgeCompile's passes, *before* this point, and this module
only changes notation. That keeps the split between "what ForgeCompile does"
and "what LLVM does" clean and measurable (docs/LLVM_BACKEND.md).

Mapping:

==================  ==============================================================
ForgeCompile        LLVM
==================  ==============================================================
i64 / f64 / i1/ptr  i64 / double / i1 / ptr (opaque pointers)
add sub mul         add / sub / mul (no ``nsw``: MiniLang ints wrap)
sdiv, srem          plain ``sdiv``/``srem`` when the divisor is a constant other than
                    0 and -1; otherwise ``@__fc_sdiv``/``@__fc_srem``. These helpers
                    check for zero and handle INT_MIN / -1, which is undefined
                    behaviour in LLVM but defined (wrap) in MiniLang.
fadd ... frem       fadd ... frem (``frem`` is C fmod)
neg / fneg / not    sub 0, x / fneg / xor x, true
icmp p / fcmp p     icmp s{lt,le,gt,ge}/eq/ne; fcmp o{eq,lt,le,gt,ge}, **une** for ne
sitofp / zext       sitofp / zext
fptosi              ``@llvm.fptosi.sat.i64.f64`` (saturating, NaN -> 0)
copy                no instruction: uses are forwarded to the source value
alloca T, n         alloca T, i64 n
load / store        getelementptr T + load / store
ptradd              getelementptr T
memzero             ``@llvm.memset.p0.i64``
boundscheck         call ``@__fc_boundscheck`` (unsigned compare, trap on failure)
print               call ``@fc_print_{i64,f64,bool}`` (C runtime)
phi / br / ret      phi / br / ret
==================  ==============================================================

The checking helpers are ``internal alwaysinline`` functions defined in the
same module. With LLVM optimization they inline into straight-line compare
and branch code; without it they stay calls. Either way, ForgeCompile basic
blocks map 1:1 to LLVM basic blocks, so phi predecessor labels stay valid.

Naming: registers become ``%v.<name>``, blocks ``b.<label>``, address temporaries
``%a.<n>``, and user functions ``@mini_<name>``. LLVM puts locals and labels in one
namespace, and user functions named ``abs``/``sqrt`` would collide with libc.
"""

from __future__ import annotations

import struct

from forgecompile.ir.function import Function, Module
from forgecompile.ir.instructions import (
    AllocaInst,
    BoundsCheckInst,
    BranchInst,
    CallInst,
    CmpPred,
    CompareInst,
    Instruction,
    JumpInst,
    MemZeroInst,
    Opcode,
    PhiInst,
    PtrAddInst,
)
from forgecompile.ir.values import Constant, IRType, Register, Undef, Value

LLVM_TYPES = {
    IRType.I64: "i64",
    IRType.F64: "double",
    IRType.I1: "i1",
    IRType.PTR: "ptr",
    IRType.VOID: "void",
}
BYTE_SIZES = {IRType.I64: 8, IRType.F64: 8, IRType.I1: 1}

_ARITH = {
    Opcode.ADD: "add",
    Opcode.SUB: "sub",
    Opcode.MUL: "mul",
    Opcode.FADD: "fadd",
    Opcode.FSUB: "fsub",
    Opcode.FMUL: "fmul",
    Opcode.FDIV: "fdiv",
    Opcode.FREM: "frem",
}
_ICMP = {
    CmpPred.EQ: "eq",
    CmpPred.NE: "ne",
    CmpPred.LT: "slt",
    CmpPred.LE: "sle",
    CmpPred.GT: "sgt",
    CmpPred.GE: "sge",
}
_FCMP = {
    CmpPred.EQ: "oeq",
    CmpPred.NE: "une",  # true for NaN, matching IEEE / Python / MiniLang
    CmpPred.LT: "olt",
    CmpPred.LE: "ole",
    CmpPred.GT: "ogt",
    CmpPred.GE: "oge",
}

PRELUDE = """\
; ---- ForgeCompile runtime interface (implemented in fc_runtime.c) ----
declare void @fc_runtime_init()
declare void @fc_print_i64(i64)
declare void @fc_print_f64(double)
declare void @fc_print_bool(i32)
declare void @fc_trap_division() noreturn
declare void @fc_trap_remainder() noreturn
declare void @fc_trap_bounds(i64, i64) noreturn
declare i64 @llvm.fptosi.sat.i64.f64(double)
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)

; ---- checked operations: MiniLang semantics that LLVM leaves undefined ----
define internal i64 @__fc_sdiv(i64 %a, i64 %b) alwaysinline {
entry:
  %zero = icmp eq i64 %b, 0
  br i1 %zero, label %trap, label %nonzero
trap:
  call void @fc_trap_division()
  unreachable
nonzero:
  %minus1 = icmp eq i64 %b, -1
  br i1 %minus1, label %negate, label %divide
negate:
  %n = sub i64 0, %a
  ret i64 %n
divide:
  %q = sdiv i64 %a, %b
  ret i64 %q
}

define internal i64 @__fc_srem(i64 %a, i64 %b) alwaysinline {
entry:
  %zero = icmp eq i64 %b, 0
  br i1 %zero, label %trap, label %nonzero
trap:
  call void @fc_trap_remainder()
  unreachable
nonzero:
  %minus1 = icmp eq i64 %b, -1
  br i1 %minus1, label %zero_result, label %remainder
zero_result:
  ret i64 0
remainder:
  %r = srem i64 %a, %b
  ret i64 %r
}

define internal void @__fc_boundscheck(i64 %i, i64 %n) alwaysinline {
entry:
  %ok = icmp ult i64 %i, %n
  br i1 %ok, label %fine, label %bad
bad:
  call void @fc_trap_bounds(i64 %i, i64 %n)
  unreachable
fine:
  ret void
}
"""


def llvm_float(value: float) -> str:
    """Exact LLVM spelling of a double: the IEEE-754 bit pattern in hex (handles NaN, inf, -0)."""
    bits = struct.unpack("<Q", struct.pack("<d", value))[0]
    return f"0x{bits:016X}"


class BackendError(Exception):
    """The backend could not translate or build the program (a compiler or toolchain bug)."""


class _FunctionEmitter:
    def __init__(self, fn: Function, module: Module) -> None:
        self.fn = fn
        self.module = module
        self.lines: list[str] = []
        self.copies: dict[Register, Value] = {
            inst.dest: inst.operands[0]
            for inst in fn.instructions()
            if inst.opcode is Opcode.COPY and inst.dest is not None
        }
        self._temp = 0

    # ------------------------------------------------------------------ values

    def value(self, v: Value) -> str:
        seen = 0
        while isinstance(v, Register) and v in self.copies:  # copy forwarding
            v = self.copies[v]
            seen += 1
            if seen > len(self.copies):
                raise BackendError(f"cyclic copies in @{self.fn.name}")
        if isinstance(v, Register):
            return f"%v.{v.name}"
        if isinstance(v, Undef):
            return "undef"
        assert isinstance(v, Constant)
        if v.type is IRType.I1:
            return "true" if v.value else "false"
        if v.type is IRType.F64:
            return llvm_float(float(v.value))
        return str(v.value)

    def typed(self, v: Value) -> str:
        return f"{LLVM_TYPES[v.type]} {self.value(v)}"

    def temp(self) -> str:
        self._temp += 1
        return f"%a.{self._temp}"

    def emit(self, text: str) -> None:
        self.lines.append(f"  {text}")

    # ------------------------------------------------------------------ functions

    def run(self) -> list[str]:
        fn = self.fn
        params = ", ".join(f"{LLVM_TYPES[p.type]} %v.{p.name}" for p in fn.params)
        self.lines.append(f"define {LLVM_TYPES[fn.return_type]} @mini_{fn.name}({params}) {{")
        for block in fn.blocks:
            self.lines.append(f"b.{block.label}:")
            for inst in block.instructions:
                self.instruction(inst)
        self.lines.append("}")
        return self.lines

    def instruction(self, inst: Instruction) -> None:
        op = inst.opcode
        ops = inst.operands
        if op is Opcode.COPY:
            return  # forwarded
        dest = f"%v.{inst.dest.name}" if inst.dest is not None else ""
        # Operand spellings, resolved once (after copy forwarding).
        a = self.value(ops[0]) if ops else ""
        b = self.value(ops[1]) if len(ops) > 1 else ""
        if op in _ARITH:
            self.emit(f"{dest} = {_ARITH[op]} {LLVM_TYPES[ops[0].type]} {a}, {b}")
        elif op in (Opcode.SDIV, Opcode.SREM):
            divisor = ops[1]
            if isinstance(divisor, Constant) and divisor.value not in (0, -1):
                name = "sdiv" if op is Opcode.SDIV else "srem"
                self.emit(f"{dest} = {name} i64 {a}, {b}")
            else:
                helper = "__fc_sdiv" if op is Opcode.SDIV else "__fc_srem"
                self.emit(f"{dest} = call i64 @{helper}(i64 {a}, i64 {b})")
        elif op is Opcode.NEG:
            self.emit(f"{dest} = sub i64 0, {a}")
        elif op is Opcode.FNEG:
            self.emit(f"{dest} = fneg double {a}")
        elif op is Opcode.NOT:
            self.emit(f"{dest} = xor i1 {a}, true")
        elif op is Opcode.SITOFP:
            self.emit(f"{dest} = sitofp i64 {a} to double")
        elif op is Opcode.FPTOSI:
            self.emit(f"{dest} = call i64 @llvm.fptosi.sat.i64.f64(double {a})")
        elif op is Opcode.ZEXT:
            self.emit(f"{dest} = zext i1 {a} to i64")
        elif isinstance(inst, CompareInst):
            if op is Opcode.FCMP:
                self.emit(f"{dest} = fcmp {_FCMP[inst.pred]} double {a}, {b}")
            else:
                self.emit(f"{dest} = icmp {_ICMP[inst.pred]} {LLVM_TYPES[ops[0].type]} {a}, {b}")
        elif isinstance(inst, AllocaInst):
            self.emit(f"{dest} = alloca {LLVM_TYPES[inst.elem_type]}, i64 {inst.count}")
        elif op is Opcode.LOAD:
            assert inst.dest is not None
            ty = LLVM_TYPES[inst.dest.type]
            address = self.temp()
            self.emit(f"{address} = getelementptr {ty}, ptr {a}, i64 {b}")
            self.emit(f"{dest} = load {ty}, ptr {address}")
        elif op is Opcode.STORE:
            ty = LLVM_TYPES[ops[2].type]
            address = self.temp()
            self.emit(f"{address} = getelementptr {ty}, ptr {a}, i64 {b}")
            self.emit(f"store {ty} {self.value(ops[2])}, ptr {address}")
        elif isinstance(inst, PtrAddInst):
            self.emit(f"{dest} = getelementptr {LLVM_TYPES[inst.elem_type]}, ptr {a}, i64 {b}")
        elif isinstance(inst, MemZeroInst):
            size = BYTE_SIZES[inst.elem_type] * inst.count
            self.emit(f"call void @llvm.memset.p0.i64(ptr {a}, i8 0, i64 {size}, i1 false)")
        elif isinstance(inst, BoundsCheckInst):
            self.emit(f"call void @__fc_boundscheck(i64 {a}, i64 {inst.length})")
        elif isinstance(inst, CallInst):
            callee = self.module.functions[inst.callee]
            args = ", ".join(self.typed(a) for a in ops)
            ret = LLVM_TYPES[callee.return_type]
            prefix = f"{dest} = " if inst.dest is not None else ""
            self.emit(f"{prefix}call {ret} @mini_{inst.callee}({args})")
        elif op is Opcode.PRINT:
            value = ops[0]
            if value.type is IRType.I1:
                widened = self.temp()
                self.emit(f"{widened} = zext i1 {self.value(value)} to i32")
                self.emit(f"call void @fc_print_bool(i32 {widened})")
            elif value.type is IRType.F64:
                self.emit(f"call void @fc_print_f64(double {self.value(value)})")
            else:
                self.emit(f"call void @fc_print_i64(i64 {self.value(value)})")
        elif isinstance(inst, PhiInst):
            assert inst.dest is not None
            incoming = ", ".join(f"[ {self.value(v)}, %b.{b.label} ]" for v, b in inst.incoming)
            self.emit(f"{dest} = phi {LLVM_TYPES[inst.dest.type]} {incoming}")
        elif isinstance(inst, JumpInst):
            self.emit(f"br label %b.{inst.target.label}")
        elif isinstance(inst, BranchInst):
            self.emit(
                f"br i1 {self.value(ops[0])}, label %b.{inst.true_target.label}, "
                f"label %b.{inst.false_target.label}"
            )
        elif op is Opcode.RET:
            self.emit(f"ret {self.typed(ops[0])}" if ops else "ret void")
        elif op is Opcode.UNREACHABLE:
            self.emit("unreachable")
        else:
            raise BackendError(f"no LLVM lowering for opcode {op.value}")


def _c_main(module: Module) -> str:
    """The C ``main`` wrapper: initialize the runtime, call ``mini_main``, return status % 256."""
    main = module.functions["main"]
    if main.return_type is IRType.VOID:
        body = "  call void @mini_main()\n  ret i32 0"
    else:
        body = (
            "  %r = call i64 @mini_main()\n"
            "  %low = and i64 %r, 255\n"  # same as Python's r % 256 for two's complement
            "  %status = trunc i64 %low to i32\n"
            "  ret i32 %status"
        )
    return f"define i32 @main() {{\nentry:\n  call void @fc_runtime_init()\n{body}\n}}"


def emit_module(module: Module, source_name: str = "forgecompile") -> str:
    """Translate an SSA module (with a ``main`` function) to LLVM IR text."""
    if "main" not in module.functions:
        raise BackendError("module has no main function")
    parts = [f'; ModuleID = "{source_name}"\nsource_filename = "{source_name}"', PRELUDE]
    for fn in module.functions.values():
        parts.append("\n".join(_FunctionEmitter(fn, module).run()))
    parts.append(_c_main(module))
    return "\n\n".join(parts) + "\n"


def verify_llvm(text: str) -> None:
    """Parse and verify LLVM IR with llvmlite; raises BackendError with LLVM's message."""
    import llvmlite.binding as llvm

    try:
        parsed = llvm.parse_assembly(text)
        parsed.verify()
    except RuntimeError as exc:
        raise BackendError(f"invalid LLVM IR: {exc}") from exc


def optimize_llvm(text: str, speed_level: int) -> str:
    """Run LLVM's own optimization pipeline (``-O<level>``) on LLVM IR text, via llvmlite.

    This is for *inspection and comparison only*: it shows what LLVM would do to
    ForgeCompile's output. ForgeCompile's own optimizations never depend on it.
    """
    import llvmlite.binding as llvm

    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    machine = llvm.Target.from_default_triple().create_target_machine()
    module = llvm.parse_assembly(text)
    builder = llvm.create_pass_builder(
        machine, llvm.create_pipeline_tuning_options(speed_level=speed_level)
    )
    builder.getModulePassManager().run(module, builder)
    return str(module)

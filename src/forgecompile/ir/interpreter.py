"""IR interpreter: reference execution of ForgeCompile IR, with instruction counting.

Roles:

1. **Correctness oracle.** It runs any IR, before or after SSA, before or
   after optimization. Differential tests compare its observable behaviour
   with the AST interpreter and, from Phase 5, with native executables.
2. **Deterministic cost signal** (DECISIONS D-006). It counts every executed
   instruction by opcode and computes a weighted cost. Unlike wall-clock time,
   this is identical on every run, which matters for ML/RL rewards.

Phi semantics: on a jump from block P to block B, every phi in B reads its
value for P *simultaneously* (parallel copy), and then execution starts at
B's first non-phi instruction.

The interpreter also checks invariants that valid IR must satisfy, and reports
violations as :class:`InterpreterError` (a compiler bug, *not* a MiniLang
runtime error):

* reading ``undef`` anywhere except as a phi input;
* reading a register that was never assigned;
* memory access outside an allocation (a removed or wrong bounds check);
* reaching ``unreachable``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from forgecompile.ir.function import BasicBlock, Function, Module
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
)
from forgecompile.ir.values import Constant, IRType, Register, Undef, Value
from forgecompile.runtime import semantics as sem
from forgecompile.runtime.semantics import RuntimeTrap

DEFAULT_MAX_STEPS = 200_000_000
MAX_CALL_DEPTH = 10_000

# Rough relative costs (approximate x86-64 latencies, in "simple-op" units).
# These are *assumptions*: Phase 6 measures how well this cost model predicts
# native runtime, and the result is reported whether good or bad.
DEFAULT_COST_MODEL: dict[Opcode, float] = {
    Opcode.ADD: 1, Opcode.SUB: 1, Opcode.NEG: 1, Opcode.MUL: 3,
    Opcode.SDIV: 25, Opcode.SREM: 25,
    Opcode.FADD: 4, Opcode.FSUB: 4, Opcode.FNEG: 1, Opcode.FMUL: 4,
    Opcode.FDIV: 15, Opcode.FREM: 30,
    Opcode.ICMP: 1, Opcode.FCMP: 3, Opcode.NOT: 1,
    Opcode.SITOFP: 4, Opcode.FPTOSI: 6, Opcode.ZEXT: 1, Opcode.COPY: 1,
    Opcode.ALLOCA: 1, Opcode.LOAD: 4, Opcode.STORE: 4, Opcode.PTRADD: 1,
    Opcode.MEMZERO: 1, Opcode.BOUNDSCHECK: 2,
    Opcode.CALL: 10, Opcode.PRINT: 50,
    Opcode.PHI: 0,
    Opcode.JUMP: 1, Opcode.BRANCH: 2, Opcode.RET: 5, Opcode.UNREACHABLE: 0,
}  # fmt: skip

_UNDEF = object()  # runtime marker for undef values


class InterpreterError(Exception):
    """The IR violated an invariant: a compiler bug, not a program error."""


class StepLimitExceeded(Exception):
    """The program executed more instructions than the step budget allows."""


@dataclass
class IRExecutionResult:
    stdout: str
    exit_code: int
    trap: str | None = None
    steps: int = 0
    opcode_counts: Counter[str] = field(default_factory=Counter)
    cost: float = 0.0

    @property
    def observable(self) -> tuple[str, int]:
        return self.stdout, self.exit_code


@dataclass
class _Frame:
    fn: Function
    regs: dict[Register, Any]
    block: BasicBlock
    index: int = 0
    result_dest: Register | None = None  # caller register that receives the return value


def _zero_of(ty: IRType) -> Any:
    return {IRType.I64: 0, IRType.F64: 0.0, IRType.I1: False}[ty]


def _compare(pred: CmpPred, a: Any, b: Any) -> bool:
    match pred:
        case CmpPred.EQ:
            return bool(a == b)
        case CmpPred.NE:
            return bool(a != b)
        case CmpPred.LT:
            return bool(a < b)
        case CmpPred.LE:
            return bool(a <= b)
        case CmpPred.GT:
            return bool(a > b)
        case CmpPred.GE:
            return bool(a >= b)


class IRInterpreter:
    def __init__(
        self,
        module: Module,
        max_steps: int = DEFAULT_MAX_STEPS,
        cost_model: dict[Opcode, float] | None = None,
    ) -> None:
        self.module = module
        self.max_steps = max_steps
        self.cost_model = cost_model if cost_model is not None else DEFAULT_COST_MODEL
        self.output: list[str] = []
        self.counts: Counter[Opcode] = Counter()
        self.steps = 0

    # ================================================================== public API

    def run(self, entry: str = "main") -> IRExecutionResult:
        fn = self.module.functions[entry]
        try:
            result = self._execute(fn, [])
            exit_code, trap = sem.exit_status(result), None
        except RuntimeTrap as error:
            exit_code, trap = sem.RUNTIME_ERROR_EXIT_CODE, str(error)
        counts = Counter({op.value: n for op, n in self.counts.items()})
        cost = sum(self.cost_model.get(op, 1.0) * n for op, n in self.counts.items())
        return IRExecutionResult("".join(self.output), exit_code, trap, self.steps, counts, cost)

    # ================================================================== execution loop

    def _read(self, frame: _Frame, value: Value) -> Any:
        if isinstance(value, Register):
            try:
                result = frame.regs[value]
            except KeyError:
                raise InterpreterError(
                    f"@{frame.fn.name}: register {value} read before assignment"
                ) from None
            if result is _UNDEF:
                raise InterpreterError(f"@{frame.fn.name}: observable use of undef via {value}")
            return result
        if isinstance(value, Constant):
            return value.value
        if isinstance(value, Undef):
            raise InterpreterError(f"@{frame.fn.name}: observable use of {value}")
        raise InterpreterError(f"unknown value {value!r}")

    def _enter_block(self, frame: _Frame, target: BasicBlock) -> None:
        """Transfer control along the edge frame.block -> target, executing phis in parallel."""
        source = frame.block
        phis = target.phis()
        if phis:
            incoming: list[Any] = []
            for phi in phis:
                value = phi.value_from(source)
                if isinstance(value, Undef):
                    incoming.append(_UNDEF)
                elif isinstance(value, Register):
                    incoming.append(frame.regs.get(value, _UNDEF))
                else:
                    incoming.append(self._read(frame, value))
            for phi, value in zip(phis, incoming, strict=True):
                assert phi.dest is not None
                frame.regs[phi.dest] = value
            self.counts[Opcode.PHI] += len(phis)
        frame.block = target
        frame.index = len(phis)

    def _execute(self, fn: Function, args: list[Any]) -> Any:
        frames = [_Frame(fn, dict(zip(fn.params, args, strict=True)), fn.entry)]
        frames[0].index = len(fn.entry.phis())
        while True:
            frame = frames[-1]
            inst = frame.block.instructions[frame.index]
            frame.index += 1
            self.steps += 1
            if self.steps > self.max_steps:
                raise StepLimitExceeded(f"exceeded {self.max_steps} IR instructions")
            op = inst.opcode
            self.counts[op] += 1

            if op is Opcode.JUMP:
                assert isinstance(inst, JumpInst)
                self._enter_block(frame, inst.target)
            elif op is Opcode.BRANCH:
                assert isinstance(inst, BranchInst)
                taken = inst.true_target if self._read(frame, inst.cond) else inst.false_target
                self._enter_block(frame, taken)
            elif op is Opcode.CALL:
                assert isinstance(inst, CallInst)
                callee = self.module.functions[inst.callee]
                values = [self._read(frame, a) for a in inst.operands]
                if len(frames) >= MAX_CALL_DEPTH:
                    raise InterpreterError(f"call depth exceeded {MAX_CALL_DEPTH}")
                new_frame = _Frame(
                    callee, dict(zip(callee.params, values, strict=True)), callee.entry
                )
                new_frame.index = len(callee.entry.phis())
                new_frame.result_dest = inst.dest
                frames.append(new_frame)
            elif op is Opcode.RET:
                result = self._read(frame, inst.operands[0]) if inst.operands else None
                frames.pop()
                if not frames:
                    return result
                if frame.result_dest is not None:
                    frames[-1].regs[frame.result_dest] = result
            elif op is Opcode.UNREACHABLE:
                raise InterpreterError(f"@{frame.fn.name}: reached 'unreachable'")
            elif op is Opcode.PHI:
                raise InterpreterError(
                    f"@{frame.fn.name}: phi after non-phi in {frame.block.label}"
                )
            else:
                self._simple(frame, inst)

    # ================================================================== straight-line instructions

    def _simple(self, frame: _Frame, inst: Instruction) -> None:
        op = inst.opcode
        read = self._read
        ops = inst.operands
        result: Any
        if op is Opcode.ADD:
            result = sem.wrap(read(frame, ops[0]) + read(frame, ops[1]))
        elif op is Opcode.SUB:
            result = sem.wrap(read(frame, ops[0]) - read(frame, ops[1]))
        elif op is Opcode.MUL:
            result = sem.wrap(read(frame, ops[0]) * read(frame, ops[1]))
        elif op is Opcode.SDIV:
            result = sem.int_div(read(frame, ops[0]), read(frame, ops[1]))
        elif op is Opcode.SREM:
            result = sem.int_rem(read(frame, ops[0]), read(frame, ops[1]))
        elif op is Opcode.NEG:
            result = sem.wrap(-read(frame, ops[0]))
        elif op is Opcode.FADD:
            result = read(frame, ops[0]) + read(frame, ops[1])
        elif op is Opcode.FSUB:
            result = read(frame, ops[0]) - read(frame, ops[1])
        elif op is Opcode.FMUL:
            result = read(frame, ops[0]) * read(frame, ops[1])
        elif op is Opcode.FDIV:
            result = sem.float_div(read(frame, ops[0]), read(frame, ops[1]))
        elif op is Opcode.FREM:
            result = sem.float_rem(read(frame, ops[0]), read(frame, ops[1]))
        elif op is Opcode.FNEG:
            result = -read(frame, ops[0])
        elif op is Opcode.ICMP or op is Opcode.FCMP:
            assert isinstance(inst, CompareInst)
            result = _compare(inst.pred, read(frame, ops[0]), read(frame, ops[1]))
        elif op is Opcode.NOT:
            result = not read(frame, ops[0])
        elif op is Opcode.SITOFP:
            result = float(read(frame, ops[0]))
        elif op is Opcode.FPTOSI:
            result = sem.float_to_int(read(frame, ops[0]))
        elif op is Opcode.ZEXT:
            result = int(read(frame, ops[0]))
        elif op is Opcode.COPY:
            result = read(frame, ops[0])
        elif op is Opcode.ALLOCA:
            assert isinstance(inst, AllocaInst)
            result = ([_zero_of(inst.elem_type)] * inst.count, 0)
        elif op is Opcode.LOAD:
            buffer, base = read(frame, ops[0])
            position = base + read(frame, ops[1])
            self._check_access(frame, buffer, position)
            result = buffer[position]
        elif op is Opcode.STORE:
            buffer, base = read(frame, ops[0])
            position = base + read(frame, ops[1])
            self._check_access(frame, buffer, position)
            buffer[position] = read(frame, ops[2])
            return
        elif op is Opcode.PTRADD:
            buffer, base = read(frame, ops[0])
            result = (buffer, base + read(frame, ops[1]))
        elif op is Opcode.MEMZERO:
            assert isinstance(inst, MemZeroInst)
            buffer, base = read(frame, ops[0])
            self._check_access(frame, buffer, base)
            self._check_access(frame, buffer, base + inst.count - 1)
            buffer[base : base + inst.count] = [_zero_of(inst.elem_type)] * inst.count
            return
        elif op is Opcode.BOUNDSCHECK:
            assert isinstance(inst, BoundsCheckInst)
            index = read(frame, ops[0])
            if not 0 <= index < inst.length:
                raise RuntimeTrap(f"index {index} out of bounds for array of length {inst.length}")
            return
        elif op is Opcode.PRINT:
            self.output.append(sem.format_value(read(frame, ops[0])) + "\n")
            return
        else:
            raise InterpreterError(f"unhandled opcode {op.value}")
        assert inst.dest is not None
        frame.regs[inst.dest] = result

    @staticmethod
    def _check_access(frame: _Frame, buffer: list[Any], position: int) -> None:
        # Python would silently accept negative indices; IR memory must not.
        if not 0 <= position < len(buffer):
            raise InterpreterError(
                f"@{frame.fn.name}: memory access at {position} outside buffer of {len(buffer)}"
            )


def run_module(module: Module, max_steps: int = DEFAULT_MAX_STEPS) -> IRExecutionResult:
    return IRInterpreter(module, max_steps).run()

"""IR verifier: well-formedness checks run after lowering, SSA construction and every pass.

A verifier turns subtle miscompilations into immediate, located errors. A pass
that leaves a phi out of sync with its block's predecessors would otherwise
show up much later as a wrong program output, far from the cause.

Checks (all modes):
  * every block is non-empty and ends in exactly one terminator; phis come first;
  * the entry block has no predecessors and no phis;
  * branch targets belong to the function;
  * phi incoming blocks are exactly the block's predecessors, each listed once;
  * operand and result types match the opcode; calls match the callee signature;
    ``ret`` matches the function's return type.

Additional checks in SSA mode (``ssa=True``):
  * every register has exactly one definition (parameters count as defined);
  * every used register is defined;
  * **dominance property**: each definition dominates each of its uses. A phi
    operand counts as a use at the *end of the corresponding predecessor*.
"""

from __future__ import annotations

from collections import Counter

from forgecompile.analysis.cfg import predecessors, reachable_blocks
from forgecompile.analysis.dominators import DominatorTree
from forgecompile.ir.function import BasicBlock, Function, Module
from forgecompile.ir.instructions import (
    FLOAT_BINARY,
    INT_BINARY,
    UNARY_SIGNATURES,
    AllocaInst,
    BoundsCheckInst,
    CallInst,
    CmpPred,
    CompareInst,
    Instruction,
    LoadInst,
    MemZeroInst,
    Opcode,
    PhiInst,
    Terminator,
)
from forgecompile.ir.values import IRType, Register, Value

SCALAR_TYPES = (IRType.I64, IRType.F64, IRType.I1)


class IRVerificationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("IR verification failed:\n  " + "\n  ".join(errors))


class _FunctionVerifier:
    def __init__(self, fn: Function, module: Module | None, ssa: bool) -> None:
        self.fn = fn
        self.module = module
        self.ssa = ssa
        self.errors: list[str] = []

    def error(self, where: BasicBlock | None, message: str) -> None:
        location = f"@{self.fn.name}" + (f":{where.label}" if where is not None else "")
        self.errors.append(f"{location}: {message}")

    # ------------------------------------------------------------------ driver

    def run(self) -> list[str]:
        fn = self.fn
        if not fn.blocks:
            self.error(None, "function has no blocks")
            return self.errors
        labels = Counter(block.label for block in fn.blocks)
        for label, count in labels.items():
            if count > 1:
                self.error(None, f"duplicate block label '{label}'")
        block_set = set(fn.blocks)
        for block in fn.blocks:
            self._check_structure(block, block_set)
        if self.errors:  # CFG queries below assume well-formed terminators
            return self.errors
        preds = predecessors(fn)
        if preds[fn.entry]:
            self.error(fn.entry, "entry block must not have predecessors")
        for block in fn.blocks:
            self._check_phis(block, preds[block])
            for inst in block.instructions:
                self._check_types(block, inst)
        if self.ssa and not self.errors:
            self._check_ssa()
        return self.errors

    # ------------------------------------------------------------------ structure

    def _check_structure(self, block: BasicBlock, block_set: set[BasicBlock]) -> None:
        if not block.instructions:
            self.error(block, "empty block")
            return
        seen_non_phi = False
        for i, inst in enumerate(block.instructions):
            is_last = i == len(block.instructions) - 1
            if inst.block is not block:
                self.error(block, f"instruction '{inst!r}' has a stale block pointer")
            if isinstance(inst, PhiInst):
                if seen_non_phi:
                    self.error(block, "phi after a non-phi instruction")
            else:
                seen_non_phi = True
            if inst.is_terminator and not is_last:
                self.error(block, f"terminator '{inst.opcode.value}' in the middle of the block")
            if is_last and not inst.is_terminator:
                self.error(block, "block does not end in a terminator")
            if isinstance(inst, Terminator):
                for target in inst.targets:
                    if target not in block_set:
                        self.error(block, f"branch to block '{target.label}' outside the function")

    def _check_phis(self, block: BasicBlock, preds: list[BasicBlock]) -> None:
        phis = block.phis()
        if phis and block is self.fn.entry:
            self.error(block, "entry block must not contain phis")
        for phi in phis:
            if Counter(phi.blocks) != Counter(preds):
                got = sorted(b.label for b in phi.blocks)
                want = sorted(b.label for b in preds)
                self.error(block, f"phi {phi.dest}: incoming blocks {got} != predecessors {want}")

    # ------------------------------------------------------------------ types

    def _expect(
        self, block: BasicBlock, inst: Instruction, value: Value, ty: IRType, what: str
    ) -> None:
        if value.type is not ty:
            self.error(block, f"'{inst!r}': {what} has type {value.type}, expected {ty}")

    def _check_types(self, block: BasicBlock, inst: Instruction) -> None:
        op = inst.opcode
        ops = inst.operands
        dest = inst.dest
        e = self._expect
        if op in INT_BINARY or op in FLOAT_BINARY:
            ty = IRType.I64 if op in INT_BINARY else IRType.F64
            e(block, inst, ops[0], ty, "left operand")
            e(block, inst, ops[1], ty, "right operand")
            assert dest is not None
            e(block, inst, dest, ty, "result")
        elif op in UNARY_SIGNATURES:
            operand_ty, result_ty = UNARY_SIGNATURES[op]
            assert dest is not None
            if operand_ty is None:  # copy
                e(block, inst, dest, ops[0].type, "copy result")
            else:
                assert result_ty is not None
                e(block, inst, ops[0], operand_ty, "operand")
                e(block, inst, dest, result_ty, "result")
        elif isinstance(inst, CompareInst):
            assert dest is not None
            e(block, inst, dest, IRType.I1, "result")
            if op is Opcode.FCMP:
                e(block, inst, ops[0], IRType.F64, "left operand")
                e(block, inst, ops[1], IRType.F64, "right operand")
            else:
                if ops[0].type not in (IRType.I64, IRType.I1) or ops[0].type is not ops[1].type:
                    self.error(block, f"'{inst!r}': icmp operands must both be i64 or both i1")
                if ops[0].type is IRType.I1 and inst.pred not in (CmpPred.EQ, CmpPred.NE):
                    self.error(block, f"'{inst!r}': ordering comparison on i1")
        elif isinstance(inst, AllocaInst):
            assert dest is not None
            e(block, inst, dest, IRType.PTR, "result")
            if inst.elem_type not in SCALAR_TYPES or inst.count < 1:
                self.error(block, f"'{inst!r}': bad alloca element type or count")
        elif isinstance(inst, LoadInst):
            e(block, inst, ops[0], IRType.PTR, "pointer")
            e(block, inst, ops[1], IRType.I64, "index")
            assert dest is not None
            if dest.type not in SCALAR_TYPES:
                self.error(block, f"'{inst!r}': load of non-scalar type {dest.type}")
        elif op is Opcode.STORE:
            e(block, inst, ops[0], IRType.PTR, "pointer")
            e(block, inst, ops[1], IRType.I64, "index")
            if ops[2].type not in SCALAR_TYPES:
                self.error(block, f"'{inst!r}': store of non-scalar type {ops[2].type}")
        elif op is Opcode.PTRADD:
            e(block, inst, ops[0], IRType.PTR, "pointer")
            e(block, inst, ops[1], IRType.I64, "offset")
            assert dest is not None
            e(block, inst, dest, IRType.PTR, "result")
        elif isinstance(inst, MemZeroInst):
            e(block, inst, ops[0], IRType.PTR, "pointer")
        elif isinstance(inst, BoundsCheckInst):
            e(block, inst, ops[0], IRType.I64, "index")
        elif isinstance(inst, CallInst):
            self._check_call(block, inst)
        elif op is Opcode.PRINT:
            if ops[0].type not in SCALAR_TYPES:
                self.error(block, f"'{inst!r}': print of non-scalar type {ops[0].type}")
        elif isinstance(inst, PhiInst):
            assert dest is not None
            for value in ops:
                e(block, inst, value, dest.type, "phi input")
        elif op is Opcode.BRANCH:
            e(block, inst, ops[0], IRType.I1, "branch condition")
        elif op is Opcode.RET:
            if self.fn.return_type is IRType.VOID:
                if ops:
                    self.error(block, "'ret' with a value in a void function")
            elif not ops:
                self.error(
                    block, f"'ret' without a value in a function returning {self.fn.return_type}"
                )
            else:
                e(block, inst, ops[0], self.fn.return_type, "return value")

    def _check_call(self, block: BasicBlock, inst: CallInst) -> None:
        if self.module is None:
            return
        callee = self.module.functions.get(inst.callee)
        if callee is None:
            self.error(block, f"call to undefined function @{inst.callee}")
            return
        if len(inst.operands) != len(callee.params):
            self.error(block, f"'{inst!r}': wrong number of arguments")
            return
        for arg, param in zip(inst.operands, callee.params, strict=True):
            self._expect(block, inst, arg, param.type, f"argument for {param}")
        if callee.return_type is IRType.VOID:
            if inst.dest is not None:
                self.error(block, f"'{inst!r}': void call cannot define a register")
        elif inst.dest is None or inst.dest.type is not callee.return_type:
            self.error(block, f"'{inst!r}': result must have type {callee.return_type}")

    # ------------------------------------------------------------------ SSA

    def _check_ssa(self) -> None:
        fn = self.fn
        def_site: dict[Register, tuple[BasicBlock, int]] = {}
        for param in fn.params:
            def_site[param] = (fn.entry, -1)
        for block in fn.blocks:
            for index, inst in enumerate(block.instructions):
                if inst.dest is None:
                    continue
                if inst.dest in def_site:
                    self.error(block, f"register {inst.dest} is defined more than once")
                def_site[inst.dest] = (block, index)
        if self.errors:
            return
        reachable = reachable_blocks(fn)
        domtree = DominatorTree(fn)
        for block in fn.blocks:
            if block not in reachable:
                continue  # dominance is undefined for unreachable code
            for index, inst in enumerate(block.instructions):
                if isinstance(inst, PhiInst):
                    for value, pred in inst.incoming:
                        if isinstance(value, Register):
                            self._check_dominates(def_site, value, pred, None, domtree, block)
                else:
                    for reg in inst.registers_used():
                        self._check_dominates(def_site, reg, block, index, domtree, block)

    def _check_dominates(
        self,
        def_site: dict[Register, tuple[BasicBlock, int]],
        reg: Register,
        use_block: BasicBlock,
        use_index: int | None,  # None: use at the end of use_block (phi input)
        domtree: DominatorTree,
        report_block: BasicBlock,
    ) -> None:
        site = def_site.get(reg)
        if site is None:
            self.error(report_block, f"use of undefined register {reg}")
            return
        def_block, def_index = site
        if def_block is use_block:
            if use_index is not None and def_index >= use_index:
                self.error(report_block, f"register {reg} used before its definition")
        elif not domtree.dominates(def_block, use_block):
            self.error(report_block, f"definition of {reg} does not dominate its use")


def verify_function(fn: Function, module: Module | None = None, ssa: bool = False) -> list[str]:
    return _FunctionVerifier(fn, module, ssa).run()


def verify_module(module: Module, ssa: bool = False) -> None:
    """Raise :class:`IRVerificationError` listing every problem in the module."""
    errors: list[str] = []
    for fn in module.functions.values():
        errors.extend(verify_function(fn, module, ssa))
    if errors:
        raise IRVerificationError(errors)

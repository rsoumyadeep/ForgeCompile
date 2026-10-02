"""Lowering: type-checked AST -> ForgeCompile IR (pre-SSA).

The lowering is deliberately naive. It produces correct, simple IR and leaves
every improvement to the optimizer:

* **Scalar variables** become virtual registers, one per ``VariableSymbol``.
  Every assignment is a ``copy`` into the variable's register. A register may
  therefore be assigned many times; SSA construction (``ir/ssa.py``) renames
  them afterwards.
* **Arrays** become ``alloca`` buffers placed in the entry block, so a loop
  that declares an array does not grow the stack. They are zeroed by
  ``memzero`` *at the declaration site*, because a declaration inside a loop
  must re-zero its array on every iteration (LANGUAGE.md §7). Multi-dimensional
  arrays are flattened: ``m[i][j]`` on ``[[T; C]; R]`` becomes
  ``boundscheck i, R; boundscheck j, C; load m[i*C + j]``.
* **Short-circuit** ``&&``/``||`` become control flow plus a result register
  assigned on both paths.
* **Control flow** becomes basic blocks (``if.then``, ``while.cond``,
  ``for.latch``, ...). Statements after ``return``/``break``/``continue`` go
  into a fresh block with no predecessors. All such unreachable blocks are
  deleted at the end.

Evaluation order follows LANGUAGE.md §7 exactly (left to right; the target's
indices before the right-hand side). The reference AST interpreter follows the
same order, and the differential tests compare the two.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forgecompile.analysis.cfg import remove_unreachable_blocks
from forgecompile.ast import nodes as ast
from forgecompile.ast.operators import BinaryOp, UnaryOp
from forgecompile.ast.types import BOOL, FLOAT, INT, VOID, ArrayType, Type
from forgecompile.ir.function import BasicBlock, Function, Module
from forgecompile.ir.instructions import (
    AllocaInst,
    BinaryInst,
    BoundsCheckInst,
    BranchInst,
    CallInst,
    CmpPred,
    CompareInst,
    Instruction,
    JumpInst,
    LoadInst,
    MemZeroInst,
    Opcode,
    PrintInst,
    PtrAddInst,
    ReturnInst,
    StoreInst,
    UnaryInst,
    UnreachableInst,
)
from forgecompile.ir.values import (
    Constant,
    IRType,
    Register,
    Value,
    const_bool,
    const_float,
    const_int,
)

if TYPE_CHECKING:  # driver imports this module, so only import it for annotations
    from forgecompile.driver import CheckedProgram

_SCALAR_IR_TYPES: dict[Type, IRType] = {INT: IRType.I64, FLOAT: IRType.F64, BOOL: IRType.I1}

_INT_OPS = {
    BinaryOp.ADD: Opcode.ADD,
    BinaryOp.SUB: Opcode.SUB,
    BinaryOp.MUL: Opcode.MUL,
    BinaryOp.DIV: Opcode.SDIV,
    BinaryOp.MOD: Opcode.SREM,
}
_FLOAT_OPS = {
    BinaryOp.ADD: Opcode.FADD,
    BinaryOp.SUB: Opcode.FSUB,
    BinaryOp.MUL: Opcode.FMUL,
    BinaryOp.DIV: Opcode.FDIV,
    BinaryOp.MOD: Opcode.FREM,
}
_PREDICATES = {
    BinaryOp.EQ: CmpPred.EQ,
    BinaryOp.NE: CmpPred.NE,
    BinaryOp.LT: CmpPred.LT,
    BinaryOp.LE: CmpPred.LE,
    BinaryOp.GT: CmpPred.GT,
    BinaryOp.GE: CmpPred.GE,
}


def ir_type(ty: Type) -> IRType:
    if isinstance(ty, ArrayType):
        return IRType.PTR
    if ty == VOID:
        return IRType.VOID
    return _SCALAR_IR_TYPES[ty]


def _zero(ty: IRType) -> Constant:
    return Constant(ty, 0)


def _scalar_of(ty: Type) -> Type:
    return ty.scalar_element if isinstance(ty, ArrayType) else ty


class FunctionLowering:
    def __init__(self, decl: ast.FunctionDecl) -> None:
        assert decl.symbol is not None, "lowering requires a type-checked AST"
        self.decl = decl
        params: list[Register] = []
        self.vars: dict[int, Register] = {}  # scalar variable uid -> register
        self.arrays: dict[int, tuple[Value, ArrayType]] = {}  # array variable uid -> (ptr, type)
        for param in decl.params:
            assert param.symbol is not None
            reg = Register(param.name, ir_type(param.type))
            params.append(reg)
            if isinstance(param.type, ArrayType):
                self.arrays[param.symbol.uid] = (reg, param.type)
            else:
                self.vars[param.symbol.uid] = reg
        self.fn = Function(decl.name, params, ir_type(decl.return_type))
        self.entry = self.fn.new_block("entry")
        self.block = self.entry
        self._alloca_count = 0
        self._loops: list[tuple[BasicBlock, BasicBlock]] = []  # (continue target, break target)

    # ================================================================== emission helpers

    def emit(self, inst: Instruction) -> Instruction:
        return self.block.append(inst)

    def emit_value(self, inst: Instruction) -> Register:
        self.emit(inst)
        assert inst.dest is not None
        return inst.dest

    def start_block(self, block: BasicBlock) -> None:
        self.block = block

    def terminated(self) -> bool:
        return self.block.terminator is not None

    def jump(self, target: BasicBlock) -> None:
        if not self.terminated():
            self.emit(JumpInst(target))

    def start_dead_block(self) -> None:
        """Code after return/break/continue: a block with no predecessors (removed later)."""
        self.start_block(self.fn.new_block("dead"))

    def binary(self, opcode: Opcode, lhs: Value, rhs: Value) -> Register:
        dest = self.fn.new_temp(lhs.type)
        return self.emit_value(BinaryInst(opcode, dest, lhs, rhs))

    def unary(self, opcode: Opcode, operand: Value, result: IRType) -> Register:
        return self.emit_value(UnaryInst(opcode, self.fn.new_temp(result), operand))

    def compare(self, pred: CmpPred, lhs: Value, rhs: Value) -> Register:
        opcode = Opcode.FCMP if lhs.type is IRType.F64 else Opcode.ICMP
        return self.emit_value(CompareInst(opcode, pred, self.fn.new_temp(IRType.I1), lhs, rhs))

    def copy_into(self, dest: Register, value: Value) -> None:
        self.emit(UnaryInst(Opcode.COPY, dest, value))

    # ================================================================== functions

    def lower(self) -> Function:
        for stmt in self.decl.body.statements:
            self.stmt(stmt)
        if not self.terminated():
            if self.fn.return_type is IRType.VOID:
                self.emit(ReturnInst(None))
            else:
                # Semantic analysis proved this point unreachable (missing-return check).
                self.emit(UnreachableInst())
        remove_unreachable_blocks(self.fn)
        return self.fn

    # ================================================================== statements

    def stmt(self, stmt: ast.Stmt) -> None:
        match stmt:
            case ast.Block(statements=statements):
                for s in statements:
                    self.stmt(s)
            case ast.LetStmt():
                self.let(stmt)
            case ast.AssignStmt():
                self.assign(stmt)
            case ast.IfStmt():
                self.if_stmt(stmt)
            case ast.WhileStmt():
                self.while_stmt(stmt)
            case ast.ForStmt():
                self.for_stmt(stmt)
            case ast.ReturnStmt(value=value):
                self.emit(ReturnInst(None if value is None else self.expr(value)))
                self.start_dead_block()
            case ast.BreakStmt():
                self.jump(self._loops[-1][1])
                self.start_dead_block()
            case ast.ContinueStmt():
                self.jump(self._loops[-1][0])
                self.start_dead_block()
            case ast.ExprStmt(expr=expr):
                self.expr(expr)
            case _:
                raise TypeError(f"unknown statement {type(stmt).__name__}")

    def let(self, stmt: ast.LetStmt) -> None:
        symbol = stmt.symbol
        assert symbol is not None
        if isinstance(symbol.type, ArrayType):
            self.let_array(stmt, symbol.type, symbol.uid)
            return
        value = self.expr(stmt.init) if stmt.init is not None else _zero(ir_type(symbol.type))
        reg = self.fn.new_register(stmt.name, ir_type(symbol.type))
        self.vars[symbol.uid] = reg
        self.copy_into(reg, value)

    def let_array(self, stmt: ast.LetStmt, ty: ArrayType, uid: int) -> None:
        elem = ir_type(ty.scalar_element)
        ptr = self.fn.new_register(stmt.name, IRType.PTR)
        # Allocas go to the top of the entry block, in declaration order.
        self.entry.insert(self._alloca_count, AllocaInst(ptr, elem, ty.total_elements))
        self._alloca_count += 1
        self.arrays[uid] = (ptr, ty)
        if isinstance(stmt.init, ast.ArrayLiteral):
            # A literal initializes every element, so no memzero is needed.
            scalars: list[ast.Expr] = []
            _flatten_literal(stmt.init, scalars)
            for offset, element in enumerate(scalars):
                value = self.expr(element)
                self.emit(StoreInst(ptr, const_int(offset), value))
        else:
            self.emit(MemZeroInst(ptr, elem, ty.total_elements))

    def assign(self, stmt: ast.AssignStmt) -> None:
        target = stmt.target
        if isinstance(target, ast.Name):
            assert target.symbol is not None
            value = self.expr(stmt.value)
            self.copy_into(self.vars[target.symbol.uid], value)
            return
        assert isinstance(target, ast.Index)
        ptr, offset, _ = self.address(target)  # indices first (LANGUAGE.md §7)
        value = self.expr(stmt.value)
        self.emit(StoreInst(ptr, offset, value))

    def if_stmt(self, stmt: ast.IfStmt) -> None:
        cond = self.expr(stmt.condition)
        then_block = self.fn.new_block("if.then")
        merge = self.fn.new_block("if.end")
        else_block = self.fn.new_block("if.else") if stmt.else_body is not None else merge
        self.emit(BranchInst(cond, then_block, else_block))

        self.start_block(then_block)
        self.stmt(stmt.then_body)
        self.jump(merge)
        if stmt.else_body is not None:
            self.start_block(else_block)
            self.stmt(stmt.else_body)
            self.jump(merge)
        # Keep block order readable: the merge block comes after the branches.
        self.fn.blocks.remove(merge)
        self.fn.blocks.append(merge)
        self.start_block(merge)

    def while_stmt(self, stmt: ast.WhileStmt) -> None:
        header = self.fn.new_block("while.cond")
        body = self.fn.new_block("while.body")
        exit_block = self.fn.new_block("while.end")
        self.jump(header)
        self.start_block(header)
        cond = self.expr(stmt.condition)
        self.emit(BranchInst(cond, body, exit_block))

        self.start_block(body)
        self._loops.append((header, exit_block))
        self.stmt(stmt.body)
        self._loops.pop()
        self.jump(header)
        self.fn.blocks.remove(exit_block)
        self.fn.blocks.append(exit_block)
        self.start_block(exit_block)

    def for_stmt(self, stmt: ast.ForStmt) -> None:
        """``for i in a..b {B}`` becomes::

        i = copy a; end = b
        for.cond:  c = icmp lt i, end; br c, for.body, for.end
        for.body:  B; jump for.latch
        for.latch: i = add i, 1; jump for.cond      (`continue` jumps here)
        for.end:                                     (`break` jumps here)
        """
        symbol = stmt.symbol
        assert symbol is not None
        start = self.expr(stmt.start)
        end = self.expr(stmt.end)  # evaluated once, before the first iteration
        var = self.fn.new_register(stmt.var, IRType.I64)
        self.vars[symbol.uid] = var
        self.copy_into(var, start)

        header = self.fn.new_block("for.cond")
        body = self.fn.new_block("for.body")
        latch = self.fn.new_block("for.latch")
        exit_block = self.fn.new_block("for.end")
        self.jump(header)
        self.start_block(header)
        self.emit(BranchInst(self.compare(CmpPred.LT, var, end), body, exit_block))

        self.start_block(body)
        self._loops.append((latch, exit_block))
        self.stmt(stmt.body)
        self._loops.pop()
        self.jump(latch)

        self.start_block(latch)
        self.copy_into(var, self.binary(Opcode.ADD, var, const_int(1)))
        self.jump(header)
        for block in (latch, exit_block):  # order: cond, body..., latch, end
            self.fn.blocks.remove(block)
            self.fn.blocks.append(block)
        self.start_block(exit_block)

    # ================================================================== expressions

    def expr(self, expr: ast.Expr) -> Value:
        match expr:
            case ast.IntLiteral(value=v):
                return const_int(v)
            case ast.FloatLiteral(value=v):
                return const_float(v)
            case ast.BoolLiteral(value=v):
                return const_bool(v)
            case ast.Name(symbol=symbol):
                assert symbol is not None
                if symbol.uid in self.arrays:
                    return self.arrays[symbol.uid][0]
                return self.vars[symbol.uid]
            case ast.Unary(op=op, operand=operand):
                value = self.expr(operand)
                if op is UnaryOp.NOT:
                    return self.unary(Opcode.NOT, value, IRType.I1)
                opcode = Opcode.FNEG if value.type is IRType.F64 else Opcode.NEG
                return self.unary(opcode, value, value.type)
            case ast.Binary():
                return self.binary_expr(expr)
            case ast.Cast(expr=inner, target=target):
                return self.cast(self.expr(inner), ir_type(target))
            case ast.Index():
                ptr, offset, ty = self.address(expr)
                if isinstance(ty, ArrayType):  # a row, passed by reference
                    if isinstance(offset, Constant) and offset.value == 0:
                        return ptr
                    elem = ir_type(_scalar_of(ty))
                    dest = self.fn.new_temp(IRType.PTR)
                    return self.emit_value(PtrAddInst(dest, ptr, offset, elem))
                return self.emit_value(LoadInst(self.fn.new_temp(ir_type(ty)), ptr, offset))
            case ast.Call():
                return self.call(expr)
            case ast.ArrayLiteral():
                raise AssertionError("array literals are lowered by let_array")
        raise TypeError(f"unknown expression {type(expr).__name__}")

    def binary_expr(self, expr: ast.Binary) -> Value:
        op = expr.op
        if op.is_logical:
            return self.short_circuit(expr)
        lhs = self.expr(expr.left)
        rhs = self.expr(expr.right)
        if op.is_arithmetic:
            table = _FLOAT_OPS if lhs.type is IRType.F64 else _INT_OPS
            return self.binary(table[op], lhs, rhs)
        return self.compare(_PREDICATES[op], lhs, rhs)

    def short_circuit(self, expr: ast.Binary) -> Value:
        """``a && b``: result = a; if a { result = b }.  ``a || b``: if !a { result = b }."""
        is_and = expr.op is BinaryOp.AND
        result = self.fn.new_register("and" if is_and else "or", IRType.I1)
        lhs = self.expr(expr.left)
        self.copy_into(result, lhs)
        rhs_block = self.fn.new_block("and.rhs" if is_and else "or.rhs")
        end = self.fn.new_block("and.end" if is_and else "or.end")
        if is_and:
            self.emit(BranchInst(lhs, rhs_block, end))
        else:
            self.emit(BranchInst(lhs, end, rhs_block))
        self.start_block(rhs_block)
        self.copy_into(result, self.expr(expr.right))
        self.jump(end)
        self.fn.blocks.remove(end)
        self.fn.blocks.append(end)
        self.start_block(end)
        return result

    def cast(self, value: Value, target: IRType) -> Value:
        source = value.type
        if source is target:
            return value
        if target is IRType.F64:
            if source is IRType.I1:
                value = self.unary(Opcode.ZEXT, value, IRType.I64)
            return self.unary(Opcode.SITOFP, value, IRType.F64)
        if target is IRType.I64:
            if source is IRType.F64:
                return self.unary(Opcode.FPTOSI, value, IRType.I64)
            return self.unary(Opcode.ZEXT, value, IRType.I64)
        assert target is IRType.I1
        return self.compare(CmpPred.NE, value, _zero(source))

    def address(self, expr: ast.Index) -> tuple[Value, Value, Type]:
        """Bounds-check every index and compute the flat element offset.

        Returns ``(base pointer, offset, type at that offset)``. The type is an
        ``ArrayType`` for a partial index such as ``m[i]`` on a 2-D array.
        """
        chain: list[ast.Expr] = []
        node: ast.Expr = expr
        while isinstance(node, ast.Index):
            chain.append(node.index)
            node = node.base
        assert isinstance(node, ast.Name) and node.symbol is not None
        ptr, ty = self.arrays[node.symbol.uid]
        current: Type = ty
        offset: Value = const_int(0)
        for index_expr in reversed(chain):  # outermost dimension first
            assert isinstance(current, ArrayType)
            index = self.expr(index_expr)
            self.emit(BoundsCheckInst(index, current.size))
            element = current.element
            stride = element.total_elements if isinstance(element, ArrayType) else 1
            term = index if stride == 1 else self.binary(Opcode.MUL, index, const_int(stride))
            is_zero = isinstance(offset, Constant) and offset.value == 0
            offset = term if is_zero else self.binary(Opcode.ADD, offset, term)
            current = element
        return ptr, offset, current

    def call(self, expr: ast.Call) -> Value:
        args = [self.expr(a) for a in expr.args]
        if expr.callee == "print":
            self.emit(PrintInst(args[0]))
            return const_int(0)  # never used: print returns nothing
        assert expr.function is not None
        ret = ir_type(expr.function.return_type)
        dest = None if ret is IRType.VOID else self.fn.new_temp(ret)
        self.emit(CallInst(dest, expr.callee, args))
        return dest if dest is not None else const_int(0)


def _flatten_literal(literal: ast.ArrayLiteral, out: list[ast.Expr]) -> None:
    """Row-major flattening of a (possibly nested) array literal."""
    for element in literal.elements:
        if isinstance(element, ast.ArrayLiteral):
            _flatten_literal(element, out)
        else:
            out.append(element)


def lower_program(checked: CheckedProgram) -> Module:
    """Lower every function of a type-checked program to pre-SSA IR."""
    module = Module()
    for decl in checked.ast.functions:
        module.add(FunctionLowering(decl).lower())
    return module

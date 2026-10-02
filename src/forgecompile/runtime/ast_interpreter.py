"""Reference interpreter that executes the type-checked AST directly.

This is the *specification oracle*: a direct transcription of LANGUAGE.md §7
that shares nothing with the IR pipeline except the arithmetic helpers in
``runtime/semantics.py``. Lowering, SSA construction and every optimization
pass are tested by checking that the IR interpreter (and later native code)
produces exactly the same observable behaviour, ``(stdout, exit status)``, as
this interpreter.

It is kept independent of the IR on purpose:

* arrays are nested Python lists, whereas the IR uses flat buffers with
  computed offsets, so offset arithmetic is checked rather than duplicated;
* control flow uses exceptions for ``return``/``break``/``continue``, whereas
  the IR uses explicit basic blocks and branches.

Speed is not a goal. A step budget turns non-terminating programs into a
clean error instead of a hang.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from forgecompile.ast import nodes as ast
from forgecompile.ast.operators import BinaryOp, UnaryOp
from forgecompile.ast.types import BOOL, FLOAT, INT, ArrayType, Type
from forgecompile.runtime import semantics as sem
from forgecompile.runtime.semantics import RuntimeTrap

DEFAULT_MAX_STEPS = 50_000_000
_RECURSION_LIMIT = 20_000


@dataclass
class ExecutionResult:
    """Observable behaviour of one program run."""

    stdout: str
    exit_code: int
    trap: str | None = None  # runtime error message, if the program trapped

    @property
    def observable(self) -> tuple[str, int]:
        return self.stdout, self.exit_code


class StepLimitExceeded(Exception):
    """The program ran longer than the step budget (probably an infinite loop)."""


class _Return(Exception):
    def __init__(self, value: Any) -> None:
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


def zero_value(ty: Type) -> Any:
    """A zero-initialized value: 0, 0.0, false, or nested lists for arrays."""
    if isinstance(ty, ArrayType):
        return [zero_value(ty.element) for _ in range(ty.size)]
    if ty == INT:
        return 0
    if ty == FLOAT:
        return 0.0
    if ty == BOOL:
        return False
    raise TypeError(f"no zero value for type {ty}")


class AstInterpreter:
    def __init__(self, program: ast.Program, max_steps: int = DEFAULT_MAX_STEPS) -> None:
        self.functions = {fn.name: fn for fn in program.functions}
        self.max_steps = max_steps
        self.steps = 0
        self.output: list[str] = []

    # ------------------------------------------------------------------ entry point

    def run(self) -> ExecutionResult:
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, _RECURSION_LIMIT))
        try:
            result = self._call(self.functions["main"], [])
        except RuntimeTrap as trap:
            return ExecutionResult(
                "".join(self.output), sem.RUNTIME_ERROR_EXIT_CODE, trap=str(trap)
            )
        finally:
            sys.setrecursionlimit(old_limit)
        return ExecutionResult("".join(self.output), sem.exit_status(result))

    # ------------------------------------------------------------------ functions

    def _call(self, fn: ast.FunctionDecl, args: list[Any]) -> Any:
        env: dict[int, Any] = {}
        for param, value in zip(fn.params, args, strict=True):
            assert param.symbol is not None
            env[param.symbol.uid] = value  # arrays: the list object itself (by reference)
        try:
            self._block(fn.body, env)
        except _Return as ret:
            return ret.value
        return None

    # ------------------------------------------------------------------ statements

    def _tick(self) -> None:
        self.steps += 1
        if self.steps > self.max_steps:
            raise StepLimitExceeded(f"exceeded {self.max_steps} steps")

    def _block(self, block: ast.Block, env: dict[int, Any]) -> None:
        for stmt in block.statements:
            self._stmt(stmt, env)

    def _stmt(self, stmt: ast.Stmt, env: dict[int, Any]) -> None:
        self._tick()
        match stmt:
            case ast.Block():
                self._block(stmt, env)
            case ast.LetStmt(init=init, symbol=symbol):
                assert symbol is not None
                env[symbol.uid] = zero_value(symbol.type) if init is None else self._eval(init, env)
            case ast.AssignStmt(target=target, value=value_expr):
                if isinstance(target, ast.Name):
                    assert target.symbol is not None
                    env[target.symbol.uid] = self._eval(value_expr, env)
                else:
                    # Left to right: the target's indices are evaluated and
                    # bounds-checked *before* the right-hand side (LANGUAGE.md §7).
                    assert isinstance(target, ast.Index)
                    container = self._eval(target.base, env)
                    index = self._checked_index(container, self._eval(target.index, env))
                    container[index] = self._eval(value_expr, env)
            case ast.IfStmt(condition=cond, then_body=then_body, else_body=else_body):
                if self._eval(cond, env):
                    self._block(then_body, env)
                elif else_body is not None:
                    self._block(else_body, env)
            case ast.WhileStmt(condition=cond, body=body):
                while self._eval(cond, env):
                    try:
                        self._block(body, env)
                    except _Break:
                        break
                    except _Continue:
                        pass
                    self._tick()
            case ast.ForStmt(start=start, end=end, body=body, symbol=symbol):
                assert symbol is not None
                current = self._eval(start, env)
                limit = self._eval(end, env)  # evaluated once (LANGUAGE.md §5)
                while current < limit:
                    env[symbol.uid] = current
                    try:
                        self._block(body, env)
                    except _Break:
                        break
                    except _Continue:
                        pass
                    current = sem.wrap(current + 1)
                    self._tick()
            case ast.ReturnStmt(value=value):
                raise _Return(None if value is None else self._eval(value, env))
            case ast.BreakStmt():
                raise _Break()
            case ast.ContinueStmt():
                raise _Continue()
            case ast.ExprStmt(expr=expr):
                self._eval(expr, env)
            case _:
                raise TypeError(f"unknown statement {type(stmt).__name__}")

    # ------------------------------------------------------------------ expressions

    @staticmethod
    def _checked_index(container: list[Any], index: int) -> int:
        if not 0 <= index < len(container):
            raise RuntimeTrap(f"index {index} out of bounds for array of length {len(container)}")
        return index

    def _eval(self, expr: ast.Expr, env: dict[int, Any]) -> Any:
        match expr:
            case ast.IntLiteral(value=v) | ast.FloatLiteral(value=v) | ast.BoolLiteral(value=v):
                return v
            case ast.Name(symbol=symbol):
                assert symbol is not None
                return env[symbol.uid]
            case ast.ArrayLiteral(elements=elements):
                return [self._eval(e, env) for e in elements]
            case ast.Unary(op=op, operand=operand):
                value = self._eval(operand, env)
                if op is UnaryOp.NOT:
                    return not value
                return -value if isinstance(value, float) else sem.wrap(-value)
            case ast.Binary():
                return self._binary(expr, env)
            case ast.Cast(expr=inner, target=target):
                return _cast(self._eval(inner, env), target)
            case ast.Index(base=base, index=index):
                container = self._eval(base, env)
                return container[self._checked_index(container, self._eval(index, env))]
            case ast.Call(callee="print", args=[arg]):
                self.output.append(sem.format_value(self._eval(arg, env)) + "\n")
                return None
            case ast.Call(callee=callee, args=args):
                values = [self._eval(a, env) for a in args]
                return self._call(self.functions[callee], values)
        raise TypeError(f"unknown expression {type(expr).__name__}")

    def _binary(self, expr: ast.Binary, env: dict[int, Any]) -> Any:
        op = expr.op
        if op is BinaryOp.AND:  # short-circuit
            return bool(self._eval(expr.left, env)) and bool(self._eval(expr.right, env))
        if op is BinaryOp.OR:
            return bool(self._eval(expr.left, env)) or bool(self._eval(expr.right, env))
        a = self._eval(expr.left, env)
        b = self._eval(expr.right, env)
        if isinstance(a, float):
            return _float_binary(op, a, b)
        if isinstance(a, bool):  # only == / != are allowed on bools
            return a == b if op is BinaryOp.EQ else a != b
        return _int_binary(op, a, b)


def _int_binary(op: BinaryOp, a: int, b: int) -> int | bool:
    match op:
        case BinaryOp.ADD:
            return sem.wrap(a + b)
        case BinaryOp.SUB:
            return sem.wrap(a - b)
        case BinaryOp.MUL:
            return sem.wrap(a * b)
        case BinaryOp.DIV:
            return sem.int_div(a, b)
        case BinaryOp.MOD:
            return sem.int_rem(a, b)
        case BinaryOp.EQ:
            return a == b
        case BinaryOp.NE:
            return a != b
        case BinaryOp.LT:
            return a < b
        case BinaryOp.LE:
            return a <= b
        case BinaryOp.GT:
            return a > b
        case BinaryOp.GE:
            return a >= b
    raise TypeError(f"bad int operator {op}")


def _float_binary(op: BinaryOp, a: float, b: float) -> float | bool:
    match op:
        case BinaryOp.ADD:
            return a + b
        case BinaryOp.SUB:
            return a - b
        case BinaryOp.MUL:
            return a * b
        case BinaryOp.DIV:
            return sem.float_div(a, b)
        case BinaryOp.MOD:
            return sem.float_rem(a, b)
        # Python float comparisons already follow IEEE-754: any comparison with
        # NaN is False, except != which is True.
        case BinaryOp.EQ:
            return a == b
        case BinaryOp.NE:
            return a != b
        case BinaryOp.LT:
            return a < b
        case BinaryOp.LE:
            return a <= b
        case BinaryOp.GT:
            return a > b
        case BinaryOp.GE:
            return a >= b
    raise TypeError(f"bad float operator {op}")


def _cast(value: Any, target: Type) -> Any:
    if target == FLOAT:
        return float(value)  # int -> nearest double; bool -> 0.0/1.0
    if target == INT:
        if isinstance(value, float):
            return sem.float_to_int(value)
        return int(value)  # bool -> 0/1
    if target == BOOL:
        return value != 0  # NaN != 0.0 is True, as specified
    raise TypeError(f"bad cast target {target}")


def run_program(program: ast.Program, max_steps: int = DEFAULT_MAX_STEPS) -> ExecutionResult:
    """Execute a type-checked program with the reference AST interpreter."""
    return AstInterpreter(program, max_steps).run()

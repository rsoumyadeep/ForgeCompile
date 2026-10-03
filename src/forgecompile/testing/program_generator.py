"""Random generator of well-typed, terminating MiniLang programs.

Used for *differential testing*. Every generated program runs through the
reference AST interpreter and through the IR pipeline (pre-SSA, SSA, and
later optimized and native), and all of them must agree on
``(stdout, exit status)``. Later phases also use it to generate training
workloads for the ML/RL components.

Guarantees, by construction:

* **Well-typed.** Expressions are generated top-down for a requested type,
  using only variables in scope.
* **Terminating.**
  - ``for`` loops have small constant bounds.
  - ``while`` loops are driven by a hidden counter that the body never
    assigns. It is incremented as the *first* statement of the body, so a
    ``continue`` cannot skip it.
  - Helpers only call helpers defined *earlier*, so there is no recursion.
  - Loop nesting depth is capped.
* **Mostly trap-free.**
  - Divisors have the form ``(e * e + 1)``, which can never be zero: a square
    is 0 or 1 mod 4, so it can never be congruent to -1 mod 2**64, even with
    wrap-around.
  - Indices have the form ``((e % n) + n) % n``, which lies in ``[0, n)``.
  - With probability ``trap_probability``, a raw divisor or index is emitted
    on purpose, so runtime-error behaviour is differentially tested too.

The generator builds AST nodes and prints them with the source formatter, so
every program also exercises the parser and the type checker.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from forgecompile.ast import nodes as ast
from forgecompile.ast.formatter import format_program
from forgecompile.ast.operators import BinaryOp, UnaryOp
from forgecompile.ast.types import BOOL, FLOAT, INT, VOID, ArrayType, Type
from forgecompile.diagnostics import Span

_SPAN = Span(0, 0, 1, 1)
_INTERESTING_INTS = [0, 1, 2, 3, 7, 10, 100, 9223372036854775807, -9223372036854775807]


@dataclass
class GeneratorConfig:
    max_helpers: int = 3
    max_statements: int = 6
    max_expr_depth: int = 3
    max_loop_depth: int = 2
    max_loop_bound: int = 6
    trap_probability: float = 0.02
    # Cumulative thresholds for one uniform draw choosing the next statement kind:
    # let, array let, assignment, print, if, for, while, break/continue (rest: print
    # of an expression). The defaults reproduce the original generator exactly.
    statement_thresholds: tuple[float, ...] = (0.22, 0.30, 0.45, 0.60, 0.70, 0.80, 0.86, 0.90)


# Training-workload profile for the ML/RL phases: more and deeper loops and fewer
# straight-line constant expressions (EXP-001 found the default constant-heavy).
# No deliberate traps (D-036): about 10% of programs trapped at 0.02, which truncates
# their cost and makes them unrepresentative optimization workloads.
LOOP_HEAVY = GeneratorConfig(
    max_statements=7,
    max_loop_depth=3,
    max_loop_bound=6,
    trap_probability=0.0,
    statement_thresholds=(0.15, 0.25, 0.37, 0.45, 0.52, 0.74, 0.85, 0.88),
)


@dataclass
class _Var:
    name: str
    type: Type
    assignable: bool = True


@dataclass
class _Helper:
    name: str
    params: list[Type]
    return_type: Type


@dataclass
class _Scope:
    vars: list[_Var] = field(default_factory=list)


class ProgramGenerator:
    def __init__(self, seed: int, config: GeneratorConfig | None = None) -> None:
        self.rng = random.Random(seed)
        self.config = config or GeneratorConfig()
        self.helpers: list[_Helper] = []
        self.scopes: list[_Scope] = []
        self.counter = 0
        self.loop_depth = 0
        self.in_loop = False
        self.in_helper = False
        self.allow_calls = True
        self.leaf_nesting = 0  # caps array-read-inside-index recursion

    # ================================================================== utilities

    def fresh(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}{self.counter}"

    def visible(self) -> list[_Var]:
        result: list[_Var] = []
        for scope in self.scopes:
            result.extend(scope.vars)
        return result

    def vars_of(self, ty: Type, assignable_only: bool = False) -> list[_Var]:
        return [v for v in self.visible() if v.type == ty and (v.assignable or not assignable_only)]

    def declare(self, var: _Var) -> None:
        self.scopes[-1].vars.append(var)

    def chance(self, p: float) -> bool:
        return self.rng.random() < p

    # ================================================================== expressions

    def expr(self, ty: Type, depth: int) -> ast.Expr:
        if ty == INT:
            return self.int_expr(depth)
        if ty == FLOAT:
            return self.float_expr(depth)
        return self.bool_expr(depth)

    def leaf(self, ty: Type) -> ast.Expr:
        candidates = self.vars_of(ty)
        if candidates and self.chance(0.6):
            return ast.Name(self.rng.choice(candidates).name, span=_SPAN)
        array_reads = [v for v in self.visible() if isinstance(v.type, ArrayType)]
        array_reads = [v for v in array_reads if _scalar(v.type) == ty]
        if array_reads and self.leaf_nesting < 2 and self.chance(0.3):
            self.leaf_nesting += 1
            read = self.array_read(self.rng.choice(array_reads), depth=0)
            self.leaf_nesting -= 1
            return read
        if ty == INT:
            value = (
                self.rng.choice(_INTERESTING_INTS) if self.chance(0.2) else self.rng.randrange(20)
            )
            literal: ast.Expr = ast.IntLiteral(abs(value), span=_SPAN)
            return ast.Unary(UnaryOp.NEG, literal, span=_SPAN) if value < 0 else literal
        if ty == FLOAT:
            return ast.FloatLiteral(
                self.rng.choice([0.0, 0.5, 1.0, 1.5, 2.25, 3.0, 10.0, 1e-3]), span=_SPAN
            )
        return ast.BoolLiteral(self.chance(0.5), span=_SPAN)

    def int_expr(self, depth: int) -> ast.Expr:
        if depth <= 0 or self.chance(0.25):
            return self.leaf(INT)
        choice = self.rng.randrange(10)
        if choice < 4:
            op = self.rng.choice([BinaryOp.ADD, BinaryOp.SUB, BinaryOp.MUL])
            return ast.Binary(op, self.int_expr(depth - 1), self.int_expr(depth - 1), span=_SPAN)
        if choice < 6:
            op = self.rng.choice([BinaryOp.DIV, BinaryOp.MOD])
            return ast.Binary(op, self.int_expr(depth - 1), self.divisor(depth - 1), span=_SPAN)
        if choice == 6:
            return ast.Unary(UnaryOp.NEG, self.int_expr(depth - 1), span=_SPAN)
        if choice == 7:
            source = self.rng.choice([FLOAT, BOOL])
            return ast.Cast(self.expr(source, depth - 1), INT, span=_SPAN)
        if choice == 8:
            call = self.call_returning(INT, depth - 1)
            if call is not None:
                return call
        return self.leaf(INT)

    def divisor(self, depth: int) -> ast.Expr:
        if self.chance(self.config.trap_probability):
            return self.int_expr(depth)  # may be zero: exercises the trap path
        e = self.int_expr(depth)
        square = ast.Binary(BinaryOp.MUL, e, e, span=_SPAN)
        return ast.Binary(BinaryOp.ADD, square, ast.IntLiteral(1, span=_SPAN), span=_SPAN)

    def float_expr(self, depth: int) -> ast.Expr:
        if depth <= 0 or self.chance(0.25):
            return self.leaf(FLOAT)
        choice = self.rng.randrange(8)
        if choice < 5:
            op = self.rng.choice(
                [BinaryOp.ADD, BinaryOp.SUB, BinaryOp.MUL, BinaryOp.DIV, BinaryOp.MOD]
            )
            return ast.Binary(
                op, self.float_expr(depth - 1), self.float_expr(depth - 1), span=_SPAN
            )
        if choice == 5:
            return ast.Unary(UnaryOp.NEG, self.float_expr(depth - 1), span=_SPAN)
        if choice == 6:
            return ast.Cast(self.expr(self.rng.choice([INT, BOOL]), depth - 1), FLOAT, span=_SPAN)
        call = self.call_returning(FLOAT, depth - 1)
        return call if call is not None else self.leaf(FLOAT)

    def bool_expr(self, depth: int) -> ast.Expr:
        if depth <= 0 or self.chance(0.2):
            return self.leaf(BOOL)
        choice = self.rng.randrange(8)
        if choice < 4:
            operand_ty = self.rng.choice([INT, INT, FLOAT])
            op = self.rng.choice(
                [BinaryOp.LT, BinaryOp.LE, BinaryOp.GT, BinaryOp.GE, BinaryOp.EQ, BinaryOp.NE]
            )
            return ast.Binary(
                op, self.expr(operand_ty, depth - 1), self.expr(operand_ty, depth - 1), span=_SPAN
            )
        if choice < 6:
            op = self.rng.choice([BinaryOp.AND, BinaryOp.OR])
            return ast.Binary(op, self.bool_expr(depth - 1), self.bool_expr(depth - 1), span=_SPAN)
        if choice == 6:
            return ast.Unary(UnaryOp.NOT, self.bool_expr(depth - 1), span=_SPAN)
        return ast.Cast(self.int_expr(depth - 1), BOOL, span=_SPAN)

    def safe_index(self, size: int, depth: int) -> ast.Expr:
        index = self.int_expr(depth)
        if self.chance(self.config.trap_probability):
            # May be out of bounds. "+ 0" keeps a literal index from being rejected
            # at compile time (DECISIONS D-015), so the *runtime* trap path is exercised.
            return ast.Binary(BinaryOp.ADD, index, ast.IntLiteral(0, span=_SPAN), span=_SPAN)
        n = ast.IntLiteral(size, span=_SPAN)
        inner = ast.Binary(BinaryOp.MOD, index, n, span=_SPAN)
        shifted = ast.Binary(BinaryOp.ADD, inner, ast.IntLiteral(size, span=_SPAN), span=_SPAN)
        return ast.Binary(BinaryOp.MOD, shifted, ast.IntLiteral(size, span=_SPAN), span=_SPAN)

    def element_ref(self, var: _Var, depth: int) -> ast.Expr:
        expr: ast.Expr = ast.Name(var.name, span=_SPAN)
        ty = var.type
        while isinstance(ty, ArrayType):
            expr = ast.Index(expr, self.safe_index(ty.size, depth), span=_SPAN)
            ty = ty.element
        return expr

    def array_read(self, var: _Var, depth: int) -> ast.Expr:
        return self.element_ref(var, max(depth, 0))

    def call_returning(self, ty: Type, depth: int) -> ast.Expr | None:
        # Calls inside a helper's loops would multiply loop trip counts across
        # helpers (up to bound**(2 * helpers)); keep total runtime small.
        if not self.allow_calls or (self.in_helper and self.in_loop):
            return None
        candidates = [h for h in self.helpers if h.return_type == ty]
        if not candidates:
            return None
        helper = self.rng.choice(candidates)
        args = [self.argument(p, depth) for p in helper.params]
        if any(a is None for a in args):
            return None
        return ast.Call(helper.name, [a for a in args if a is not None], span=_SPAN)

    def argument(self, ty: Type, depth: int) -> ast.Expr | None:
        if isinstance(ty, ArrayType):
            matches = [v for v in self.visible() if v.type == ty]
            return ast.Name(self.rng.choice(matches).name, span=_SPAN) if matches else None
        return self.expr(ty, depth)

    # ================================================================== statements

    def block(self, statements: int) -> ast.Block:
        self.scopes.append(_Scope())
        body = [self.statement() for _ in range(statements)]
        self.scopes.pop()
        return ast.Block(body, span=_SPAN)

    def statement(self) -> ast.Stmt:
        depth = self.config.max_expr_depth
        t_let, t_array, t_assign, t_print, t_if, t_for, t_while, t_jump = (
            self.config.statement_thresholds
        )
        roll = self.rng.random()
        if roll < t_let:
            return self.let_scalar()
        if roll < t_array:
            return self.let_array()
        if roll < t_assign:
            assign = self.assignment()
            if assign is not None:
                return assign
        if roll < t_print:
            return self.print_stmt()
        if roll < t_if:
            return self.if_stmt()
        if roll < t_for and self.loop_depth < self.config.max_loop_depth:
            return self.for_stmt()
        if roll < t_while and self.loop_depth < self.config.max_loop_depth:
            return self.while_stmt()
        if roll < t_jump and self.in_loop:
            return ast.BreakStmt(span=_SPAN) if self.chance(0.5) else ast.ContinueStmt(span=_SPAN)
        return ast.ExprStmt(
            ast.Call("print", [self.expr(self.rng.choice([INT, FLOAT, BOOL]), depth)], span=_SPAN),
            span=_SPAN,
        )

    def let_scalar(self) -> ast.LetStmt:
        ty = self.rng.choice([INT, INT, FLOAT, BOOL])
        name = self.fresh("v")
        init = self.expr(ty, self.config.max_expr_depth)
        stmt = ast.LetStmt(name, ty if self.chance(0.5) else None, init, span=_SPAN)
        self.declare(_Var(name, ty))
        return stmt

    def let_array(self) -> ast.LetStmt:
        element = self.rng.choice([INT, INT, FLOAT, BOOL])
        ty: Type = ArrayType(element, self.rng.randrange(1, 6))
        if self.chance(0.25):
            ty = ArrayType(ty, self.rng.randrange(1, 4))
        name = self.fresh("arr")
        init: ast.Expr | None = None
        is_one_dimensional = isinstance(ty, ArrayType) and not isinstance(ty.element, ArrayType)
        if is_one_dimensional and self.chance(0.4):  # literals only for 1-D arrays
            assert isinstance(ty, ArrayType)
            init = ast.ArrayLiteral([self.expr(element, 1) for _ in range(ty.size)], span=_SPAN)
        stmt = ast.LetStmt(name, ty, init, span=_SPAN)
        self.declare(_Var(name, ty))
        return stmt

    def assignment(self) -> ast.AssignStmt | None:
        depth = self.config.max_expr_depth
        arrays = [v for v in self.visible() if isinstance(v.type, ArrayType)]
        if arrays and self.chance(0.4):
            var = self.rng.choice(arrays)
            target = self.element_ref(var, 1)
            return ast.AssignStmt(target, self.expr(_scalar(var.type), depth), span=_SPAN)
        scalars = [v for v in self.visible() if v.assignable and not isinstance(v.type, ArrayType)]
        if not scalars:
            return None
        var = self.rng.choice(scalars)
        return ast.AssignStmt(
            ast.Name(var.name, span=_SPAN), self.expr(var.type, depth), span=_SPAN
        )

    def print_stmt(self) -> ast.ExprStmt:
        ty = self.rng.choice([INT, INT, FLOAT, BOOL])
        candidates = self.vars_of(ty)
        value = (
            ast.Name(self.rng.choice(candidates).name, span=_SPAN)
            if candidates and self.chance(0.7)
            else self.expr(ty, self.config.max_expr_depth)
        )
        return ast.ExprStmt(ast.Call("print", [value], span=_SPAN), span=_SPAN)

    def if_stmt(self) -> ast.IfStmt:
        cond = self.bool_expr(self.config.max_expr_depth)
        n = max(1, self.config.max_statements // 2)
        then_body = self.block(self.rng.randrange(1, n + 1))
        else_body = self.block(self.rng.randrange(1, n + 1)) if self.chance(0.5) else None
        return ast.IfStmt(cond, then_body, else_body, span=_SPAN)

    def _loop_body(self, statements: int, prefix: list[ast.Stmt] | None = None) -> ast.Block:
        saved = self.in_loop
        self.in_loop = True
        self.loop_depth += 1
        body = self.block(statements)
        self.loop_depth -= 1
        self.in_loop = saved
        if prefix:
            body.statements = prefix + body.statements
        return body

    def for_stmt(self) -> ast.ForStmt:
        var = self.fresh("i")
        start = self.rng.randrange(-2, 3)
        end = start + self.rng.randrange(0, self.config.max_loop_bound + 1)
        start_expr = _int_literal(start)
        end_expr = _int_literal(end)
        self.scopes.append(_Scope([_Var(var, INT, assignable=False)]))
        body = self._loop_body(self.rng.randrange(1, self.config.max_statements))
        self.scopes.pop()
        return ast.ForStmt(var, start_expr, end_expr, body, span=_SPAN)

    def while_stmt(self) -> ast.Block:
        """``{ let w = 0; while w < k && <cond> { w = w + 1; ... } }``"""
        counter = self.fresh("w")
        bound = self.rng.randrange(1, self.config.max_loop_bound + 1)
        self.scopes.append(_Scope([_Var(counter, INT, assignable=False)]))
        cond: ast.Expr = ast.Binary(
            BinaryOp.LT,
            ast.Name(counter, span=_SPAN),
            ast.IntLiteral(bound, span=_SPAN),
            span=_SPAN,
        )
        if self.chance(0.5):
            self.allow_calls = False  # evaluated every iteration
            cond = ast.Binary(BinaryOp.AND, cond, self.bool_expr(2), span=_SPAN)
            self.allow_calls = True
        increment = ast.AssignStmt(
            ast.Name(counter, span=_SPAN),
            ast.Binary(
                BinaryOp.ADD,
                ast.Name(counter, span=_SPAN),
                ast.IntLiteral(1, span=_SPAN),
                span=_SPAN,
            ),
            span=_SPAN,
        )
        body = self._loop_body(self.rng.randrange(1, self.config.max_statements), [increment])
        self.scopes.pop()
        init = ast.LetStmt(counter, INT, ast.IntLiteral(0, span=_SPAN), span=_SPAN)
        return ast.Block([init, ast.WhileStmt(cond, body, span=_SPAN)], span=_SPAN)

    # ================================================================== functions

    def helper(self, index: int) -> ast.FunctionDecl:
        name = f"helper{index}"
        self.in_helper = True
        params: list[ast.Param] = []
        param_types: list[Type] = []
        self.scopes = [_Scope()]
        for p in range(self.rng.randrange(0, 4)):
            ty: Type = self.rng.choice([INT, INT, FLOAT, BOOL])
            if self.chance(0.15):
                ty = ArrayType(self.rng.choice([INT, FLOAT]), self.rng.randrange(1, 5))
            pname = f"p{p}"
            params.append(ast.Param(pname, ty, span=_SPAN))
            param_types.append(ty)
            self.declare(_Var(pname, ty))
        return_type = self.rng.choice([INT, INT, FLOAT, BOOL, VOID])
        statements = [
            self.statement() for _ in range(self.rng.randrange(1, self.config.max_statements + 1))
        ]
        if return_type != VOID:
            statements.append(ast.ReturnStmt(self.expr(return_type, 2), span=_SPAN))
        self.helpers.append(_Helper(name, param_types, return_type))  # callable only by later code
        self.in_helper = False
        return ast.FunctionDecl(
            name, params, return_type, ast.Block(statements, span=_SPAN), span=_SPAN
        )

    def program(self) -> ast.Program:
        functions = [
            self.helper(i) for i in range(self.rng.randrange(0, self.config.max_helpers + 1))
        ]
        self.scopes = [_Scope()]
        statements = [
            self.statement() for _ in range(self.rng.randrange(3, self.config.max_statements + 4))
        ]
        for helper in self.helpers:  # make sure every helper is exercised at least once
            if helper.return_type == VOID:
                args = [self.argument(p, 1) for p in helper.params]
                if all(a is not None for a in args):
                    call = ast.Call(helper.name, [a for a in args if a is not None], span=_SPAN)
                    statements.append(ast.ExprStmt(call, span=_SPAN))
        exit_value = ast.Binary(
            BinaryOp.MOD, self.int_expr(2), ast.IntLiteral(256, span=_SPAN), span=_SPAN
        )
        statements.append(ast.ReturnStmt(exit_value, span=_SPAN))
        main = ast.FunctionDecl("main", [], INT, ast.Block(statements, span=_SPAN), span=_SPAN)
        return ast.Program([*functions, main], span=_SPAN)


def _scalar(ty: Type) -> Type:
    return ty.scalar_element if isinstance(ty, ArrayType) else ty


def _int_literal(value: int) -> ast.Expr:
    literal = ast.IntLiteral(abs(value), span=_SPAN)
    return ast.Unary(UnaryOp.NEG, literal, span=_SPAN) if value < 0 else literal


def generate_program(seed: int, config: GeneratorConfig | None = None) -> str:
    """MiniLang source of a random, well-typed, terminating program (deterministic per seed)."""
    return format_program(ProgramGenerator(seed, config).program())

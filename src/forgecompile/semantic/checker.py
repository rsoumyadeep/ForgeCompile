"""Semantic analysis: name resolution, type checking, and structural rules.

Runs in two passes over the AST:

1. **Collect signatures.** Every function's name, parameter types and return
   type go into a global table before any body is checked. Calls may then
   refer to functions defined later in the file, which allows mutual
   recursion, as in C with prototypes but without writing them.
2. **Check bodies.** One recursive walk per function. It resolves every name to
   its symbol, computes every expression's type, and enforces the rules in
   docs/LANGUAGE.md §5-6.

Results are written onto the AST: ``Expr.ty`` for every expression, and the
resolved symbol on ``Name``/``LetStmt``/``ForStmt``/``Param``/``Call``/
``FunctionDecl``. IR lowering relies on both.

**Error handling.** Problems are collected, never raised one at a time. An
expression that fails to type-check is given the ``ERROR`` type. Every rule
accepts ``ERROR`` without comment, so ``(1 + true) * 2`` reports *one* error,
not two.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from forgecompile.ast import nodes as ast
from forgecompile.ast.operators import BinaryOp, UnaryOp
from forgecompile.ast.types import BOOL, ERROR, FLOAT, INT, VOID, ArrayType, Type
from forgecompile.diagnostics import CompileError, Diagnostic, Span
from forgecompile.semantic.control_flow import completes_normally
from forgecompile.semantic.symbols import FunctionSymbol, Scope, VariableKind, VariableSymbol

PRINT = FunctionSymbol("print", (), VOID, span=None, builtin=True)
NO_IMPLICIT_CONVERSION_NOTE = "MiniLang has no implicit conversions; convert explicitly with 'as'"


@dataclass
class ProgramInfo:
    """Program-level results of semantic analysis."""

    functions: dict[str, FunctionSymbol]
    main: FunctionSymbol


def _did_you_mean(name: str, candidates: set[str]) -> tuple[str, ...]:
    matches = difflib.get_close_matches(name, sorted(candidates), n=1, cutoff=0.6)
    return (f"did you mean '{matches[0]}'?",) if matches else ()


class TypeChecker:
    def __init__(self) -> None:
        self.diagnostics: list[Diagnostic] = []
        self.functions: dict[str, FunctionSymbol] = {}
        self._next_uid = 0
        self._function: FunctionSymbol | None = None  # function being checked
        self._loop_depth = 0
        self._scope = Scope()

    # ================================================================== helpers

    def _error(self, message: str, span: Span | None, *notes: str) -> None:
        self.diagnostics.append(Diagnostic.error(message, span, *notes))

    def _new_variable(self, name: str, ty: Type, kind: VariableKind, span: Span) -> VariableSymbol:
        symbol = VariableSymbol(name, ty, kind, span, self._next_uid)
        self._next_uid += 1
        return symbol

    def _declare(self, symbol: VariableSymbol) -> None:
        previous = self._scope.declare(symbol)
        if previous is not None:
            self._error(
                f"'{symbol.name}' is already declared in this scope",
                symbol.span,
                f"previous declaration as {previous.kind.value} at line {previous.span}",
            )

    def _push_scope(self) -> None:
        self._scope = Scope(self._scope)

    def _pop_scope(self) -> None:
        assert self._scope.parent is not None
        self._scope = self._scope.parent

    # ================================================================== program

    def check_program(self, program: ast.Program) -> ProgramInfo | None:
        self._collect_signatures(program)
        for fn in program.functions:
            if fn.symbol is not None:  # None when the declaration itself was invalid
                self._check_function(fn, fn.symbol)
        main = self._check_main(program)
        if self.diagnostics or main is None:
            return None
        return ProgramInfo(self.functions, main)

    def _collect_signatures(self, program: ast.Program) -> None:
        for fn in program.functions:
            if fn.name == PRINT.name:
                self._error("'print' is a built-in function and cannot be redefined", fn.span)
                continue
            previous = self.functions.get(fn.name)
            if previous is not None:
                assert previous.span is not None
                self._error(
                    f"function '{fn.name}' is already defined",
                    fn.span,
                    f"previous definition at line {previous.span}",
                )
                continue
            params = [
                self._new_variable(p.name, p.type, VariableKind.PARAM, p.span) for p in fn.params
            ]
            for param_node, param_symbol in zip(fn.params, params, strict=True):
                param_node.symbol = param_symbol
            symbol = FunctionSymbol(
                fn.name, tuple(p.type for p in fn.params), fn.return_type, fn.span, params=params
            )
            fn.symbol = symbol
            self.functions[fn.name] = symbol

    def _check_main(self, program: ast.Program) -> FunctionSymbol | None:
        main = self.functions.get("main")
        if main is None:
            self._error(
                "program has no 'main' function", program.span if program.functions else None
            )
            return None
        if main.param_types:
            self._error("'main' must not take parameters", main.span)
        if main.return_type not in (INT, VOID):
            self._error(f"'main' must return int or nothing, not {main.return_type}", main.span)
        return main

    def _check_function(self, fn: ast.FunctionDecl, symbol: FunctionSymbol) -> None:
        self._function = symbol
        self._scope = Scope()  # function scope: parameters + top-level body statements
        for param in symbol.params:
            self._declare(param)
        # The body's top level shares the parameter scope, so `let n` with a
        # parameter `n` is a redeclaration error (LANGUAGE.md §6).
        for stmt in fn.body.statements:
            self._check_stmt(stmt)
        if symbol.return_type != VOID and completes_normally(fn.body):
            self._error(
                f"function '{fn.name}' may reach the end of its body without returning a value",
                fn.span,
                f"every path through '{fn.name}' must end in 'return <{symbol.return_type}>'",
            )
        self._function = None

    # ================================================================== statements

    def _check_block(self, block: ast.Block) -> None:
        self._push_scope()
        for stmt in block.statements:
            self._check_stmt(stmt)
        self._pop_scope()

    def _check_stmt(self, stmt: ast.Stmt) -> None:
        match stmt:
            case ast.Block():
                self._check_block(stmt)
            case ast.LetStmt():
                self._check_let(stmt)
            case ast.AssignStmt():
                self._check_assign(stmt)
            case ast.IfStmt(condition=cond, then_body=then_body, else_body=else_body):
                self._check_condition(cond, "if")
                self._check_block(then_body)
                if else_body is not None:
                    self._check_block(else_body)
            case ast.WhileStmt(condition=cond, body=body):
                self._check_condition(cond, "while")
                self._loop_depth += 1
                self._check_block(body)
                self._loop_depth -= 1
            case ast.ForStmt():
                self._check_for(stmt)
            case ast.ReturnStmt():
                self._check_return(stmt)
            case ast.BreakStmt() | ast.ContinueStmt():
                if self._loop_depth == 0:
                    word = "break" if isinstance(stmt, ast.BreakStmt) else "continue"
                    self._error(f"'{word}' outside of a loop", stmt.span)
            case ast.ExprStmt(expr=expr):
                self._check_expr(expr)
                if not isinstance(expr, ast.Call):
                    self._error(
                        "expression result is unused",
                        expr.span,
                        "only function calls can be used as statements",
                    )
            case _:
                raise TypeError(f"unknown statement {type(stmt).__name__}")

    def _check_let(self, stmt: ast.LetStmt) -> None:
        init_type: Type | None = None
        if stmt.init is not None:
            init_type = self._check_value(stmt.init, allow_array_literal=True)
        declared = stmt.declared_type
        var_type = declared if declared is not None else init_type
        assert var_type is not None  # the parser requires a type or an initializer

        if stmt.init is not None and init_type is not None and init_type != ERROR:
            if isinstance(init_type, ArrayType) and not isinstance(stmt.init, ast.ArrayLiteral):
                self._error(
                    "arrays cannot be copied",
                    stmt.init.span,
                    "declare a new array and copy its elements in a loop",
                )
            elif declared is not None and init_type != declared:
                notes = (NO_IMPLICIT_CONVERSION_NOTE,) if declared.is_numeric else ()
                self._error(
                    f"mismatched types: '{stmt.name}' is declared as {declared} "
                    f"but initialized with {init_type}",
                    stmt.init.span,
                    *notes,
                )
        # Declared *after* checking the initializer: in `let x = x + 1;` the
        # right-hand `x` refers to an outer variable (as in Rust).
        symbol = self._new_variable(stmt.name, var_type, VariableKind.LOCAL, stmt.span)
        stmt.symbol = symbol
        self._declare(symbol)

    def _check_assign(self, stmt: ast.AssignStmt) -> None:
        target_type = self._check_value(stmt.target)
        if isinstance(stmt.target, ast.Name) and stmt.target.symbol is not None:
            symbol = stmt.target.symbol
            if not symbol.mutable:
                self._error(
                    f"cannot assign to {symbol.kind.value} '{symbol.name}'",
                    stmt.target.span,
                    "the variable of a 'for' loop is read-only",
                )
        value_type = self._check_value(stmt.value)
        if isinstance(target_type, ArrayType):
            self._error(
                "cannot assign to an entire array",
                stmt.target.span,
                "assign individual elements instead, e.g. a[i] = ...",
            )
        elif ERROR not in (target_type, value_type) and target_type != value_type:
            notes = (NO_IMPLICIT_CONVERSION_NOTE,) if target_type.is_numeric else ()
            self._error(
                f"mismatched types: cannot assign {value_type} to {target_type}",
                stmt.value.span,
                *notes,
            )

    def _check_condition(self, cond: ast.Expr, keyword: str) -> None:
        ty = self._check_value(cond)
        if ty in (BOOL, ERROR):
            return
        notes = ("compare explicitly, e.g. 'x != 0'",) if ty.is_numeric else ()
        self._error(f"'{keyword}' condition must be bool, found {ty}", cond.span, *notes)

    def _check_for(self, stmt: ast.ForStmt) -> None:
        for bound, which in ((stmt.start, "start"), (stmt.end, "end")):
            ty = self._check_value(bound)
            if ty not in (INT, ERROR):
                self._error(f"range {which} must be int, found {ty}", bound.span)
        self._push_scope()  # holds only the loop variable; the body block nests inside
        symbol = self._new_variable(stmt.var, INT, VariableKind.LOOP_VAR, stmt.span)
        stmt.symbol = symbol
        self._declare(symbol)
        self._loop_depth += 1
        self._check_block(stmt.body)
        self._loop_depth -= 1
        self._pop_scope()

    def _check_return(self, stmt: ast.ReturnStmt) -> None:
        assert self._function is not None
        expected = self._function.return_type
        name = self._function.name
        if stmt.value is None:
            if expected != VOID:
                self._error(f"function '{name}' must return a value of type {expected}", stmt.span)
            return
        actual = self._check_value(stmt.value)
        if expected == VOID:
            self._error(f"function '{name}' does not return a value", stmt.value.span)
        elif actual not in (expected, ERROR):
            notes = (NO_IMPLICIT_CONVERSION_NOTE,) if expected.is_numeric else ()
            self._error(
                f"mismatched types: function '{name}' returns {expected}, found {actual}",
                stmt.value.span,
                *notes,
            )

    # ================================================================== expressions

    def _check_value(self, expr: ast.Expr, allow_array_literal: bool = False) -> Type:
        """Check an expression used as a *value*: a call to a void function is an error."""
        ty = self._check_expr(expr, allow_array_literal)
        if ty == VOID:
            assert isinstance(expr, ast.Call)
            self._error(f"'{expr.callee}' does not return a value", expr.span)
            expr.ty = ERROR
            return ERROR
        return ty

    def _check_expr(self, expr: ast.Expr, allow_array_literal: bool = False) -> Type:
        ty = self._infer(expr, allow_array_literal)
        expr.ty = ty
        return ty

    def _infer(self, expr: ast.Expr, allow_array_literal: bool) -> Type:
        match expr:
            case ast.IntLiteral():
                return INT
            case ast.FloatLiteral():
                return FLOAT
            case ast.BoolLiteral():
                return BOOL
            case ast.Name():
                return self._infer_name(expr)
            case ast.Unary():
                return self._infer_unary(expr)
            case ast.Binary():
                return self._infer_binary(expr)
            case ast.Cast():
                return self._infer_cast(expr)
            case ast.Index():
                return self._infer_index(expr)
            case ast.Call():
                return self._infer_call(expr)
            case ast.ArrayLiteral():
                return self._infer_array_literal(expr, allow_array_literal)
        raise TypeError(f"unknown expression {type(expr).__name__}")

    def _infer_name(self, expr: ast.Name) -> Type:
        symbol = self._scope.lookup(expr.ident)
        if symbol is None:
            if expr.ident in self.functions or expr.ident == PRINT.name:
                self._error(
                    f"'{expr.ident}' is a function, not a variable",
                    expr.span,
                    f"call it: {expr.ident}(...)",
                )
            else:
                self._error(
                    f"undefined variable '{expr.ident}'",
                    expr.span,
                    *_did_you_mean(expr.ident, self._scope.visible_names()),
                )
            return ERROR
        expr.symbol = symbol
        return symbol.type

    def _infer_unary(self, expr: ast.Unary) -> Type:
        operand = self._check_value(expr.operand)
        if operand == ERROR:
            return ERROR
        if expr.op is UnaryOp.NEG and operand.is_numeric:
            return operand
        if expr.op is UnaryOp.NOT and operand == BOOL:
            return BOOL
        expected = "int or float" if expr.op is UnaryOp.NEG else "bool"
        self._error(
            f"operator '{expr.op.value}' cannot be applied to {operand}",
            expr.span,
            f"'{expr.op.value}' expects {expected}",
        )
        return ERROR

    def _infer_binary(self, expr: ast.Binary) -> Type:
        left = self._check_value(expr.left)
        right = self._check_value(expr.right)
        if ERROR in (left, right):
            return ERROR
        op = expr.op
        if op.is_logical:
            if left == BOOL and right == BOOL:
                return BOOL
            self._error(
                f"operator '{op.value}' requires bool operands, found {left} and {right}",
                expr.span,
            )
            return ERROR
        if op in (BinaryOp.EQ, BinaryOp.NE):
            if left == right and left.is_scalar:
                return BOOL
        elif left == right and left.is_numeric:
            return left if op.is_arithmetic else BOOL  # arithmetic or ordering comparison

        notes: tuple[str, ...] = ()
        if left.is_numeric and right.is_numeric:  # int vs float
            notes = (NO_IMPLICIT_CONVERSION_NOTE,)
        self._error(
            f"operator '{op.value}' cannot be applied to {left} and {right}", expr.span, *notes
        )
        return ERROR

    def _infer_cast(self, expr: ast.Cast) -> Type:
        source = self._check_value(expr.expr)
        if source != ERROR and not (source.is_scalar and expr.target.is_scalar):
            self._error(f"cannot cast {source} to {expr.target}", expr.span)
        # Even after an error the result has the target type, which limits cascades.
        return expr.target

    def _infer_index(self, expr: ast.Index) -> Type:
        base = self._check_value(expr.base)
        index = self._check_value(expr.index)
        if index not in (INT, ERROR):
            self._error(f"array index must be int, found {index}", expr.index.span)
        if base == ERROR:
            return ERROR
        if not isinstance(base, ArrayType):
            self._error(f"cannot index into a value of type {base}", expr.base.span)
            return ERROR
        constant = _constant_index(expr.index)
        if constant is not None and not 0 <= constant < base.size:
            self._error(
                f"index {constant} is out of bounds for an array of length {base.size}",
                expr.index.span,
            )
        return base.element

    def _infer_call(self, expr: ast.Call) -> Type:
        if expr.callee == PRINT.name:
            return self._infer_print(expr)
        function = self.functions.get(expr.callee)
        arg_types = [self._check_value(arg) for arg in expr.args]
        if function is None:
            if self._scope.lookup(expr.callee) is not None:
                self._error(f"'{expr.callee}' is a variable, not a function", expr.span)
            else:
                self._error(
                    f"undefined function '{expr.callee}'",
                    expr.span,
                    *_did_you_mean(expr.callee, set(self.functions) | {PRINT.name}),
                )
            return ERROR
        expr.function = function
        expected = function.param_types
        if len(arg_types) != len(expected):
            plural = "s" if len(expected) != 1 else ""
            self._error(
                f"function '{function.name}' takes {len(expected)} argument{plural}, "
                f"but {len(arg_types)} were given",
                expr.span,
                f"signature: {function.signature()}",
            )
        else:
            for position, (arg, actual, wanted) in enumerate(
                zip(expr.args, arg_types, expected, strict=True), start=1
            ):
                if actual not in (wanted, ERROR):
                    self._error(
                        f"argument {position} of '{function.name}' has type {actual}, "
                        f"expected {wanted}",
                        arg.span,
                        f"signature: {function.signature()}",
                    )
        return function.return_type

    def _infer_print(self, expr: ast.Call) -> Type:
        expr.function = PRINT
        arg_types = [self._check_value(arg) for arg in expr.args]
        if len(arg_types) != 1:
            self._error(
                f"'print' takes exactly 1 argument, but {len(arg_types)} were given", expr.span
            )
        elif arg_types[0] != ERROR and not arg_types[0].is_scalar:
            self._error(
                f"'print' cannot print a value of type {arg_types[0]}",
                expr.args[0].span,
                "print elements individually in a loop",
            )
        return VOID

    def _infer_array_literal(self, expr: ast.ArrayLiteral, allowed: bool) -> Type:
        element_types = [self._check_value(e, allow_array_literal=True) for e in expr.elements]
        if not allowed:
            self._error(
                "array literals are only allowed as 'let' initializers",
                expr.span,
                "e.g. let a: [int; 3] = [1, 2, 3];",
            )
            return ERROR
        if not element_types:
            self._error("empty array literal", expr.span, "arrays must have at least one element")
            return ERROR
        if ERROR in element_types:
            return ERROR
        first = element_types[0]
        for element, ty in zip(expr.elements[1:], element_types[1:], strict=True):
            if ty != first:
                self._error(
                    f"array elements must all have the same type: expected {first}, found {ty}",
                    element.span,
                )
                return ERROR
        return ArrayType(first, len(element_types))


def _constant_index(expr: ast.Expr) -> int | None:
    """The value of a literal index (``a[3]``, ``a[-1]``), or None if not a literal."""
    if isinstance(expr, ast.IntLiteral):
        return expr.value
    if (
        isinstance(expr, ast.Unary)
        and expr.op is UnaryOp.NEG
        and isinstance(expr.operand, ast.IntLiteral)
    ):
        return -expr.operand.value
    return None


def analyze(program: ast.Program) -> ProgramInfo:
    """Type-check ``program`` in place. Raises :class:`CompileError` listing all problems."""
    checker = TypeChecker()
    info = checker.check_program(program)
    if info is None:
        diagnostics = sorted(checker.diagnostics, key=lambda d: d.span.start if d.span else -1)
        raise CompileError(diagnostics)
    return info

"""Recursive-descent parser with Pratt (precedence-climbing) expression parsing.

Grammar (EBNF; the full specification is in docs/LANGUAGE.md)::

    program     = { function } EOF ;
    function    = "fn" IDENT "(" [ param { "," param } [ "," ] ] ")" [ "->" type ] block ;
    param       = IDENT ":" type ;
    type        = "int" | "float" | "bool" | "[" type ";" INT "]" ;
    block       = "{" { statement } "}" ;
    statement   = let | if | while | for | return | "break" ";" | "continue" ";"
                | block | expr [ "=" expr ] ";" ;
    let         = "let" IDENT [ ":" type ] [ "=" expr ] ";" ;
    if          = "if" expr block [ "else" ( if | block ) ] ;
    while       = "while" expr block ;
    for         = "for" IDENT "in" expr ".." expr block ;
    return      = "return" [ expr ] ";" ;
    expr        = (Pratt-parsed using the table in forgecompile/ast/operators.py)

Statements use plain recursive descent: one method per rule, chosen by the
first token. Expressions use a Pratt loop, because encoding nine precedence
levels as nine mutually recursive grammar rules is verbose and slow.

**Error recovery (panic mode).** On a syntax error the parser records a
diagnostic and raises ``_SyntaxError``. The statement loop catches it, skips
tokens until a likely statement boundary (``;``, ``}``, or a statement keyword),
and carries on. One run can therefore report several independent errors. The
cost is occasional follow-on errors, which the parser limits by never
reporting two errors at the same token.
"""

from __future__ import annotations

from forgecompile.ast import nodes as ast
from forgecompile.ast.operators import NON_ASSOCIATIVE, BinaryOp, Precedence, UnaryOp
from forgecompile.ast.types import BOOL, FLOAT, INT, VOID, ArrayType, Type
from forgecompile.diagnostics import Diagnostic, Span
from forgecompile.frontend.tokens import KEYWORDS, Token, TokenKind

BINARY_OPERATORS: dict[TokenKind, BinaryOp] = {
    TokenKind.OR: BinaryOp.OR,
    TokenKind.AND: BinaryOp.AND,
    TokenKind.EQ: BinaryOp.EQ,
    TokenKind.NE: BinaryOp.NE,
    TokenKind.LT: BinaryOp.LT,
    TokenKind.LE: BinaryOp.LE,
    TokenKind.GT: BinaryOp.GT,
    TokenKind.GE: BinaryOp.GE,
    TokenKind.PLUS: BinaryOp.ADD,
    TokenKind.MINUS: BinaryOp.SUB,
    TokenKind.STAR: BinaryOp.MUL,
    TokenKind.SLASH: BinaryOp.DIV,
    TokenKind.PERCENT: BinaryOp.MOD,
}

UNARY_OPERATORS: dict[TokenKind, UnaryOp] = {
    TokenKind.MINUS: UnaryOp.NEG,
    TokenKind.NOT: UnaryOp.NOT,
}

PRIMITIVE_TYPE_TOKENS: dict[TokenKind, Type] = {
    TokenKind.INT_TYPE: INT,
    TokenKind.FLOAT_TYPE: FLOAT,
    TokenKind.BOOL_TYPE: BOOL,
}

# Tokens that begin a statement: recovery stops before them.
STATEMENT_START = frozenset(
    {
        TokenKind.LET,
        TokenKind.IF,
        TokenKind.WHILE,
        TokenKind.FOR,
        TokenKind.RETURN,
        TokenKind.BREAK,
        TokenKind.CONTINUE,
        TokenKind.FN,
    }
)


class _SyntaxError(Exception):
    """Internal control flow: unwinds to the nearest recovery point."""


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        if not tokens or tokens[-1].kind is not TokenKind.EOF:
            raise ValueError("token stream must end with EOF")
        self.tokens = tokens
        self.pos = 0
        self.diagnostics: list[Diagnostic] = []
        self._last_error_pos = -1

    # ================================================================== token helpers

    @property
    def current(self) -> Token:
        return self.tokens[self.pos]

    @property
    def previous(self) -> Token:
        return self.tokens[self.pos - 1] if self.pos > 0 else self.tokens[0]

    def _peek_kind(self, offset: int = 1) -> TokenKind:
        index = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[index].kind

    def _check(self, kind: TokenKind) -> bool:
        return self.current.kind is kind

    def _advance(self) -> Token:
        token = self.current
        if token.kind is not TokenKind.EOF:
            self.pos += 1
        return token

    def _match(self, kind: TokenKind) -> bool:
        if self._check(kind):
            self._advance()
            return True
        return False

    def _error(self, message: str, span: Span, *notes: str) -> _SyntaxError:
        """Record a diagnostic (once per token position) and return an exception to raise."""
        if self.pos != self._last_error_pos:
            self.diagnostics.append(Diagnostic.error(message, span, *notes))
            self._last_error_pos = self.pos
        return _SyntaxError(message)

    def _expect(self, kind: TokenKind, context: str) -> Token:
        if self._check(kind):
            return self._advance()
        if kind in (TokenKind.SEMICOLON, TokenKind.RPAREN, TokenKind.RBRACKET) and self.pos > 0:
            # A missing closer is best reported just after the previous token
            # (`let x = 5` <- here), not at the start of the next line.
            prev = self.previous.span
            span = Span(prev.end, prev.end + 1, prev.line, prev.column + (prev.end - prev.start))
        else:
            span = self.current.span
        raise self._error(
            f"expected {kind.describe()} {context}, found {self.current.describe()}", span
        )

    def _expect_ident(self, context: str) -> Token:
        if self._check(TokenKind.IDENT):
            return self._advance()
        message = f"expected identifier {context}, found {self.current.describe()}"
        if self.current.kind in KEYWORDS.values():
            # A keyword used as a name (`let let = 1;`): report it, then treat
            # it as the name and keep parsing. This avoids follow-on errors.
            self._error(message, self.current.span, f"'{self.current.text}' is a reserved keyword")
            return self._advance()
        raise self._error(message, self.current.span)

    def _synchronize(self) -> None:
        """Skip tokens until a plausible statement boundary (panic-mode recovery).

        Brace depth is tracked so that a ``{ ... }`` inside the broken statement
        (e.g. the body of ``if a < b < c { }``) is skipped as a unit. Without
        this, its ``}`` would be mistaken for the end of the enclosing block
        (see docs/FAILURES.md, F-002).
        """
        depth = 0
        while not self._check(TokenKind.EOF):
            kind = self.current.kind
            if kind is TokenKind.LBRACE:
                depth += 1
            elif kind is TokenKind.RBRACE:
                if depth == 0:
                    return  # end of the enclosing block: let the block parser consume it
                depth -= 1
                self._advance()
                if depth == 0:
                    return  # a skipped `{ ... }` group ends a statement
                continue
            elif depth == 0:
                if kind is TokenKind.SEMICOLON:
                    self._advance()
                    return
                if kind in STATEMENT_START:
                    return
            self._advance()

    # ================================================================== declarations

    def parse_program(self) -> ast.Program:
        start = self.current.span
        functions: list[ast.FunctionDecl] = []
        while not self._check(TokenKind.EOF):
            if not self._check(TokenKind.FN):
                self._error(
                    f"expected 'fn' at top level, found {self.current.describe()}",
                    self.current.span,
                    "only function declarations may appear at the top level",
                )
                self._skip_to_next_function()
                continue
            try:
                functions.append(self._function())
            except _SyntaxError:
                self._skip_to_next_function()
        return ast.Program(functions, span=start.cover(self.current.span))

    def _skip_to_next_function(self) -> None:
        # Stops *at* an `fn` without consuming it: if the error was caused by a
        # missing '}' just before the next function, that function still parses.
        while not self._check(TokenKind.EOF) and not self._check(TokenKind.FN):
            self._advance()

    def _function(self) -> ast.FunctionDecl:
        fn_token = self._expect(TokenKind.FN, "to start a function")
        name = self._expect_ident("after 'fn'")
        self._expect(TokenKind.LPAREN, "after function name")
        params: list[ast.Param] = []
        while not self._check(TokenKind.RPAREN):
            param_name = self._expect_ident("for parameter name")
            self._expect(TokenKind.COLON, "after parameter name")
            param_type = self._type()
            params.append(
                ast.Param(
                    param_name.text, param_type, span=param_name.span.cover(self.previous.span)
                )
            )
            if not self._match(TokenKind.COMMA):
                break
        self._expect(TokenKind.RPAREN, "to close the parameter list")
        return_type = self._type() if self._match(TokenKind.ARROW) else VOID
        body = self._block()
        return ast.FunctionDecl(
            name.text, params, return_type, body, span=fn_token.span.cover(body.span)
        )

    def _type(self) -> Type:
        token = self.current
        primitive = PRIMITIVE_TYPE_TOKENS.get(token.kind)
        if primitive is not None:
            self._advance()
            return primitive
        if self._match(TokenKind.LBRACKET):
            element = self._type()
            self._expect(TokenKind.SEMICOLON, "between array element type and size")
            size_token = self._expect(TokenKind.INT, "for array size")
            assert isinstance(size_token.value, int)
            if size_token.value <= 0:
                raise self._error("array size must be positive", size_token.span)
            self._expect(TokenKind.RBRACKET, "to close the array type")
            return ArrayType(element, size_token.value)
        raise self._error(
            f"expected a type, found {token.describe()}",
            token.span,
            "types are 'int', 'float', 'bool' or '[T; N]'",
        )

    # ================================================================== statements

    def _block(self) -> ast.Block:
        open_brace = self._expect(TokenKind.LBRACE, "to start a block")
        statements: list[ast.Stmt] = []
        while not self._check(TokenKind.RBRACE) and not self._check(TokenKind.EOF):
            if self._check(TokenKind.FN):
                # Almost certainly a missing '}' before the next function.
                break
            start_pos = self.pos
            try:
                statements.append(self._statement())
            except _SyntaxError:
                self._synchronize()
                if self.pos == start_pos and not self._check(TokenKind.RBRACE):
                    self._advance()  # guarantee progress, so recovery can never loop forever
        close = self._expect(TokenKind.RBRACE, "to close the block")
        return ast.Block(statements, span=open_brace.span.cover(close.span))

    def _statement(self) -> ast.Stmt:
        kind = self.current.kind
        if kind is TokenKind.LET:
            return self._let()
        if kind is TokenKind.IF:
            return self._if()
        if kind is TokenKind.WHILE:
            return self._while()
        if kind is TokenKind.FOR:
            return self._for()
        if kind is TokenKind.RETURN:
            return self._return()
        if kind in (TokenKind.BREAK, TokenKind.CONTINUE):
            token = self._advance()
            self._expect(TokenKind.SEMICOLON, f"after '{token.text}'")
            node_class = ast.BreakStmt if kind is TokenKind.BREAK else ast.ContinueStmt
            return node_class(span=token.span.cover(self.previous.span))
        if kind is TokenKind.LBRACE:
            return self._block()
        return self._expression_statement()

    def _let(self) -> ast.LetStmt:
        let_token = self._advance()
        name = self._expect_ident("after 'let'")
        declared = self._type() if self._match(TokenKind.COLON) else None
        init = self._expression() if self._match(TokenKind.ASSIGN) else None
        if declared is None and init is None:
            raise self._error(
                f"variable '{name.text}' needs a type annotation or an initializer",
                name.span,
                f"e.g. 'let {name.text}: int;' or 'let {name.text} = 0;'",
            )
        self._expect(TokenKind.SEMICOLON, "after variable declaration")
        return ast.LetStmt(name.text, declared, init, span=let_token.span.cover(self.previous.span))

    def _if(self) -> ast.IfStmt:
        if_token = self._advance()
        condition = self._expression()
        then_body = self._block()
        else_body: ast.Block | None = None
        if self._match(TokenKind.ELSE):
            if self._check(TokenKind.IF):
                nested = self._if()
                else_body = ast.Block([nested], span=nested.span)  # desugar `else if`
            else:
                else_body = self._block()
        end = (else_body or then_body).span
        return ast.IfStmt(condition, then_body, else_body, span=if_token.span.cover(end))

    def _while(self) -> ast.WhileStmt:
        while_token = self._advance()
        condition = self._expression()
        body = self._block()
        return ast.WhileStmt(condition, body, span=while_token.span.cover(body.span))

    def _for(self) -> ast.ForStmt:
        for_token = self._advance()
        var = self._expect_ident("after 'for'")
        self._expect(TokenKind.IN, "after loop variable")
        start = self._expression()
        self._expect(TokenKind.DOTDOT, "in range (write 'start..end')")
        end = self._expression()
        body = self._block()
        return ast.ForStmt(var.text, start, end, body, span=for_token.span.cover(body.span))

    def _return(self) -> ast.ReturnStmt:
        return_token = self._advance()
        value = None if self._check(TokenKind.SEMICOLON) else self._expression()
        self._expect(TokenKind.SEMICOLON, "after return statement")
        return ast.ReturnStmt(value, span=return_token.span.cover(self.previous.span))

    def _expression_statement(self) -> ast.Stmt:
        expr = self._expression()
        if self._match(TokenKind.ASSIGN):
            if not isinstance(expr, ast.Name | ast.Index):
                raise self._error(
                    "invalid assignment target",
                    expr.span,
                    "only variables and array elements can be assigned",
                )
            value = self._expression()
            self._expect(TokenKind.SEMICOLON, "after assignment")
            return ast.AssignStmt(expr, value, span=expr.span.cover(self.previous.span))
        self._expect(TokenKind.SEMICOLON, "after expression")
        return ast.ExprStmt(expr, span=expr.span.cover(self.previous.span))

    # ================================================================== expressions (Pratt)

    def _expression(self, min_precedence: Precedence = Precedence.LOWEST) -> ast.Expr:
        """Parse an expression whose operators all bind at least as tightly as ``min_precedence``.

        Loop invariant: ``left`` is a complete expression. Each iteration either
        extends it with an operator of precedence >= ``min_precedence`` or stops.
        Parsing the right operand with ``precedence + 1`` makes operators
        left-associative: in ``a - b - c`` the inner call refuses the second
        ``-``, so it attaches to the outer ``(a - b)``.
        """
        left = self._unary()
        last_non_assoc: Precedence | None = None
        while True:
            token = self.current
            if token.kind is TokenKind.AS:
                if min_precedence > Precedence.CAST:
                    break
                self._advance()
                target = self._type()
                left = ast.Cast(left, target, span=left.span.cover(self.previous.span))
                continue

            op = BINARY_OPERATORS.get(token.kind)
            if op is None or op.precedence < min_precedence:
                break
            if op.precedence in NON_ASSOCIATIVE and last_non_assoc == op.precedence:
                raise self._error(
                    "comparison operators cannot be chained",
                    token.span,
                    "use parentheses or '&&', e.g. 'a < b && b < c'",
                )
            self._advance()
            right = self._expression(Precedence(op.precedence + 1))
            left = ast.Binary(op, left, right, span=left.span.cover(right.span))
            if op.precedence in NON_ASSOCIATIVE:
                last_non_assoc = op.precedence
        return left

    def _unary(self) -> ast.Expr:
        op = UNARY_OPERATORS.get(self.current.kind)
        if op is not None:
            op_token = self._advance()
            operand = self._unary()
            return ast.Unary(op, operand, span=op_token.span.cover(operand.span))
        return self._postfix(self._primary())

    def _postfix(self, expr: ast.Expr) -> ast.Expr:
        while self._match(TokenKind.LBRACKET):
            index = self._expression()
            self._expect(TokenKind.RBRACKET, "to close the index")
            expr = ast.Index(expr, index, span=expr.span.cover(self.previous.span))
        return expr

    def _primary(self) -> ast.Expr:
        token = self.current
        kind = token.kind
        if kind is TokenKind.INT:
            self._advance()
            assert isinstance(token.value, int)
            return ast.IntLiteral(token.value, span=token.span)
        if kind is TokenKind.FLOAT:
            self._advance()
            assert isinstance(token.value, float)
            return ast.FloatLiteral(token.value, span=token.span)
        if kind in (TokenKind.TRUE, TokenKind.FALSE):
            self._advance()
            return ast.BoolLiteral(kind is TokenKind.TRUE, span=token.span)
        if kind is TokenKind.IDENT:
            self._advance()
            if self._match(TokenKind.LPAREN):
                args = self._arguments()
                return ast.Call(token.text, args, span=token.span.cover(self.previous.span))
            return ast.Name(token.text, span=token.span)
        if kind is TokenKind.LPAREN:
            self._advance()
            inner = self._expression()
            self._expect(TokenKind.RPAREN, "to close the parenthesized expression")
            return inner
        if kind is TokenKind.LBRACKET:
            self._advance()
            elements = self._comma_list(TokenKind.RBRACKET, "array literal")
            return ast.ArrayLiteral(elements, span=token.span.cover(self.previous.span))
        raise self._error(f"expected an expression, found {token.describe()}", token.span)

    def _arguments(self) -> list[ast.Expr]:
        return self._comma_list(TokenKind.RPAREN, "argument list")

    def _comma_list(self, closer: TokenKind, what: str) -> list[ast.Expr]:
        """Parse ``expr, expr, ... [,] closer`` (the opener is already consumed)."""
        items: list[ast.Expr] = []
        while not self._check(closer):
            items.append(self._expression())
            if not self._match(TokenKind.COMMA):
                break
        self._expect(closer, f"to close the {what}")
        return items

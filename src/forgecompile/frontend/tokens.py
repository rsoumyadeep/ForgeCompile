"""Token kinds and the Token record produced by the lexer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from forgecompile.diagnostics import Span


class TokenKind(Enum):
    # Literals and names
    INT = "integer literal"
    FLOAT = "float literal"
    IDENT = "identifier"

    # Keywords
    FN = "fn"
    LET = "let"
    IF = "if"
    ELSE = "else"
    WHILE = "while"
    FOR = "for"
    IN = "in"
    RETURN = "return"
    BREAK = "break"
    CONTINUE = "continue"
    TRUE = "true"
    FALSE = "false"
    AS = "as"
    INT_TYPE = "int"
    FLOAT_TYPE = "float"
    BOOL_TYPE = "bool"

    # Operators
    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    SLASH = "/"
    PERCENT = "%"
    ASSIGN = "="
    EQ = "=="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    AND = "&&"
    OR = "||"
    NOT = "!"
    ARROW = "->"
    DOTDOT = ".."

    # Punctuation
    LPAREN = "("
    RPAREN = ")"
    LBRACE = "{"
    RBRACE = "}"
    LBRACKET = "["
    RBRACKET = "]"
    COMMA = ","
    SEMICOLON = ";"
    COLON = ":"

    EOF = "end of file"

    def describe(self) -> str:
        """Human-readable description for error messages: ``';'``, ``identifier``, ..."""
        if self in (TokenKind.INT, TokenKind.FLOAT, TokenKind.IDENT, TokenKind.EOF):
            return self.value
        return f"'{self.value}'"


KEYWORDS: dict[str, TokenKind] = {
    kind.value: kind
    for kind in (
        TokenKind.FN,
        TokenKind.LET,
        TokenKind.IF,
        TokenKind.ELSE,
        TokenKind.WHILE,
        TokenKind.FOR,
        TokenKind.IN,
        TokenKind.RETURN,
        TokenKind.BREAK,
        TokenKind.CONTINUE,
        TokenKind.TRUE,
        TokenKind.FALSE,
        TokenKind.AS,
        TokenKind.INT_TYPE,
        TokenKind.FLOAT_TYPE,
        TokenKind.BOOL_TYPE,
    )
}

# Operators/punctuation ordered longest-first so that maximal munch works:
# "<=" must be tried before "<", ".." before any single-character token.
SYMBOLS: list[tuple[str, TokenKind]] = sorted(
    (
        (kind.value, kind)
        for kind in TokenKind
        if kind.name not in {"INT", "FLOAT", "IDENT", "EOF"} and kind not in KEYWORDS.values()
    ),
    key=lambda pair: -len(pair[0]),
)


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str
    span: Span
    value: int | float | None = None  # parsed value of INT/FLOAT literals

    def describe(self) -> str:
        if self.kind in (TokenKind.INT, TokenKind.FLOAT, TokenKind.IDENT):
            return f"{self.kind.value} '{self.text}'"
        return self.kind.describe()

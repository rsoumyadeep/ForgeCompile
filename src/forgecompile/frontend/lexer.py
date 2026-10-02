"""Hand-written lexer for MiniLang.

The lexer turns characters into tokens. It discards whitespace and comments,
recognizes keywords and literals, and records a source span for every token.

Design notes:

* **Maximal munch:** at each position the longest matching token wins, so
  ``<=`` is one token, not ``<`` followed by ``=``.
* **Number literals:** a ``.`` belongs to a float literal only when a digit
  follows it. This keeps ``0..10`` lexing as ``0`` ``..`` ``10``.
* **Error recovery:** an invalid character produces a diagnostic and is
  skipped, so one stray character does not hide later errors.

Runs in O(n) time over the input characters.
"""

from __future__ import annotations

from forgecompile.diagnostics import Diagnostic, SourceFile
from forgecompile.frontend.tokens import KEYWORDS, SYMBOLS, Token, TokenKind

INT64_MAX = 2**63 - 1


# MiniLang source is ASCII-only for names and numbers. str.isdigit()/isalpha()
# would also accept Unicode characters such as '²', which int() then rejects.
def _is_digit(ch: str) -> bool:
    return ch != "" and "0" <= ch <= "9"


def _is_ident_start(ch: str) -> bool:
    return ch != "" and (("a" <= ch <= "z") or ("A" <= ch <= "Z") or ch == "_")


def _is_ident_char(ch: str) -> bool:
    return _is_ident_start(ch) or _is_digit(ch)


class Lexer:
    def __init__(self, source: SourceFile) -> None:
        self.source = source
        self.text = source.text
        self.pos = 0
        self.tokens: list[Token] = []
        self.diagnostics: list[Diagnostic] = []

    # ------------------------------------------------------------------ helpers

    def _peek(self, offset: int = 0) -> str:
        index = self.pos + offset
        return self.text[index] if index < len(self.text) else ""

    def _error(self, message: str, start: int, end: int, *notes: str) -> None:
        self.diagnostics.append(Diagnostic.error(message, self.source.span(start, end), *notes))

    def _emit(self, kind: TokenKind, start: int, value: int | float | None = None) -> None:
        span = self.source.span(start, self.pos)
        self.tokens.append(Token(kind, self.text[start : self.pos], span, value))

    # ------------------------------------------------------------------ scanning

    def tokenize(self) -> list[Token]:
        while True:
            self._skip_trivia()
            if self.pos >= len(self.text):
                break
            ch = self._peek()
            if _is_digit(ch):
                self._number()
            elif _is_ident_start(ch):
                self._identifier()
            else:
                self._symbol()
        self.tokens.append(Token(TokenKind.EOF, "", self.source.span(self.pos, self.pos)))
        return self.tokens

    def _skip_trivia(self) -> None:
        """Skip whitespace, ``// line`` comments and ``/* block */`` comments."""
        while self.pos < len(self.text):
            ch = self._peek()
            if ch in " \t\r\n":
                self.pos += 1
            elif ch == "/" and self._peek(1) == "/":
                newline = self.text.find("\n", self.pos)
                self.pos = len(self.text) if newline == -1 else newline + 1
            elif ch == "/" and self._peek(1) == "*":
                close = self.text.find("*/", self.pos + 2)
                if close == -1:
                    self._error("unterminated block comment", self.pos, self.pos + 2)
                    self.pos = len(self.text)
                else:
                    self.pos = close + 2
            else:
                return

    def _digits(self) -> None:
        while _is_digit(self._peek()):
            self.pos += 1

    def _number(self) -> None:
        start = self.pos
        self._digits()
        is_float = False
        if self._peek() == "." and _is_digit(self._peek(1)):
            is_float = True
            self.pos += 1
            self._digits()
        if self._peek() in ("e", "E"):
            sign = 1 if self._peek(1) in ("+", "-") else 0
            if _is_digit(self._peek(1 + sign)):
                is_float = True
                self.pos += 1 + sign
                self._digits()
        text = self.text[start : self.pos]
        if is_float:
            self._emit(TokenKind.FLOAT, start, float(text))
            return
        value = int(text)
        if value > INT64_MAX:
            self._error(
                f"integer literal {text} does not fit in a 64-bit int",
                start,
                self.pos,
                f"the largest int is {INT64_MAX}",
            )
            value = 0
        self._emit(TokenKind.INT, start, value)

    def _identifier(self) -> None:
        start = self.pos
        while _is_ident_char(self._peek()):
            self.pos += 1
        word = self.text[start : self.pos]
        self._emit(KEYWORDS.get(word, TokenKind.IDENT), start)

    def _symbol(self) -> None:
        start = self.pos
        for spelling, kind in SYMBOLS:
            if self.text.startswith(spelling, self.pos):
                self.pos += len(spelling)
                self._emit(kind, start)
                return
        ch = self._peek()
        self.pos += 1
        if ch in "&|":
            self._error(
                f"unexpected character '{ch}'", start, self.pos, f"did you mean '{ch * 2}'?"
            )
            # Recover by assuming the logical operator was meant; this avoids a
            # cascade of parser errors caused by the missing operator token.
            self._emit(TokenKind.AND if ch == "&" else TokenKind.OR, start)
        else:
            self._error(f"unexpected character {ch!r}", start, self.pos)


def tokenize(source: SourceFile) -> tuple[list[Token], list[Diagnostic]]:
    """Return the token list (always ending in EOF) and any lexical errors."""
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    return tokens, lexer.diagnostics

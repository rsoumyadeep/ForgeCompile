# Phase 1 Report — MiniLang Frontend

**PHASE:** 1 — MiniLang frontend (lexer, parser, AST)
**STATUS:** ✅ Complete (2026-10-02)

## Implemented
- **Language specification** (`docs/LANGUAGE.md`):
  - lexical rules, EBNF grammar and precedence table;
  - full static semantics (enforced in Phase 2) and dynamic semantics (Phases 3 and 5);
  - no undefined behaviour: wrapping ints, trapping division by zero, saturating casts,
    bounds checks.
- **Diagnostics** (`diagnostics.py`): `Span`, `SourceFile` (offset → line/col via bisect),
  `Diagnostic`, `CompileError` (carries *all* errors), and rustc-style rendering with a
  source excerpt and caret.
- **Lexer** (`frontend/lexer.py`, `tokens.py`):
  - maximal munch;
  - int and float literals (the `0..10` lookahead case, an int64 range check);
  - line and block comments;
  - ASCII-only identifiers;
  - error recovery (bad characters skipped; a lone `&`/`|` is recovered as `&&`/`||`).
- **AST** (`ast/nodes.py`, `types.py`, `operators.py`): dataclass nodes whose equality ignores
  spans. Language types (`int`, `float`, `bool`, nested `[T; N]`). A single precedence table.
- **Parser** (`frontend/parser.py`):
  - recursive descent for declarations and statements;
  - a Pratt loop for expressions, with non-associative comparisons;
  - `else if` desugaring;
  - assignment-target validation;
  - panic-mode recovery with brace-depth tracking, plus keyword-as-name recovery.
- **Printers:** `ast/dump.py` (indented tree, S-expressions) and `ast/formatter.py`
  (canonical source with minimal parentheses).
- **CLI:** `forgecompile lex FILE` and `forgecompile parse FILE [--format]`. Exit code 1 and
  rendered diagnostics on syntax errors. `CliError` handles missing or unreadable files.
- **Examples:** 7 programs in `examples/` (fibonacci, gcd, primes, bubble_sort, matmul,
  newton_sqrt, collatz) covering every language feature.

## Tests
164 total (139 new in `tests/frontend/`), all passing:
- `test_lexer.py`: keywords, maximal munch, literal values and types, the range-vs-float
  case, comments, spans (including CRLF), every lexical error, the Unicode digit trap.
- `test_parser.py`: function signatures, `let` forms, assignment targets, if/else-if
  desugaring, loops, blocks, calls, casts, spans, all examples.
- `test_precedence.py`: 25 precedence and associativity cases, chained-comparison rejection,
  deep nesting.
- `test_syntax_errors.py`: 19 single-error messages, error positions, multi-error recovery,
  regression tests for F-002, rendering.
- `test_roundtrip.py`: examples parse → format → parse (equality + idempotence); **1,000
  random expression trees** (20 seeds × 50) format → parse; minimal-parentheses checks.
- `test_frontend_cli.py`: AST dump, format round-trip through files, token listing, exit codes.

ruff and mypy are clean.

## Experiments
None. Not applicable to this phase.

## Results
Not applicable.

## Important decisions
D-009 hand-written recursive descent + Pratt · D-010 fully defined semantics · D-011 counted
`for` loops, arrays by reference · D-012 pytest importlib mode.

## Problems encountered → how they were solved
- **F-002:** recovery treated the `}` of a skipped block as the end of the function. Fixed
  with brace-depth tracking. Two error cascades were also removed (lone `&`, keyword as name).
- **F-003:** the random round-trip test found that the formatter dropped required parentheses
  in `(a != b) != c`. Fixed the non-associative rule.
- **F-004:** two wrong test expectations were corrected in the tests, not the code.
- A Unicode pitfall: `str.isdigit()` accepts `'²'`, which then crashes `int()`. It was caught
  in review before it shipped. The lexer now uses explicit ASCII checks, and a regression test
  was added.

## Known limitations
- Recovery is heuristic. Some inputs can still produce a follow-on error (for example, a
  dropped `@` in `1 @ 2` also causes "expected ';'").
- `-9223372036854775808` cannot be written as a literal (documented in LANGUAGE.md §1).
- Deeply nested expressions recurse in Python. 200 levels are tested. Several thousand levels
  would hit Python's recursion limit.
- `print` and most other rules are still only *syntax*. `1 + true` parses fine and is
  rejected in Phase 2.

## Files changed
`src/forgecompile/diagnostics.py`, `src/forgecompile/frontend/*`, `src/forgecompile/ast/*`,
`src/forgecompile/cli/{main,common,frontend_commands}.py`, `tests/frontend/*`,
`examples/*.mini`, `examples/README.md`, `pyproject.toml` (pytest import mode), and docs:
`LANGUAGE.md`, `THEORY.md` §2–4, `HOW_TO_STUDY.md` §2–4, `DECISIONS.md` (D-009–D-012),
`FAILURES.md` (F-002–F-004), `ARCHITECTURE.md`, `ROADMAP.md`, `HOW_TO_RUN.md`, `README.md`.

## Commit
`phase-1: implement MiniLang lexer, parser, AST and diagnostics`

## Next phase
Phase 2: semantic analysis (symbol tables, scopes, type checking, function and return-path
checks, `forgecompile check`).

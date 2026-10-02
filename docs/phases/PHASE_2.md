# Phase 2 Report — Semantic Analysis

**PHASE:** 2 — Semantic analysis
**STATUS:** ✅ Complete (2026-10-02)

## Implemented
- **Symbols and scopes** (`semantic/symbols.py`):
  - `VariableSymbol` (identity equality plus a `uid`; kinds local, parameter and loop
    variable; loop variables are immutable);
  - `FunctionSymbol`;
  - `Scope` chain with shadowing and redeclaration detection.
- **Type checker** (`semantic/checker.py`):
  - two passes (signatures, then bodies), which supports forward calls and mutual recursion;
  - every rule in LANGUAGE.md §5–6, plus a compile-time literal-index bounds check (D-015);
  - `print` as a built-in;
  - `main` signature check;
  - an `ERROR` type for cascade suppression (D-014);
  - "did you mean" suggestions via `difflib`;
  - notes that explain the no-implicit-conversion rule.
- **Return-path analysis** (`semantic/control_flow.py`): conservative "completes normally"
  rules. `while true` without a targeted `break` counts as non-terminating, and breaks in
  nested loops are attributed to the right loop.
- **In-place annotation** (D-013): `Expr.ty`, `Name.symbol`, `Call.function`,
  `LetStmt/ForStmt/Param.symbol`, `FunctionDecl.symbol`.
- **Driver** (`driver.py`): `check_source(text) -> CheckedProgram(ast, info)`.
- **CLI:** `forgecompile check FILE [--dump]` (the dump shows each expression's type).

## Tests
280 total (116 new in `tests/semantic/`), all passing:
- `test_semantic_errors.py`: 9 program-level, 20 statement-level and 28 expression-level
  diagnostics. Each one is a complete program that must yield **exactly one** error, so every
  case also tests cascade suppression. Further tests cover notes, multi-error reporting, and
  scope exit.
- `test_checker.py`: all examples type-check with every expression annotated; expression
  types; distinct symbols under shadowing; `let x = x + 1`; mutual recursion; array rows
  passed by reference; symbol kinds; always-return patterns; all scalar casts.
- `test_control_flow.py`: 17 cases of the completes-normally analysis.
- `test_check_cli.py`: ok, dump, semantic errors, and syntax errors stopping before semantics.

Mutation testing found that all 4 injected checker bugs were detected (FAILURES F-005).

## Experiments
None. Not applicable to this phase.

## Results
Not applicable.

## Important decisions
D-013 in-place annotation and symbol identity · D-014 error type · D-015 compile-time
literal-index bounds check.

## Problems encountered → how they were solved
- **F-005:** the mutation-testing script silently failed to apply one mutation after
  `ruff format` re-wrapped the target line. This was detected, the mutation re-applied, and
  the mutant was caught.
- Ruff E501 on test tables with exact expected messages: relaxed E501 for `tests/**` only
  (`pyproject.toml`).

## Known limitations
- The missing-return check is conservative (only `while true` is treated as infinite).
- No warnings yet (unused variables, unreachable code after `return`). Code after a `return`
  is silently accepted.
- No compile-time evaluation of constant expressions beyond literal indices. For example,
  `a[1 + 4]` on `[int; 3]` is only caught at run time.

## Files changed
`src/forgecompile/semantic/{__init__,symbols,checker,control_flow}.py`, `driver.py`,
`ast/nodes.py` (annotation fields), `ast/types.py` (`ERROR`),
`cli/{main,frontend_commands}.py`, `tests/semantic/*`, `pyproject.toml`, and docs:
`LANGUAGE.md`, `THEORY.md` §5, `HOW_TO_STUDY.md` §5, `DECISIONS.md` (D-013–D-015),
`FAILURES.md` (F-005), `ARCHITECTURE.md`, `ROADMAP.md`, `HOW_TO_RUN.md`, `README.md`.

## Commit
`phase-2: implement semantic analysis (scopes, type checking, return paths)`

## Next phase
Phase 3: IR design, AST → IR lowering, the reference interpreter (with dynamic instruction
counts), CFG utilities, dominators, and SSA construction and destruction.

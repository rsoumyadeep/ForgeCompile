# Failure Log

Meaningful failures, wrong turns and debugging discoveries, recorded as they happen. Entries
are never deleted or rewritten to look better. A fix that later turns out wrong gets a
follow-up entry.

Template:

```
## F-NNN — <short title>
- Date / Phase:
- Attempted:            what was being done
- Why:                  motivation
- Symptom:              observed failure / error text
- Root cause:
- Debugging process:
- Fix:
- Fix worked?:
- Lesson:
```

---

## F-001 — `uv sync` failed: hatchling requires README before first build

- **Date / Phase:** 2026-10-02, Phase 0
- **Attempted:** Running `uv sync` right after writing `pyproject.toml` and the package
  sources, before writing any documentation.
- **Symptom:** `OSError: Readme file does not exist: README.md` raised from
  `hatchling/metadata/core.py` while building the editable install.
- **Root cause:** `pyproject.toml` declares `readme = "README.md"`. Hatchling validates
  metadata fields eagerly when it builds the package, so a missing readme is fatal.
- **Fix:** Wrote `README.md` (planned anyway) and re-ran `uv sync`.
- **Fix worked?:** Yes.
- **Lesson:** Package metadata files are build inputs. Order scaffolding so that every file
  referenced by `pyproject.toml` exists before the first install.

## F-002 — Parser error recovery closed the enclosing function early

- **Date / Phase:** 2026-10-02, Phase 1
- **Attempted:** Panic-mode recovery. After a syntax error, skip tokens until `;`, `}` or a
  statement keyword.
- **Symptom:** For the input
  ```
  fn main() -> int {
      if a < b < c { }
      3 = x;
      let let = 2;
      ...
  ```
  the parser reported the chained-comparison error correctly, followed by the spurious
  `expected 'fn' at top level, found integer literal '3'`. The real error in `let let = 2;`
  was never reported.
- **Root cause:** The skip loop stopped at the first `}` it met, which was the `}` of the
  `if` body being skipped. The block parser took that `}` as the end of `main`. Everything
  after it was then parsed as top-level code.
- **Debugging process:** Ran the CLI on a hand-written file with six known errors and compared
  the reported errors against the expected list. The first wrong message was at top level,
  which pointed to a brace imbalance in recovery.
- **Fix:** `_synchronize` now tracks brace depth. A `{ ... }` group inside the broken
  statement is skipped as a unit, and only a `}` at depth 0 stops the skip. In the same pass,
  two further cascades were removed. A lone `&` or `|` is now lexed as `&&` or `||` after the
  error is reported, and a keyword used as a name (`let let`) is reported and then accepted
  as the name.
- **Fix worked?:** Yes. The six-error file now reports exactly its six errors. Regression
  tests: `test_recovery_skips_nested_braces_in_broken_statement`,
  `test_keyword_as_name_has_hint_and_no_cascade`,
  `test_single_ampersand_suggests_double_and_recovers`.
- **Lesson:** Recovery code needs adversarial tests just like the happy path. Check
  diagnostics against an expected list rather than "it reported something".

## F-003 — Formatter dropped required parentheses around non-associative operators

- **Date / Phase:** 2026-10-02, Phase 1
- **Attempted:** Minimal-parentheses formatting. A left operand gets parentheses only if it
  binds *more loosely* than its parent operator.
- **Symptom:** The randomized round-trip test failed on its very first seed. The tree
  `(3e20 != a) != false` was printed as `3.0e+20 != a != false`, which the parser (correctly)
  rejects with "comparison operators cannot be chained".
- **Root cause:** The rule "left operand needs parentheses iff its precedence < parent's" is
  only right for *left-associative* operators. For non-associative ones (comparisons), a
  left operand at the *same* level also needs parentheses.
- **Fix:** For operators of a non-associative level, the left operand is parenthesized when
  its precedence is `<=` the parent's.
- **Fix worked?:** Yes. All 1,000 random trees (20 seeds × 50) round-trip.
- **Lesson:** Property-based tests over generated inputs found a case that the hand-written
  precedence tests missed. Nobody thinks to write `(a != b) != c` by hand.

## F-004 — Two wrong test expectations (not code bugs)

- **Date / Phase:** 2026-10-02, Phase 1
- **Symptom:** Two new tests failed after the F-003 fix.
  1. The test expected `(a < b) == c` to be formatted with parentheses. The formatter
     produced `a < b == c`.
  2. The test expected the lexer error for `1 @ 2` to be reported before the parser's
     "expected ';'" error.
- **Root cause:** Both expectations were wrong.
  1. `<` binds tighter than `==`, so `a < b == c` *is* the minimal form, as the formatter's
     docstring states.
  2. The parser error is located just *after* `1` (column 10), which comes before `@`
     (column 11). Sorting by source position is correct.
- **Fix:** Corrected the tests, not the code. Test (2) now asserts the property (sorted
  offsets) rather than a hard-coded order.
- **Lesson:** When a test fails, first decide which side is wrong. Changing code to satisfy a
  wrong test would have broken the minimal-parentheses contract.

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

## F-005 — A mutation-testing step silently did nothing

- **Date / Phase:** 2026-10-02, Phase 2
- **Attempted:** All 116 new semantic tests passed on their first run. A suite that never
  fails may be vacuous, so I checked it by *mutation testing*: inject a bug into
  `checker.py`, confirm that some test fails, then restore the file.
- **Symptom:** The mutation "disable the missing-return check" reported `116 passed`, which
  looked like a gap in the tests.
- **Root cause:** The mutation was a text substitution, and its search string no longer
  matched: `ruff format` had re-wrapped that line. The file was never changed, so the
  "surviving mutant" was an artifact of the script.
- **Fix:** The script reports `NO-CHANGE` when a substitution does not apply. I re-applied
  the mutation against the current text, and 2 tests failed as expected. All four mutations
  were caught:
  - loop-variable mutability → 1 failure;
  - missing return → 2;
  - declaration of `let` symbols → 36;
  - error-type cascade suppression → 3.
- **Fix worked?:** Yes. `checker.py` was restored from a backup and verified with `git diff`.
- **Lesson:** A test of the tests needs its own sanity check. Verify that the mutation was
  actually applied before interpreting a "pass".

## F-006 — The spec and the reference interpreter disagreed on assignment evaluation order

- **Date / Phase:** 2026-10-02, Phase 3
- **Attempted:** Designing the lowering of `a[e1] = e2`.
- **Symptom:** No test failed. While writing the lowering, I noticed that LANGUAGE.md said
  "left to right", but the AST interpreter evaluated `e2` *before* `e1` and before the bounds
  check. The difference is observable: in `a[f()] = g()`, both functions may print, and the
  index may trap before or after `g` runs.
- **Root cause:** The spec was underspecified for assignments, and the interpreter followed
  the most convenient order.
- **Fix:**
  - The spec now says that the target's indices are evaluated and bounds-checked before the
    right-hand side (LANGUAGE.md §7).
  - The AST interpreter and the lowering both follow that order.
  - Regression tests: `test_left_to_right_evaluation_order`,
    `test_assignment_target_checked_before_rhs`, `test_store_value_evaluated_after_target_index`.
- **Lesson:** Two implementations of the same semantics only make useful oracles if the spec
  pins down *every* observable choice. Writing a second implementation is a good way to find
  underspecification.

## F-007 — The generator's "unsafe index" case was rejected at compile time

- **Date / Phase:** 2026-10-02, Phase 3
- **Symptom:** `CompileError: index 10 is out of bounds for an array of length 1` while
  type-checking a generated program.
- **Root cause:** The deliberately unsafe index path emitted an integer *literal*, which the
  type checker rejects statically (D-015). The generator is supposed to always produce
  well-typed programs.
- **Fix:** The unsafe path wraps the index as `e + 0`, which is not a literal, so the trap
  happens at *run time* as intended. 200 generated programs are type-checked in every test
  run (`test_generated_programs_type_check`).
- **Lesson:** Static and dynamic checks interact. A generator must know which errors the
  front end catches early.

## F-008 — Four failing tests, three of them caused by my own wrong premises

- **Date / Phase:** 2026-10-02, Phase 3
- **Symptom:** 4 of 549 tests failed on the first full run.
- **Analysis, one by one:**
  1. *`test_row_argument_uses_ptradd`* (wrong test). I expected lowering to recognise that
     `m[0]` has offset 0. Lowering is deliberately naive and emits `mul 0, 4` plus `ptradd`.
     The test now asserts that behaviour, and constant folding (Phase 4) will remove it.
  2. *SSA undef test* (wrong premise). I assumed a loop-local `let v = i*10` used in another
     block would get an undef phi. It has only *one* static definition, which dominates all
     uses, so it needs no phi at all. I rewrote the test with a genuinely multi-assigned
     loop-local variable, which does produce an `undef` header phi, and added a test for the
     single-assignment case.
  3. *Verifier test "ret in the middle"* (real tooling bug). The IR parser used
     `BasicBlock.append`, which refuses a second terminator, so malformed IR could not even
     be constructed for the verifier to reject. The parser now inserts without checking, and
     validation belongs to the verifier.
  4. *`format_float(5e-7)`* (wrong expectation). I claimed `5e-7` rounds up to `0.000001`.
     Its exact binary value is `4.99999999999999977e-07`, below the halfway point, so `%.6f`
     correctly prints `0.000000`. The test now uses both `5e-7 → 0.000000` and
     `1.5e-6 → 0.000002`, with the exact values verified using `decimal.Decimal`.
- **Lesson:** Of 4 failures, only one was a code problem. Reading every failure before
  "fixing" it prevented three bad code changes. Item 4 is directly relevant to Phase 5:
  native `printf` must match Python's correctly rounded formatting.

## F-009 — copyprop broke the SSA dominance property (caught by the verifier)

- **Date / Phase:** 2026-10-02, Phase 4
- **Attempted:** Trivial-phi elimination in copyprop: replace `%x = phi [...]` by `v` when all
  inputs are `v`, ignoring `undef` inputs and self-references.
- **Symptom:** On the first differential run, 10 of 157 programs failed under copyprop alone
  with `IR invalid after pass 'copyprop': definition of %or.2.6 does not dominate its use`.
  The other six passes were clean.
- **Root cause:** For `%x = phi [undef, entry], [%v, latch]` the helper returned `%v`.
  Ignoring undef is a legal *value* refinement, but `%v` is defined inside the loop and does
  not dominate the header. My dominance argument ("v reaches every edge, so it dominates the
  phi") silently assumed every input was `%v`. Constant-folding callers were unaffected,
  because constants dominate everything.
- **Debugging process:** The verifier named the pass and the offending register. Printing
  one failing function showed the undef-plus-loop-value phi shape. The bug followed directly
  from comparing that shape against the dominance argument in the docstring.
- **Fix:** `trivial_phi_value` may ignore undef inputs only when the unique value is a
  constant. Regression test: `test_copyprop_keeps_phi_with_undef_and_loop_value`. The
  mutation test that re-introduces the bug is caught.
- **Fix worked?:** Yes. 0 failures in 307 programs × 11 passes plus 921 random orderings.
- **Lesson:** "Same value" and "valid replacement" are different claims in SSA. The second
  needs dominance. Verifying after every pass is what made this a 5-minute fix instead of a
  mystery wrong output weeks later.

## F-010 — SCCP kept dead divisions and constant bounds checks (found by an experiment)

- **Date / Phase:** 2026-10-02, Phase 4
- **Symptom:** EXP-001 run 1 showed `constfold` beating `sccp` on generated programs (cost
  0.627 vs 0.712), even though SCCP finds a superset of constant registers. No test failed:
  the output was correct, just less optimized.
- **Debugging process:** Summed the per-opcode dynamic counts of sccp minus constfold over 200
  programs: +393 `srem`, +337 `sdiv`, +333 `boundscheck`.
- **Root cause:**
  1. The rewrite decided `is_removable_if_unused` *before* substituting constants. A division
     whose divisor was a register *known* to be 7 still looked like "divide by a register
     that might be zero", so it was kept even though its result was unused.
  2. SCCP never folded in-range constant bounds checks (constfold did).
- **Fix:** Substitute first, then delete; fold constant bounds checks. Regression test:
  `test_sccp_deletes_dead_division_and_constant_bounds_check`.
- **Fix worked?:** Yes. In EXP-001 run 2, sccp reaches 0.622 (now ≤ constfold). Only sccp's rows
  changed between the runs, which was verified programmatically.
- **Lesson:** Missed optimizations are invisible to correctness testing. Measuring passes
  against each other, and taking an "impossible" ranking seriously, found it. Run 1's results
  are kept in the repository.

## F-011 — Two documentation/infrastructure errors caught before commit

- **Date / Phase:** 2026-10-02, Phase 4
1. **An unsupported claim in OPTIMIZATIONS.md.** I wrote that running `strength` before `bce`
   removes fewer bounds checks, and labelled it "measured, EXP-001". It was not measured: I
   had inferred it from one example. Measuring it on all 7 examples showed **no difference**
   between the two orders, and reasoning confirmed bce cannot handle `a[4*i]` in either
   order. The claim was deleted. *Lesson: every quantitative statement in the docs needs a
   pointer to data; check before labelling something "measured".*
2. **Curated experiment metadata said `"status": "running"`.** `run.py` copied the metadata
   before calling `finalize()`. Fixed the ordering, and restored the curated copies from the
   run directories' final `metadata.json` (status `completed`, clean commits `6f13055` and
   `453feab`). Experiment outputs are now also forced to LF line endings on Windows.

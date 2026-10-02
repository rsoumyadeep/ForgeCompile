# Phase 4 Report — Classical Optimization Engine

**PHASE:** 4 — Classical optimization engine
**STATUS:** ✅ Complete (2026-10-02)

## Implemented
- **Framework** (`optimization/pass_manager.py`):
  - `Pass` / `FunctionPass`, plus a `@register_pass` registry;
  - a `PassManager` that verifies SSA after every pass and records per-pass statistics
    (changed, static size before/after, time, counters);
  - presets O0/O1/O2; pipelines given as comma lists or files.
- **Shared semantics** (`ir/evaluate.py`): one evaluator for the interpreter and the
  constant folder (D-022).
- **Utilities** (`optimization/utils.py`): batched substitution, `fold`, trivial-phi detection
  (dominance-safe after F-009), removability and speculatability predicates, and phi-safe CFG
  edits.
- **Loop analysis** (`analysis/loops.py`): natural loops, nesting, preheader insertion, basic
  induction variables.
- **11 passes:** constfold, sccp, copyprop, dce, simplify, simplifycfg, cse, licm, strength,
  bce, inline.
- **CLI:** `forgecompile opt [--passes | -O N] [--stats]`, `forgecompile passes`,
  `forgecompile run -O N / --passes`.
- **Tooling:** `scripts/fuzz_passes.py`, a differential fuzzer that runs single passes and
  random orderings.
- **EXP-001:** pre-registered, run twice (before and after the F-010 fix), with results and
  interpretation in EXPERIMENTS.md and RESULTS.md.

## Tests
670 total (122 new in `tests/optimization/`), all passing:
- IR-text unit tests for every pass, including **negative** cases:
  - no folding of `sdiv 1, 0`;
  - an out-of-range constant `boundscheck` is kept;
  - unsafe IEEE identities are rejected;
  - no CSE across sibling branches or of loads;
  - LICM does not hoist possibly-trapping divisions out of a zero-trip loop;
  - BCE keeps checks that can fail;
  - strength reduction skips conditional multiplies;
  - recursive functions are not inlined.
- Pass-manager tests: registry, pipeline parsing, statistics, and the verifier naming a broken
  pass.
- Differential tests: every preset on every example against golden outputs; each pass alone on
  25 generated programs; random orderings on generated programs and on the examples.
- Fuzzing at scale: `scripts/fuzz_passes.py` with 307 programs × 11 passes plus 921 random
  sequences (two independent seed batches) gives **0 failures**.
- **Mutation testing:** 5 injected optimizer bugs were all caught:
  - an F-009 regression;
  - the `x + 0.0` identity;
  - DCE deleting a trapping division;
  - a BCE off-by-one;
  - LICM ignoring speculation safety.

## Experiments
EXP-001 (per-pass effects on IR-level work), with 2 runs on clean commits.

## Results
See RESULTS.md. Headline numbers (geometric mean of cost ratios): O2 gives 0.828 on the
examples and 0.537 on generated programs. Negative results:
- LICM worst case 1.87× worse (zero-trip-loop speculation);
- inline grows static code size 1.52× on the examples;
- bce and strength have zero effect without a preceding copyprop.

## Important decisions
D-021 pass framework · D-022 shared evaluator · D-023 loop passes assume canonical IR ·
D-024 speculative LICM kept, with its downside measured · D-025 inlining threshold.

## Problems encountered → how they were solved
- **F-009:** copyprop broke SSA dominance via an `undef` phi input. The verifier caught it on
  the first run; fixed, with a regression test and a mutation check.
- **F-010:** SCCP missed dead divisions and constant bounds checks. Found by EXP-001's
  "impossible" ranking (constfold > sccp); fixed and re-run, with run 1 kept.
- **F-011:** an unsupported "measured" claim in OPTIMIZATIONS.md (strength/bce ordering),
  disproved by measuring and removed; curated metadata copied before `finalize()`, fixed.
- Three wrong test expectations: the smallest loop was not the inner loop; the hoisted
  `n*3` was forgotten in a multiply count; a label was matched in a `br` operand. The tests
  were fixed, not the code.
- Tooling: bash heredocs mangling backslashes. From now on, multi-line edits go through
  scripts written with the Write tool, or through direct edits.

## Known limitations
- Metrics are interpreter-based. Native validation comes in Phase 6.
- No alias analysis, so loads are neither CSE'd nor hoisted.
- No loop unrolling, no loop rotation, and no dead-store elimination.
- BCE handles only plain-IV indices. Strength reduction handles only `iv * constant`.
- Inlining has no global code-growth bound.
- The presets are hand-picked, not tuned.

## Files changed
New: `ir/evaluate.py`, `analysis/loops.py`, `optimization/{__init__,pass_manager,utils}.py`,
`optimization/passes/*.py` (11 passes), `scripts/fuzz_passes.py`,
`experiments/EXP-001-pass-effects/*`, `tests/optimization/*`.
Modified: `ir/interpreter.py` (shared evaluator), `cli/ir_commands.py`, `cli/main.py`,
`utils/experiment.py` (LF outputs), and docs: `OPTIMIZATIONS.md` (written), `EXPERIMENTS.md`,
`RESULTS.md`, `THEORY.md` §9–10, `HOW_TO_STUDY.md` §9–10, `DECISIONS.md` (D-021–D-025),
`FAILURES.md` (F-009–F-011), `ARCHITECTURE.md`, `ROADMAP.md`, `HOW_TO_RUN.md`, `README.md`.

## Commits
- `6f13055 phase-4: add pass framework and classical optimization passes`
- `453feab phase-4: fix SCCP keeping dead divisions and constant bounds checks (found by EXP-001)`
- `phase-4: EXP-001 results, OPTIMIZATIONS.md and phase documentation` (this commit)

## Next phase
Phase 5: the LLVM backend. ForgeCompile IR → LLVM IR text (llvmlite parsing and verification),
with runtime support for traps, `print` and the `%.6f` formatting rules. Native executables via
`zig cc`. Differential tests: interpreter vs native. LLVM `-O0..-O3` as a comparison baseline.

# Phase 3 Report — IR, Reference Interpreters, CFG, Dominators, SSA

**PHASE:** 3 — Intermediate representation
**STATUS:** ✅ Complete (2026-10-02)

## Implemented
- **Runtime semantics** (`runtime/semantics.py`): wrap-around ints, C division and remainder,
  IEEE float division and fmod, saturating float→int, `%.6f` printing, exit status.
- **Reference AST interpreter** (`runtime/ast_interpreter.py`): an independent oracle that
  transcribes LANGUAGE.md §7 (D-019).
- **IR core** (`ir/values.py`, `instructions.py`, `function.py`):
  - typed registers, constants and `undef`;
  - about 30 opcodes, with effect classification (may-trap, memory, pure);
  - blocks, functions and modules; predecessors are computed, not stored.
- **Lowering** (`lowering.py`): AST → pre-SSA IR.
  - one register per source variable;
  - hoisted allocas, plus `memzero` at the declaration site;
  - flattened, per-dimension bounds-checked array indexing;
  - short-circuit control flow and counted-loop lowering;
  - unreachable-code removal.
- **Text format** (`ir/printer.py`, `ir/parser.py`): fully round-trippable.
- **Verifier** (`ir/verify.py`): structure, phis vs predecessors, types, call signatures; in
  SSA mode, single definition and dominance.
- **IR interpreter** (`ir/interpreter.py`):
  - explicit frame stack;
  - parallel phi semantics;
  - per-opcode counts and a weighted cost model (D-006);
  - internal-error detection for undef use, out-of-allocation memory access, and
    `unreachable`.
- **CFG utilities** (`analysis/cfg.py`): RPO, unreachable-block removal, critical-edge
  splitting.
- **Dominators** (`analysis/dominators.py`): Cooper–Harvey–Kennedy idoms, O(1) `dominates`,
  and dominance frontiers.
- **SSA construction** (`ir/ssa.py`): Cytron phi placement at iterated DFs, Briggs
  semi-pruning, and dominator-tree renaming (iterative).
- **Random program generator** (`testing/program_generator.py`): well-typed, terminating
  programs (D-020).
- **Driver/CLI:** `build_ir`; `forgecompile ir [--no-ssa]`;
  `forgecompile run [--engine ir|ir-nossa|ast] [--stats]`.
- **Golden outputs** for all 7 examples (`examples/*.expected`). These were derived
  independently (known mathematical values) and match all engines.

## Tests
549 total (269 new): `tests/runtime/`, `tests/ir/`, `tests/analysis/`, `tests/e2e/`. Highlights:
- Arithmetic helpers against hand-computed C/IEEE results, including the exact binary
  rounding of `%.6f`.
- Printer/parser round-trip on every example, pre- and post-SSA. The reparsed IR executes
  identically.
- 15 verifier error classes, each triggered by hand-written bad IR.
- Dominance checked against its *definition* on 40 random CFGs, including irreducible ones.
- SSA: textbook gcd form; semi-pruning; the genuine `undef` header-phi case is shown to be
  unobserved; idempotence.
- **Differential:** examples on 3 engines vs golden output; 60 generated programs per run, and
  940 more under `-m slow`. **Zero mismatches.** 7 of the first 300 generated programs trap,
  so trap behaviour is compared too.

ruff and mypy are clean.

## Experiments
None. (The cost model exists, but its validation is a Phase 6 experiment.)

## Results
Not applicable. Interpreter instruction counts for the examples exist (e.g. gcd: 100
instructions, cost 709), but they are not results of any experiment yet.

## Important decisions
D-016 register-based IR · D-017 SSA canonical, no out-of-SSA · D-018 flat arrays and explicit
bounds checks, traps as effects · D-019 independent AST oracle · D-020 program generator ·
D-006 update (cost model implemented, validation pending).

## Problems encountered → how they were solved
- **F-006:** the spec and the AST interpreter disagreed on assignment evaluation order.
  Found while designing the lowering. Spec pinned down, both implementations aligned,
  regression tests added.
- **F-007:** the generator's unsafe-index path produced compile-time-rejected literals. Fixed
  with `e + 0`.
- **F-008:** 4 test failures, 3 of them from my own wrong premises: naive `m[0]` lowering,
  single-definition variables needing no phi, and `5e-7` rounding down. The one real tooling
  bug was the parser refusing malformed IR.
- Tooling: Python edits passed through bash heredocs turned `\n` escapes into real newlines
  twice. These were fixed with direct file edits; it was not a project bug.

## Known limitations
- Lowering is deliberately naive (redundant copies, `mul 0, 4`). That is Phase 4's job.
- Some dead phis remain (semi-pruned SSA). DCE in Phase 4 removes them.
- No alias analysis. Array parameters may alias.
- The cost model weights are assumptions until validated in Phase 6.
- The IR interpreter is a Python loop with per-instruction dispatch, so large benchmarks will
  be slow. Benchmark sizes must account for that, or the interpreter must be optimized
  (Phase 6).
- Generated programs are small and constant-heavy (D-020). They are not representative of
  real code.

## Files changed
New: `runtime/{__init__,semantics,ast_interpreter}.py`, `ir/*`, `analysis/*`, `lowering.py`,
`testing/*`, `cli/ir_commands.py`, `tests/{runtime,ir,analysis,e2e}/*`, `tests/conftest.py`,
`examples/*.expected`.
Modified: `driver.py`, `cli/main.py`, and docs: `IR.md` (written), `LANGUAGE.md` (evaluation
order), `THEORY.md` §6–8, `HOW_TO_STUDY.md` §6–8, `DECISIONS.md` (D-016–D-020, D-006 update),
`FAILURES.md` (F-006–F-008), `ARCHITECTURE.md`, `ROADMAP.md`, `HOW_TO_RUN.md`, `README.md`.

## Commit
`phase-3: add IR, lowering, reference interpreters, dominators and SSA construction`

## Next phase
Phase 4: the optimization pass framework (common `Pass` interface, pass manager,
`--passes a,b,c`, per-pass statistics) and the classical passes: constant folding and
propagation (SCCP), DCE, algebraic simplification, copy propagation, CSE/GVN. Then, if they
can be done correctly: LICM, strength reduction, inlining, unrolling, bounds-check
elimination.

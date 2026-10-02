# Optimization Passes

ForgeCompile's middle end has 11 passes. They all operate on SSA IR, share one interface, and
are composed into pipelines by the pass manager. This document covers the framework and then
each pass: motivation, transformation, correctness argument, complexity, a **real
before/after example** (actual compiler output), tests and limitations. Measured effects are
in [RESULTS.md](RESULTS.md) (EXP-001).

```bash
uv run forgecompile passes                                   # list passes and presets
uv run forgecompile opt --passes copyprop,licm --stats f.mini   # optimized IR + per-pass report
uv run forgecompile run -O 2 examples/matmul.mini           # execute O2-optimized IR
uv run python scripts/fuzz_passes.py --programs 300          # differential fuzzing
```

## 1. Framework (`optimization/pass_manager.py`)

- **Interface.** `Pass.run(module) -> PassResult(changed, stats)`. Most passes are a
  `FunctionPass` with `run_on_function`. Inlining is a module pass, because it needs the
  call graph. Passes register themselves with `@register_pass` under a short name.
- **Pass manager.** It runs an ordered list of pass names and **verifies the SSA IR after
  every pass** (`ir/verify.py`). A broken pass is reported by name
  (`IR invalid after pass 'x'`) instead of surfacing later as a wrong output. Per pass it
  records: changed?, static instructions before/after, time, and the pass's own counters.
  These become optimization statistics (Phase 6) and ML/RL signals (Phases 7–9).
- **Pipelines.** A comma list (`--passes dce,cse,licm`), a preset (`-O 0/1/2`), or a pipeline
  file (`--passes my.pipeline`, with names separated by commas or whitespace and `#`
  comments).
- **Shared semantics.** Constant folding and the interpreter evaluate operations with the
  same code (`ir/evaluate.py`), so a folded constant can never differ from the run-time
  value.
- **Shared helpers** (`optimization/utils.py`): batched `Substitution` (O(n) per batch rather
  than per replacement), `fold`, `trivial_phi_value`, `is_removable_if_unused`,
  `is_speculatable`, and CFG edits that keep phis consistent.

### Presets

| Preset | Passes | Intent |
|--------|--------|--------|
| O0 | — | baseline: SSA as produced by lowering |
| O1 | constfold, copyprop, simplify, dce, simplifycfg | cheap cleanups |
| O2 | inline, sccp, copyprop, simplify, cse, licm, strength, bce, constfold, copyprop, dce, simplifycfg | everything, with cleanup after the loop passes |

The presets are hand-chosen starting points, **not tuned**. Finding better orders is
precisely the job of the ML/RL schedulers.

### Correctness strategy (applies to every pass)

1. **IR-text unit tests** for each pass, including *negative* tests for transformations it must
   not do. Examples: folding `sdiv 1, 0`, `x + 0.0 → x`, hoisting a possibly trapping
   division, removing a bounds check that can fail.
2. **Differential testing.** The unoptimized SSA IR is the reference. Each pass alone, every
   preset, and **random pass orderings** must preserve `(stdout, exit status)`. The ML/RL
   schedulers will apply arbitrary orders, so every order must be safe.
   - `tests/optimization/test_pass_differential.py` runs on every commit.
   - `scripts/fuzz_passes.py` runs at scale: 307 programs × 11 passes plus 921 random
     sequences, with 0 failures after the F-009 fix.
3. **SSA verification after every pass** (the pass manager).
4. **Mutation testing** of the safety guards. Five injected optimizer bugs were all caught
   (Phase 4 report).

## 2. Effects and why they matter

Every pass relies on the effect classes in [IR.md §3](IR.md#3-instruction-set):

- **Pure** instructions can be deleted, CSE'd and hoisted.
- **May-trap** instructions (`sdiv`/`srem` by a non-constant, `boundscheck`, `call`) can
  *never* be deleted as unused, nor speculatively hoisted, because the trap is observable
  (MiniLang has no undefined behaviour; D-010).
- **Memory** instructions (`load`) are neither CSE'd nor hoisted, because there is no alias
  analysis yet.

---

## 3. Passes

### constfold — constant folding with SSA propagation

- **Motivation.** Remove compile-time computable work, such as `mul 0, 4` from naive indexing
  or `2 * 3`.
- **Transformation.** Fold instructions whose operands are all constants, and substitute the
  result into every use. In SSA this substitution *is* constant propagation. It also folds
  trivial constant phis and `br <const>`, deletes in-range constant `boundscheck`s and
  unreachable blocks, and repeats until nothing changes.
- **Correctness.** Folding uses the exact run-time semantics. Operations that would trap are
  not folded.
- **Complexity.** O(k·n).
- **Example** (`print(m[0][3] + 2 * 3)`):
  ```
  before                                  after
  boundscheck 0, 2                        %t3: i64 = load %m[3]
  %t1: i64 = mul 0, 4                     %t5: i64 = add %t3, 6
  boundscheck 3, 4                        print %t5
  %t2: i64 = add %t1, 3
  %t3: i64 = load %m[%t2]
  %t4: i64 = mul 2, 3
  %t5: i64 = add %t3, %t4
  print %t5
  ```
- **Tests.** `test_scalar_passes.py::test_constfold_*`: chains, wrap-around and C division,
  no trap folding, branches, bounds checks, IEEE floats.
- **Limitations.** Not conditional: it cannot prove the loop-carried constant shown under
  sccp below.

### sccp — sparse conditional constant propagation (Wegman–Zadeck)

- **Motivation.** Some constants are only provable by assuming certain code is dead, *while*
  proving that code dead.
- **Transformation.** Optimistic fixed point over the lattice TOP → constant → BOTTOM, with
  CFG and SSA worklists. Phis only meet values from executable edges. Rewrite: substitute
  constants, delete dead constant instructions (judged after substitution; F-010), fold
  branches and in-range bounds checks, and remove dead blocks.
- **Correctness.** The analysis is a monotone fixed point, so constants are sound on every
  execution. Trapping folds evaluate to BOTTOM, so they are kept.
- **Complexity.** O(n + edges) lattice updates (each value lowers at most twice).
- **Example** (`x = 1; while i < 5 { if x != 1 { x = 2; } ... } print(x)`):
  ```
  before                                         after
  %x.2 = phi [1, entry], [%x.4, if.end]          (phi gone)
  %t2  = icmp ne %x.2, 1                         while.body: jump if.end
  br %t2, if.then, if.end                        (if.then deleted)
  %x.4 = phi [%x.2, while.body], [2, if.then]
  print %x.2                                     print 1
  ```
  `constfold` + `copyprop` cannot do this (`test_constfold_alone_cannot_do_this`).
- **Limitations.** Branches on values that depend only on `undef` stay TOP; their targets are
  left untouched (safe).

### copyprop — copy propagation and trivial-phi removal

- **Motivation.** Lowering assigns every variable through `copy`, and SSA construction keeps
  the copies. EXP-001 shows this is the single largest source of redundant instructions in
  hand-written code.
- **Transformation.** Replace uses of `%a = copy v` with `v`. Replace trivial phis
  (`phi [v, a], [v, b]`, or `phi [v, entry], [%self, latch]`) with `v`. Repeat.
- **Correctness.** The replacement dominates every use (IR.md §9). **Exception, found by the
  verifier:** a phi whose inputs are `undef` and a register `%v` must *not* become `%v`,
  because `%v` is defined inside the loop and does not dominate the header (F-009). Undef
  inputs may only be ignored when the unique value is a constant.
- **Example:**
  ```
  before                      after
  %b: i64 = copy %a           %t1: i64 = add %a, 1
  %t1: i64 = add %b, 1        ret %t1
  %c: i64 = copy %t1
  ret %c
  ```
- **Tests.** `test_copyprop_*`, including the F-009 regression.

### dce — dead code elimination

- **Motivation.** Remove computations whose results are unused, such as the leftovers of other
  passes and dead semi-pruned phis.
- **Transformation.** Mark-and-sweep. The roots are side-effecting and possibly-trapping
  instructions plus terminators. Liveness flows to operand definitions. Unmarked removable
  instructions are deleted. This removes dead *phi cycles* that a "no uses" loop misses.
- **Correctness.** Only pure instructions, `load`/`alloca`, and division by a non-zero constant
  are removable.
- **Complexity.** O(n).
- **Tests.** `test_dce_removes_dead_pure_code_and_dead_phi_cycles`,
  `test_dce_keeps_effects_and_possible_traps` (`sdiv 10, %x` stays; `sdiv 10, 2` goes).
- **Limitations.** No control-dependence-based branch removal and no dead-store elimination.

### simplify — algebraic simplification and canonicalization

- **Motivation.** Remove trivially known computations on non-constants.
- **Transformation.**
  - Integer identities: `x+0`, `x*1`, `x*0`, `x-x`, `x*-1 → neg x`, `0-x → neg x`, `x/±1`,
    `x%±1`, `neg neg x`, and compares `x ≤ x` / `x < x`.
  - Boolean identities: `not not b`, `icmp eq b, true`, `zext`-then-compare,
    `not (icmp p) → icmp p̄`.
  - Canonicalization: constants move to the right of commutative operations, which helps CSE.
- **IEEE care.** Only identities exact for all IEEE values: `x*1.0`, `x/1.0`, `x-(+0.0)`,
  `x+(-0.0)`. **Rejected** because they are wrong for −0.0, NaN or inf: `x+0.0`, `x*0.0`,
  `x-x`, `fcmp eq x,x`, and `not(fcmp)`. Each rejection has a test.
- **Example:**
  ```
  before                         after
  %t1 = not %b                   %t1 = not %b        (now dead; dce removes it)
  %t2 = not %t1                  br %b, ...
  br %t2, ...                    ret %x
  %t3 = mul %x, 1                %t5 = neg %x
  %t4 = add %t3, 0
  ret %t4
  %t5 = sub 0, %x
  ```

### simplifycfg — control-flow cleanup

- **Motivation.** Lowering's many small blocks each cost a `jump` per execution.
- **Transformation.** Fold `br c, X, X` and constant branches; merge a block into its unique
  predecessor; forward jump-only blocks (skipped when it would give a phi two inputs from one
  predecessor); delete unreachable blocks.
- **Correctness.** Paths are preserved, and phi inputs are rewired to the new predecessor.
- **Tests.** `test_simplifycfg_*`.

### cse — common subexpression elimination (dominator-scoped value numbering)

- **Motivation.** Repeated pure computations, especially index arithmetic.
- **Transformation.** Preorder walk of the dominator tree with a scoped hash table keyed by
  `(opcode, predicate, operands)`, with operands sorted for commutative operations. A
  dominated duplicate is replaced by the dominating register.
- **Correctness.** Pure instructions only. SSA operands cannot change. The dominating
  definition reaches every use. Loads are excluded (no alias analysis).
- **Complexity.** O(n) expected.
- **Example:**
  ```
  before                          after
  %t1 = mul %i, 3                 %t1 = mul %i, 3
  %t2 = add %t1, %j               %t2 = add %t1, %j
  %t3 = mul %i, 3                 %t4 = sub %t1, %j
  %t4 = sub %t3, %j
  ```
- **Tests.** Commutativity; no reuse across sibling branches; loads not merged.

### licm — loop-invariant code motion

- **Motivation.** Computations that are invariant in a loop are executed once per iteration
  rather than once per loop entry.
- **Transformation.** Innermost loops first. Ensure a preheader exists, then move
  speculatable instructions whose operands are defined outside the loop (or already hoisted)
  to the preheader.
- **Correctness.** Only *speculatable* instructions move: no effects, no possible trap, no
  memory read. Dominance is preserved (IR.md, THEORY §10).
- **Example:**
  ```
  before                              after
  for.body:                           entry:
      %t2 = mul %n, 3                     %t2 = mul %n, 3
      %t3 = add %s.2, %t2             for.body:
                                          %t3 = add %s.2, %t2
  ```
- **Measured downside (EXP-001).** LICM hoists speculatively, so code from a loop that runs
  **zero** times now runs once per loop entry. On one generated program this made the
  weighted cost **1.87× worse**, while the geometric mean still improved (0.978). This is
  kept deliberately (D-024): the classic algorithm without loop rotation behaves this way, and
  "when does LICM pay off?" is a real question for a learned scheduler.
- **Tests.** `test_licm_hoists_invariants_out_of_both_loops`,
  `test_licm_does_not_hoist_possible_traps_or_loads`.

### strength — induction-variable strength reduction

- **Motivation.** `i * k` in a loop over `i` can be maintained by adding `step*k` each
  iteration.
- **Transformation.** For a basic induction variable `%i = phi [init, pre], [%i + step, latch]`,
  replace `mul %i, k` with a new phi `%s = phi [init*k, pre], [%s + step*k, latch]`.
- **Correctness.** By induction, `%s = %i·k` at every iteration, and this holds modulo 2⁶⁴.
- **Profitability guard.** Only multiplies whose block dominates the latch, i.e. that run every
  iteration, are rewritten. Otherwise an add per iteration could cost more than a rare multiply
  (`test_strength_reduction_skips_conditional_multiply`).
- **Example:**
  ```
  before                                   after
  for.body:                                for.cond:
      %t2 = mul %i.2, 4                        %i.2.x4 = phi [0, entry], [%i.2.x4.next, for.latch]
      boundscheck %t2, 40                  for.body:
      %t3 = load %a[%t2]                       boundscheck %i.2.x4, 40
                                               %t3 = load %a[%i.2.x4]
                                           for.latch:
                                               %i.2.x4.next = add %i.2.x4, 4
  ```
- **Honest caveat.** On x86, `imul` costs about 3 cycles, and LLVM's own loop strength
  reduction runs on the generated code anyway, so a native gain is expected to be small.
  EXP-001 measures a ~0.5% cost reduction on the examples, under the interpreter cost model.

### bce — bounds-check elimination

- **Motivation.** `for i in 0..N { a[i] }` on `[T; N]` checks a fact that the loop condition
  already guarantees.
- **Transformation.** Delete `boundscheck %i, N` when the header tests `%i < END` with
  `END ≤ N`, the IV starts at a constant ≥ 0 with a constant step > 0, `END − 1 + step` cannot
  overflow, and the check is dominated by the loop body's entry (whose only predecessor is the
  header).
- **Correctness.** The proof sketch is in the pass docstring. Each check on the IV becomes a
  tautology. The tests include checks that *can* fail (`0..9` on `[int; 8]`, `-1..8`), which
  must be kept.
- **Example.** `boundscheck %i.2, 8` in `for.body` disappears (see EXP-001: 4% cost on the
  examples, on top of copyprop).
- **Limitations.** Only the IV itself (`a[i]`), not `a[i+1]` or `a[4*i]`. For `a[4*i]` the
  check stays whichever way `strength` and `bce` are ordered. On the 7 examples, the two
  orders give identical bounds-check counts and costs, measured as a check on a claim I had
  made without evidence (Phase 4 report).

### inline — inlining small non-recursive functions

- **Motivation.** Remove call overhead, and expose the callee body to the caller's
  optimizations (constant arguments, CSE, loops).
- **Transformation.**
  1. Split the block at the call.
  2. Clone the callee with fresh registers, mapping parameters to arguments.
  3. Each `ret` becomes a jump to the continuation. The result becomes a phi, or the value
     itself if there is one return.
  4. Callee allocas are hoisted to the caller's entry.

  Callees larger than 40 instructions (`INLINE_THRESHOLD`) and any function on a call-graph
  cycle are skipped.
- **Example:**
  ```
  before                          after
  %t1 = call @sq(7)               jump sq.entry
  print %t1                       sq.entry:  %sq.t1 = mul 7, 7; jump entry.cont
                                  entry.cont: print %sq.t1
  ```
- **Measured (EXP-001).**
  - Dynamic instruction count is unchanged, since `call`/`ret` become two `jump`s.
  - Weighted cost drops (examples 0.961).
  - Static size grows (examples **1.52×**).
  - The worst generated case was slightly costlier (1.012), because hoisted callee allocas
    run even when the call site does not.

## 4. Phase-ordering interactions (measured, EXP-001)

| Observation | Cause |
|-------------|-------|
| `bce`, `strength` alone: **no effect** (ratio 1.000) | they recognise IVs as `phi … add`, but before copyprop the latch value is `copy %t` |
| `copyprop+bce`: examples cost 0.956 → 0.918 | bce now finds the IVs |
| `constfold` vs `sccp` (run 1): constfold *better* | an SCCP rewrite bug (F-010), since fixed; after the fix sccp ≥ constfold |
| `licm` worst case 1.87× | speculative hoisting out of zero-trip loops |

These are not design accidents to be hidden. They are exactly why pass *ordering* is a
non-trivial decision problem (THEORY §13, ML_GUIDED_OPTIMIZATION.md).

## 5. Not implemented (deliberately)

- **Loop unrolling.** Full unrolling of constant-trip loops needs block cloning per iteration
  and induction-variable rewriting. It was deferred because Phase 6 must first show where
  loop overhead matters natively; LLVM also unrolls on its own.
- **Load CSE / LICM of loads / dead-store elimination.** These need alias analysis (array
  parameters may alias).
- **Loop rotation.** This would make LICM's speculation safe for profitability. It is
  documented as the fix for the measured LICM downside.

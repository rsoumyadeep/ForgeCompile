# Phase 7 Report — ML-Based Pass Selection

**PHASE:** 7 — supervised next-pass prediction and ML-guided scheduling
**STATUS:** ⚠️ Complete with a documented negative result (2026-10-03). The pipeline works and is
validated. The learned scheduler does **not** beat the fixed O2 pipeline.

## Implemented
Code was drafted in commit `62996de` (previous session) and validated and fixed in this one.
- **Features** (`ml/features.py`): 61 static IR features in 7 groups (size 4, opcodes 32,
  cfg 5, loops 4, memory 5, calls 3, opportunities 8). Docs, tests and model inputs agree on 61.
  The "69" mentioned earlier existed nowhere in the repository.
- **Dataset** (`ml/dataset.py`, `ml/data_pipeline.py`):
  - ε-greedy oracle trajectories, with the complete one-step outcome table at every state;
  - labels from real interpreter runs;
  - splits by program with disjoint seeds, plus a hand-written OOD split;
  - per-program RNG seeds;
  - a cache keyed by configuration + `src/forgecompile` tree hash (D-037);
  - named generator profiles (`loop_heavy`, `default`).
- **Models** (`ml/models.py`): majority, decision tree, random forest, histogram GBDT, and an
  MLP. Selection is by validation regret.
- **Policies and evaluation** (`ml/policies.py`, `ml/evaluate.py`):
  - O1/O2/frequency fixed pipelines, random, greedy oracle (optionally restricted to an action
    subset), model policy;
  - output-checked end-to-end evaluation, now also recording static size.
- **Validation tooling:** `scripts/validate_dataset.py` (EXP-007) and `scripts/e2e_sanity.py`
  (the whole pipeline in 31 s).
- **CLI:** `forgecompile opt|run --schedule {oracle,dqn}` chooses passes per program.

## Tests
- ML tests: 16 (`tests/ml/`), including the trap-free training profile and size tracking in
  evaluation.
- The pass differential tests now also require optimized IR to round-trip through text
  (F-016).
- Full suite on the server: 766 passed at `94b3649`.

## Experiments
- **EXP-007 (data validation):** passed every check:
  - identical datasets with 1 and 8 workers;
  - disjoint splits;
  - 0 traps;
  - 1,969 one-step outcomes replayed exactly.
- **EXP-004 (prediction):** GBDT test regret 0.0152 vs 0.0670 for the majority class. On OOD it
  is no better than the majority class (0.0277 vs 0.0269).
- **EXP-005 (end-to-end scheduling):** geomean cost ratio on generated test programs:
  - greedy oracle 0.553;
  - O2 0.558;
  - model 0.580;
  - frequency 0.582.

  On benchmarks the model is 10% worse than O2. Decisions cost about 1.1 s per program.

## Results
See RESULTS.md (EXP-004/005/007). Headline:
- O2 is within 1% of the greedy oracle, so the headroom for a one-step-greedy learner is about
  1%.
- The supervised imitation of the oracle is 4% worse than O2 on generated programs and 10%
  worse on benchmarks.
- Low per-decision regret does not translate into end-to-end schedule quality.

## Important decisions
- D-036: trap-free training workload.
- D-037: dataset cache keyed by the source tree.
- D-038: worker counts above the default cap for interpreter experiments.
- D-039: NumPy-only DQN (recorded).

## Problems encountered → how they were solved
- **10% of training programs trapped** (found by the validator's first run). Fixed in the
  training profile (D-036).
- **F-016:** strength reduction created unparseable register names for negative factors. This
  crashed the first full dataset build, and the real error was hidden because `IRParseError`
  was not picklable. Fixed with name sanitizing, a picklable error, and a round-trip check in
  the differential tests.
- **Coverage gap** (EXP-004 diagnosis): `bce` never appears as a training label, because the
  generator never indexes arrays by a plain induction variable. Documented as a limitation and
  not "fixed" by looking at OOD data, which would leak the OOD set into design.
- **Inference overhead:**
  - single-row scikit-learn GBDT inference takes 24–50 ms;
  - feature extraction takes 4 ms;
  - the overhead is an implementation artefact, reported as measured.

## Known limitations
- The cost model is the interpreter's (native validation: EXP-002, EXP-008).
- Features are static counts, with no profile data.
- Training workloads are synthetic and do not cover IV-indexed loops.
- The policy is greedy, so errors compound.

## Files changed
New: `scripts/validate_dataset.py`, `scripts/e2e_sanity.py`,
`experiments/EXP-007-dataset-validation/*`, curated EXP-004/005 results.
Modified:
- `ml/data_pipeline.py`, `ml/evaluate.py`, `ml/policies.py`;
- `testing/program_generator.py`;
- `ir/function.py`, `ir/parser.py`, `optimization/passes/strength.py` (F-016);
- `utils/environment.py`, `cli/ir_commands.py`;
- tests;
- `ML_GUIDED_OPTIMIZATION.md`, `EXPERIMENTS.md`, `RESULTS.md`, `DECISIONS.md`, `FAILURES.md`,
  `THEORY.md` §13–14, `HOW_TO_STUDY.md` §13.

## Commits
`46a5643`, `bc4eaf8`, `f08dbe1`, `ccc8a2b`, `94b3649`, `52a6abb`, `152daad`, `039d03b`
(see `git log`).

## Next phase
Phases 8–9: does an RL agent with lookahead find the non-greedy wins? O2 beats the greedy oracle
on 9/100 programs, so such wins exist (EXP-006).

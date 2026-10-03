# Phase 10 Report — Experimental Study and Ablations

**PHASE:** 10 — answering the research questions, with ablations
**STATUS:** ✅ Complete (2026-10-03). All ten research questions are answered with measured
evidence (RESULTS.md, "Summary"). Most answers are negative, and the reasons are quantified.

## Implemented
- **EXP-008** (`experiments/EXP-008-native-policies/run.py`): native, correctness-gated
  timing of every policy's schedule on the 10 kernels, with code size, pass time, decision time
  and compile time.
- **EXP-009** (`experiments/EXP-009-ml-ablations/run.py`): feature-group, data-size and
  distribution-shift ablations of the supervised scheduler. Conditions run in parallel.
- **EXP-010** (`experiments/EXP-010-rl-ablations/run.py`): step penalty, discount, size
  weight and action-space ablations of the RL formulation, with oracle-greedy restricted to
  each action space as reference.
- **EXP-011** (`experiments/EXP-011-headroom/run.py`): beam search over pass sequences to
  bound what *any* scheduler could gain.
- **EXP-012** (`experiments/EXP-012-dqn-followup/run.py`): fair policy wrappers and scaled
  training for DQN.
- **Supporting changes:**
  - generator profiles in the dataset config;
  - configurable action spaces;
  - code size in the end-to-end evaluation;
  - `rl/training.py`;
  - the DQN no-retry option;
  - the post-hoc diagnostic `scripts/dqn_one_step_regret.py`.

## Tests
New tests: action-space restriction (environment, DQN policy, oracle), the training job, the
no-retry wrapper, chain-MDP bootstrapping, size tracking, the source-tree cache key, and dirty-flag
semantics. The full suite was 772 tests at the end of the phase (server).

## Experiments and results (all pre-registered before their full runs)
| ID | Question | Headline |
|---|---|---|
| EXP-002 | Is the interpreter cost a good proxy? | Weak: Spearman 0.29. It overrates loop-code motion and underrates branch removal. |
| EXP-003 | ForgeCompile vs LLVM, reproducibility | fc-O2 1.18×; LLVM -O2 7.4×; median run-to-run difference 0.53%. |
| EXP-008 | Native effect of learned schedules | None beats O2 beyond noise. The strength-reduction blind spot explains the loop_nest anomaly. |
| EXP-009 | Features, data, distribution | Redundant features; flat learning curve; asymmetric transfer. |
| EXP-010 | Reward and action space | λ and γ irrelevant, size weight works, action space matters most. Bit-exact reproduction of EXP-006. |
| EXP-011 | Headroom | Beam search: only about 1% above O2. |
| EXP-012 | DQN fairness and scale | No-retry closes 31–63% of the gap; 4× training does not help. |

## Important decisions
- D-036 to D-040: trap-free workload, source-tree cache key, worker policy, NumPy DQN, dirty
  semantics.
- Design choices inside the experiments:
  - EXP-006 was kept exactly as pre-registered, and its follow-up was a separate,
    pre-registered EXP-012.
  - DQN checkpoints for native timing were chosen by validation score only.
  - Post-hoc analyses are labelled as such.

## Problems encountered → how they were solved
- **F-017:** 16 workers × full-width library thread pools pushed a shared server to a load
  average of 295. I killed my job, marked the run aborted, and capped threads per process.
- **Proxy misalignment:** this was itself a finding (EXP-002, EXP-008), not a bug.
- **Redundant waiting and polling** during long runs. Solved with per-validation progress logs
  and one background waiter per job.

## Known limitations
- One shared machine, within-session reproducibility.
- The interpreter-cost proxy (all ML/RL training).
- LLVM -O0 as the measurement point.
- Synthetic training workloads with known coverage gaps.
- Small, simple models (GBDT, 2-layer DQN).
- No hyperparameter search for DQN beyond the pre-registered and ablated settings.

## Files changed
`experiments/EXP-002…012/` (scripts and curated results), `scripts/*`, `src/forgecompile/{ml,rl,utils}`,
tests, and docs (EXPERIMENTS, RESULTS, DECISIONS, FAILURES, THEORY §13–17, HOW_TO_STUDY §13–18,
INTERVIEW_QUESTIONS, ROADMAP).

## Next phase
Phase 11: hardening, final documentation, fresh-clone reproduction and the final audit.

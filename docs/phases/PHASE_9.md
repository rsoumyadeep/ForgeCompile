# Phase 9 Report — RL Optimization Agent

**PHASE:** 9 — a reinforcement-learning pass scheduler
**STATUS:** ⚠️ Complete with a documented negative result (2026-10-03). The agent is implemented,
tested, trained on the server (3 + 3 seeds, about 450k environment steps) and evaluated on held-out
programs. No DQN variant beats O2, the supervised model or the greedy oracle.

## Implemented
- **Double DQN in NumPy** (`rl/dqn.py`, D-039):
  - MLP 74 → 128 → 128 → 12 with a hand-written backward pass;
  - Adam, a replay buffer (50k), a hard target update every 250 steps, Huber loss;
  - ε-greedy exploration with linear decay;
  - fixed `log1p` + standardization fitted during warm-up;
  - progress logged at every validation (added after EXP-006, so long runs are observable).
- **`DQNPolicy`**: greedy policy for `ml.policies.schedule`. An optional **no-retry wrapper**
  never re-applies a pass in an unchanged IR state, the same rule as the supervised
  `ModelPolicy` (added after the EXP-006 diagnosis).
- **`rl/training.py`**: a self-contained training job (own cost cache, best-validation
  checkpoint). Seeds and ablation conditions run in parallel processes.
- **Configurable action space** in the environment, the DQN policy and the greedy oracle.
- **CLI:** `forgecompile opt|run --schedule dqn [--checkpoint …]`.

## Tests
`tests/rl/`, 15 tests:
- numerical gradient check of the MLP;
- Adam on a linear target;
- DQN on a one-step bandit **and on a two-step chain MDP that needs bootstrapping** (rules out a
  TD-update bug);
- save/load round trip;
- short training inside warm-up;
- restricted action spaces;
- the training job's checkpointing;
- the no-retry wrapper never repeating a (state, pass) pair.

The CLI tests cover `--schedule dqn` and its conflicts with `-O`/`--passes`.

## Experiments
- **EXP-006** (pre-registered, 3 seeds × 3,000 episodes): DQN generated-test cost ratio
  0.632–0.660 vs O2 0.558, oracle 0.553 and supervised model 0.580. Diagnosis: the policies
  repeat one no-op pass. The action gap λ = 0.002 is below the Q-function's error.
- **EXP-012** (pre-registered follow-up):
  - The no-retry wrapper closes 31–63% of the gap. The best result is 0.589.
  - 4× more training does not help: the best validation checkpoints come from episodes
    100–1,800 of 12,000.
- Invalid transformations: **0** in every run.

## Results
Research question 2 ("does RL improve over heuristic scheduling?"): **no, in this setting.**
EXP-011 explains why. Even beam search over all 12-pass schedules gains only about 1% over O2,
which leaves the agent almost nothing to learn relative to its estimation noise.

## Important decisions
- D-039: NumPy DQN.
- The EXP-012 design keeps EXP-006 exactly as pre-registered and tests the fair-wrapper
  explanation separately, deciding on validation data.

## Problems encountered → how they were solved
- **The policy degenerated into repeating no-op passes.** Diagnosed from per-program action
  logs. Addressed in evaluation by the no-retry wrapper (a policy-parity fix). The underlying
  small action gap is ablated in EXP-010 (λ = 0.01).
- **No progress visibility during long training:** per-validation logging was added.
- **ptrace was restricted on the server,** so live introspection (py-spy) was impossible.
  Checkpoint modification times served as a progress signal until logging existed.
- **F-017 thread oversubscription** (during the follow-up chain): per-process thread caps.

## Known limitations
- Value-based RL on a POMDP with about 1% headroom. A policy-gradient or offline-RL agent
  pre-filled with the supervised data's complete outcome tables was not tried (future work).
- EXP-006 ran before the thread caps, so retraining reproduces it only up to small BLAS
  floating-point differences.
- The checkpoints selected by validation are close to untrained networks. Learning adds little.

## Files changed
`rl/dqn.py`, `rl/training.py`, `rl/env.py`, `ml/policies.py`, `cli/ir_commands.py`,
`tests/rl/test_rl.py`, `tests/optimization/test_opt_cli.py`, `experiments/EXP-006…`,
`experiments/EXP-012…`, `scripts/dqn_one_step_regret.py`, and the docs (EXPERIMENTS, RESULTS,
RL_FORMULATION, THEORY §16, HOW_TO_STUDY §15, INTERVIEW_QUESTIONS).

## Next phase
Phase 10: ablations (EXP-009 supervised, EXP-010 RL), native evaluation (EXP-008), and the
deferred Phase 6 measurements (EXP-002, EXP-003).

# Phase 8 Report — RL Environment

**PHASE:** 8 — pass scheduling as a Markov decision process
**STATUS:** ✅ Complete (2026-10-03). The environment is implemented, unit-tested and used for
about 97,000 training steps (EXP-006) without a single invalid transformation.

## Implemented
- `rl/env.py`, `PassSchedulingEnv`, with a Gym-style API (`reset`, `step` →
  `(obs, reward, terminated, truncated, info)`) and no gym dependency.
  - **State:** (M, t), the SSA module and the step.
  - **Observation:** 74 numbers: 61 IR features, the remaining-step fraction, and a one-hot of
    the previous action.
  - **Actions:** 11 passes + stop, or any subset of the passes + stop (`actions=`, for the
    action-space ablation).
  - **Transition:** apply the pass to a copy (IR verified), then re-check the observable output
    against the unoptimized program (memoized by IR hash).
  - **Reward:** w_c ΔC/C₀ + w_s ΔS/S₀ − λ per applied pass. It telescopes to the total relative
    improvement minus λ·K.
  - **Termination:** stop; horizon T = 12 (observed, so a true terminal state); or an invalid
    transformation (−κ, counted).
  - Costs are memoized by IR hash and shared across episodes.
- The full derivation is in [RL_FORMULATION.md](../RL_FORMULATION.md), and the MDP/POMDP theory
  in THEORY §15.

## Tests (`tests/rl/`)
- Observation shape and the empty previous-action vector at t = 0.
- **Telescoping:** the sum of rewards equals the total relative improvement minus λ·K.
- Stop and horizon semantics.
- An invalid transformation is penalized and counted (monkeypatched broken pass).
- Restricted action spaces in the environment, the DQN policy and the oracle.

## Experiments
- Used by EXP-006 (3 seeds × 3,000 episodes, about 97k steps): **0 invalid transformations**.
- Used by EXP-010 (reward and action-space ablations) and EXP-012.

## Results
- The environment behaves as specified.
- The *agents* trained in it do not beat O2 (Phase 9 report, EXP-006).

## Important decisions
The design rationale in RL_FORMULATION.md §3 covers:
- relative, telescoping reward;
- λ as a compile-time proxy;
- γ = 1;
- the step counter in the observation;
- the previous action in the observation.

D-039 covers the NumPy agent.

## Problems encountered → how they were solved
- Observable-output checks ran an interpreter per step. They are now memoized by IR hash
  (commit `b2433db`, previous session).
- A training run that ended inside the warm-up left the normalizer unset. Fixed in `a253566`
  (previous session) and covered by a regression test.

## Known limitations
- POMDP: the features are a lossy summary of the IR.
- The reward uses the interpreter cost model, not native time (EXP-002, EXP-008).
- The step penalty is a design constant, not a measured compile time.
- The action gap between a useful pass and a repeated no-op is only λ = 0.002, which proved too
  small for DQN (EXP-006 diagnosis; ablated in EXP-010).

## Files changed
`rl/env.py` (configurable action space), `tests/rl/test_rl.py`, `RL_FORMULATION.md` (observation
size), THEORY §15, HOW_TO_STUDY §14.

## Next phase
Phase 9: the agent (EXP-006, EXP-012).

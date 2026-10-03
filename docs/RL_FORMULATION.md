# RL Formulation of Pass Scheduling

Code: `src/forgecompile/rl/env.py` (environment) and `src/forgecompile/rl/dqn.py` (agent).
Results are in [RESULTS.md](RESULTS.md) and [EXPERIMENTS.md](EXPERIMENTS.md).

## 1. Why pass scheduling is a sequential decision problem

A compiler applies passes one after another. Each pass changes the program, and so changes
what every later pass can do:

- `bce` and `strength` do nothing until `copyprop` has run (EXP-001, D-023);
- `inline` exposes constants to `sccp`;
- `licm` can make code slower when a loop never runs.

The value of a pass therefore depends on the *state* it is applied to, and choosing well can
require looking ahead. A pass with little immediate benefit may enable a large later one.
These are exactly the conditions RL is designed for: decisions with delayed consequences in a
changing state. Whether *delayed* rewards are actually significant in this compiler is an
empirical question, answered by comparing the RL agent with the one-step-greedy supervised
policy (Phase 9).

## 2. The MDP

Let 𝒫 be a set of programs (the training split of generated programs).

| Symbol | Definition in ForgeCompile |
|--------|----------------------------|
| **S** | states s = (M, t): the current SSA IR module M and the step t ∈ {0,…,T} |
| **O** | observation o = [φ(M), (T−t)/T, onehot(a_{t−1})] ∈ ℝ⁷⁴: φ = 61 static features (`ml/features.py`), 1 remaining-step fraction, 12-way one-hot of the previous action (all zeros at t = 0) |
| **A** | {constfold, sccp, copyprop, dce, simplify, simplifycfg, cse, licm, strength, bce, inline, **stop**}, so \|A\| = 12 |
| **P** | deterministic: P((pass_a(M), t+1) \| (M, t), a) = 1. `stop` and t = T are terminal. |
| **ρ₀** | initial state (M₀(p), 0), with p ~ Uniform(𝒫) and M₀(p) the unoptimized SSA IR |
| **R** | r_t = w_c·(C(M_t) − C(M_{t+1}))/C(M₀) + w_s·(S(M_t) − S(M_{t+1}))/S(M₀) − λ, for every applied pass; 0 for `stop` |
| **γ** | 1 (undiscounted, finite horizon T = 12) |
| **Termination** | `stop`; t = T (truncation, which is terminal because T−t is observed); or an invalid transformation (penalty −κ) |

**Cost:**
- C(M) is the IR-interpreter weighted cost of running M. It predicts native time only weakly
  (EXP-002: Spearman 0.29).
- S(M) is the static instruction count.
- The default weights are w_c = 1, w_s = 0, λ = 0.002 and κ = 1. Reward-weight sensitivity is
  a Phase 10 ablation.

## 3. Design decisions

**Reward = relative improvement, which telescopes.** For an episode that applies passes until
step K:

    Σ_{t<K} r_t = w_c·(C(M₀) − C(M_K))/C(M₀) + w_s·(S(M₀) − S(M_K))/S(M₀) − λ·K

The return depends only on the *final* program and the number of passes. Consequences:
- An agent cannot "farm" reward by oscillating between states. Cycles sum to zero improvement
  and cost λ per step.
- Normalizing by C(M₀) makes rewards comparable across programs of very different sizes.
  Without it, the agent would be dominated by the most expensive programs.

**Step penalty λ.** Each pass costs compile time. Without λ, an agent would be indifferent
between stopping and padding with no-op passes. λ = 0.002 is small: one pass must improve cost
by more than 0.2% to pay for itself. It is a stated design parameter, not a measured
compile-time cost, and an ablation varies it.

**Why the remaining-step fraction is in the observation.** With a hard horizon T, the optimal
action depends on how many steps remain: a long enabling sequence is worthless with one step
left. Observing (T−t)/T makes the problem Markov in time. A truncated state at t = T is then a
true terminal state, so bootstrapping stops there correctly.

**Why the last action is in the observation.** Static features can be identical before and
after a no-op pass. The previous action lets the agent learn not to repeat a pass that just did
nothing.

**γ = 1.** The objective is the final program's quality, which is undiscounted. With T = 12 the
return is bounded, so γ = 1 is well defined. γ < 1 would bias the agent toward immediate gains,
i.e. toward greedy behaviour. It is ablated in Phase 10.

**Partial observability.** φ(M) is a lossy summary of M: two different programs can share a
feature vector. Strictly, the agent solves a POMDP with a fixed observation map. This is a known
limitation, discussed with the results.

## 4. Avoiding exploitable rewards

| Possible exploit | Why it cannot pay off here |
|------------------|----------------------------|
| Delete observable behaviour to save cost | Passes are semantics-preserving. The environment re-checks every step's output against the unoptimized program, and a violation is an *invalid transformation* (−κ, episode ends, counted). |
| Oscillate between two states | The rewards telescope, so a cycle earns 0 − λ·length |
| Pad with no-op passes | λ > 0 per pass |
| Game the cost model (e.g. replace a mul with an add that is not cheaper natively) | A real risk, inherited from the proxy C. EXP-002 confirmed it: strength reduction is predicted −6% but measured +0.8%. EXP-008 therefore reports native timings of the learned schedules. |
| Shrink one huge program and ignore the others | Rewards are normalized per program |

Invalid transformations are measured and reported (the brief requires this). With correct passes
the expected count is 0. Any non-zero count is a compiler bug and goes into FAILURES.md.

## 5. Environment API (`rl/env.py`)

```python
env = PassSchedulingEnv(programs, horizon=12, reward=RewardConfig(step_penalty=0.002), seed=0)
obs, info = env.reset()  # random training program (or reset(program))
obs, reward, terminated, truncated, info = env.step(action_index)
env.stats  # program, initial/final cost, passes, return, invalid flag
env.invalid_transformations  # running count
```

The environment is Gym-compatible in spirit, without the dependency. It is reproducible: the
program choice comes from a seeded RNG, transitions are deterministic, and costs are exact.
Costs are memoized by IR hash and shared across episodes, which matters because environment
steps are interpreter runs.

## 6. The agent

See `rl/dqn.py`:
- Double DQN with a NumPy MLP (2 × 128 ReLU) and Huber loss;
- Adam, experience replay (50k), and a hard target update every 250 steps;
- ε-greedy exploration from 1.0 to 0.05;
- a log1p plus fixed standardization of observations, fitted during the warm-up.

The best checkpoint is selected by validation score, never by test score. The rationale for
each choice is in the module docstring and in DECISIONS.md.

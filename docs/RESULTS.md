# Results

Only measured results appear here. Each one is linked to its experiment in
[EXPERIMENTS.md](EXPERIMENTS.md) and to a curated results directory with full metadata (git
commit, clean/dirty flag, environment, seed). Negative results are included.

## EXP-001 — Per-pass effects on IR-level work (Phase 4)

**Setup:** 7 example programs and 200 generated programs (seeds 0–199). Metrics come from the
deterministic IR interpreter: dynamic instruction count, and a weighted cost under *assumed*
latencies. These are **not** native runtimes; Phase 6 will measure those. Data:
`experiments/EXP-001-pass-effects/results.md` (run 2, commit `453feab`).

Geometric-mean ratio, optimized / unoptimized (lower is better):

| configuration | examples: cost | generated: cost | worst single program (generated) |
|---|---:|---:|---:|
| preset:O2 | **0.828** | **0.537** | 0.912 |
| preset:O1 | 0.942 | 0.576 | 0.932 |
| sccp | 0.995 | 0.622 | 0.963 |
| constfold | 0.995 | 0.627 | 0.963 |
| copyprop | 0.956 | 0.976 | 1.000 |
| copyprop+bce | 0.918 | 0.976 | 1.000 |
| inline | 0.961 | 0.991 | 1.012 (worse) |
| licm | 0.986 | 0.978 | **1.871 (worse)** |
| bce alone, strength alone | 1.000 | 1.000 | 1.000 |

**Main findings**

1. O2 is best on average on both workload groups.
2. **Phase ordering matters measurably.** `bce` and `strength` do nothing unless `copyprop`
   runs first.
3. **Negative result: LICM can make code worse.** One program got 1.87× more costly, because
   code was hoisted out of loops that never execute (speculation without loop rotation).
4. **Negative result: inlining increases static code size** by 52% on the examples, and can
   slightly increase work.
5. Effects depend strongly on the workload distribution. Constant folding dominates on
   generated programs, while copy propagation and loop passes matter on hand-written code.
6. The experiment itself found a missed-optimization bug in SCCP (F-010). The run-1 data
   showing it is kept.

## EXP-007 — The ML/RL training data are deterministic, leak-free and reproducible (Phase 7)

**Setup:** 137 programs (80/20/20 generated + 17 hand-written OOD), commit `46a5643`, server.
Data: `experiments/EXP-007-dataset-validation/report.json`.

| check | result |
|---|---|
| 1-worker vs 8-worker build | identical (SHA-256 `016551c9…`) |
| split disjointness (names and source text) | disjoint |
| trapping programs / programs without output | 0 / 0 |
| from-scratch replay: states, one-step outcomes | 179 states, 1,969 outcomes: all features, costs and outcomes identical; output preserved in every case |
| median initial cost, train vs OOD | 6.4k vs 307k |
| STOP share of labels, train vs OOD | 6% vs 21% |

The first (local) validation attempt found that 10% of training programs trapped; fixed by D-036.

## EXP-004 — Next-pass prediction from static IR features (Phase 7)

**Setup:** 400/100/100 generated programs (2,966/736/734 states) + 17 hand-written OOD programs
(113 states); model selected on validation regret; commit `94b3649`. Data:
`experiments/EXP-004-pass-prediction/`.

| split | model | mean regret | near-optimal | accuracy |
|---|---|---:|---:|---:|
| test | gradient boosting (selected) | **0.0152** | 0.620 | 0.525 |
| test | majority class | 0.0670 | 0.290 | 0.213 |
| OOD | gradient boosting | 0.0277 | 0.513 | 0.327 |
| OOD | majority class | **0.0269** | 0.478 | 0.248 |

- In distribution, the model has 4.4× lower regret than the majority baseline.
- **Out of distribution it is no better than the majority baseline.** The main cause is
  coverage: `bce` is the best pass in 10 of 113 OOD states but never in training, because the
  generator never emits induction-variable array indexing.

## EXP-005 — End-to-end ML-guided scheduling vs fixed pipelines (Phase 7–8) — negative result

**Setup:** greedy application of the EXP-004 model, budget 12 passes, all outputs checked;
geomean final/initial interpreter cost. Data: `experiments/EXP-005-ml-scheduling/`.

| policy | generated test (100) | benchmarks (10) | examples (7) | decision ms / program |
|---|---:|---:|---:|---:|
| oracle-greedy (upper bound for greedy) | 0.553 | 0.741 | 0.825 | 2,650 |
| **O2** | **0.558** | **0.741** | **0.828** | 0 |
| model (GBDT) | 0.580 | 0.815 | 0.867 | 1,086 |
| frequency order | 0.582 | 0.747 | 0.838 | 0 |
| best of 3 random 12-pass schedules | 0.571 | 0.829 | 0.871 | 0 |

- **The learned scheduler does not beat O2. It is 4% worse on generated programs and 10% worse
  on benchmarks, at about 1 s of decision time per program.**
- O2 is within 1% of the greedy oracle, so the headroom for any one-step-greedy policy is about
  1%.
- O2 beats the greedy oracle on 9/100 programs, which is evidence that some gains need
  lookahead (EXP-006).

## EXP-006 — Double DQN pass scheduling (Phase 9) — negative result

**Setup:** 3 seeds × 3,000 episodes on 400 training programs; best checkpoint chosen on 40
validation programs; held-out evaluation with outputs checked. Commit `039d03b`. Data:
`experiments/EXP-006-rl-scheduling/` (including checkpoints and training curves).

| policy | generated test (100) | benchmarks (10) | examples (7) | decision ms |
|---|---:|---:|---:|---:|
| oracle-greedy | 0.553 | 0.741 | 0.825 | 2,153 |
| **O2** | **0.558** | **0.741** | **0.828** | 0 |
| supervised model | 0.580 | 0.815 | 0.867 | 420 |
| DQN (seeds 0 / 1 / 2) | 0.632 / 0.660 / 0.641 | 0.894 / 0.956 / 0.952 | 0.967 / 0.963 / 0.967 | 25–39 |

- **DQN does not beat O2, the supervised model or the greedy oracle on any program group.** All
  three seeds agree.
- There were 0 invalid transformations.
- Diagnosed failure: the policies repeat one no-op pass (e.g. `licm` ×12). The −0.002 per-step
  penalty is a smaller action gap than the Q-function's error. The DQN also lacked the supervised
  policy's no-retry rule; that follow-up is EXP-012.

## EXP-011 — Headroom: how much better than O2 can any 12-pass schedule be? (Phase 10)

**Setup:** beam search over pass sequences (widths 1/4/16, budget 12, best-at-any-depth, IR-hash
deduplication), on 100 test + 17 OOD programs. Measurement only. Commit `dbabcbf`. Data:
`experiments/EXP-011-headroom/`.

| programs | O2 | beam-1 (greedy) | beam-4 | beam-16 |
|---|---:|---:|---:|---:|
| generated (100) | 0.558 | 0.552 | 0.552 | **0.552** |
| benchmarks (10) | 0.741 | 0.741 | 0.741 | 0.741 |
| examples (7) | 0.828 | 0.825 | 0.825 | 0.825 |

- **The best schedules that beam search finds are only about 1% better than O2 on average**
  (0% on the hand-written kernels). They are > 1% better on 22/100 generated programs (up to
  12%), and never worse.
- The learnable headroom in this action space is therefore tiny. That is the main reason the
  supervised (EXP-005) and RL (EXP-006) schedulers cannot beat O2.

## EXP-012 — DQN follow-up: equal wrappers and 4× training (Phase 9) — negative result

**Setup:** EXP-006 checkpoints re-evaluated with the supervised policy's no-retry rule (Part A).
Then 3 seeds × 12,000 episodes, selected on validation with that rule (Part B). Commit
`e37527c`. Data: `experiments/EXP-012-dqn-followup/`.

| policy (generated test, geomean cost ratio) | plain | + no-retry |
|---|---:|---:|
| O2 | 0.558 | — |
| EXP-006 DQN (seeds 0/1/2) | 0.632 / 0.660 / 0.641 | 0.609 / 0.625 / **0.589** |
| scaled DQN, 4× training (seeds 0/1/2) | 0.650 / 0.679 / 0.681 | 0.604 / 0.632 / 0.631 |

- The no-retry rule closes 31%, 34% and 63% of DQN's gap to O2 (seeds 0, 1, 2).
- **4× more training does not help:**
  - the best validation checkpoints came from episodes 100, 1,800 and 1,800 of 12,000;
  - scaled agents are no better than the EXP-006 agents.
- No DQN variant beats O2. There were 0 invalid transformations in about 350k training steps.

## EXP-009 — Supervised-scheduler ablations: features, data, distribution (Phase 10)

**Setup:** EXP-004 protocol per condition (selection on validation), plus end-to-end greedy
scheduling; 17 conditions; commit `e37527c`. Data: `experiments/EXP-009-ml-ablations/`.

| question | finding |
|---|---|
| Which features matter? | They are highly redundant. Dropping any one group barely moves test regret (0.0127–0.0152). The hand-made `opportunities` group *alone* recovers 96% of the regret reduction over majority. On validation, dropping it hurts most. |
| How much data? | **Flat learning curve.** 25 programs (188 states) give regret 0.0149 vs 0.0152 with 400 programs; there is no monotonic trend. |
| Distribution shift? | **Asymmetric.** `loop_heavy` → `default` transfers well (regret 0.0097, better than the in-distribution `default` model's 0.0117). `default` → `loop_heavy` costs 6% end to end (0.616 vs 0.580). |
| Beats O2 anywhere? | **No.** Best end-to-end 0.572 vs O2 0.558 (`loop_heavy`) and 0.513 vs 0.505 (`default`). OOD: 7–17% worse than O2. |

## EXP-010 — RL formulation ablations: reward, discount, action space (Phase 10)

**Setup:** 7 conditions × 2 seeds × 2,000 episodes; evaluated plain and with no-retry; references
O2 and oracle-greedy restricted to each action space; commit `e37527c`. Data:
`experiments/EXP-010-rl-ablations/`.

| question | finding (generated test, geomean cost ratio) |
|---|---|
| Does a larger step penalty help (λ 0.002 → 0.01)? | **No** (0.650 vs 0.646, mean of seeds). λ = 0 is slightly worse (0.673). |
| Does discounting matter (γ 1 → 0.9)? | **No** (< 1% change). |
| Does a size term steer the agent (w_size = 0.5)? | **Yes:** static size ratio 0.359 vs 0.428 at no cost penalty. |
| Does the action space matter? | **Yes.** Without copyprop, even the greedy oracle drops (0.565 vs 0.553; benchmarks 0.856 vs 0.741). With only the O1 passes, DQN gets much closer to its oracle (≈ 9% vs ≈ 17%). |
| Does any variant beat O2 (0.558)? | **No.** Best 0.601. The no-retry wrapper helps in all 14 trainings (1.6–9.5%). |

EXP-010's base condition reproduced EXP-006's seeds 0 and 1 bit-exactly: identical validation
scores and test ratios.
